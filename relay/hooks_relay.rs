//! hooks-relay — transport-only Unix-socket relay for Claude Code hook events.
//!
//! Plan 00290, Task 3.1. Contract: DESIGN-socket-relay.md §3.1 (binding).
//!
//! CONSTRAINTS THIS FILE MUST HONOUR (the auditability of this single file is
//! the whole justification for shipping a compiled artefact at all):
//!
//! - **std only, zero crates.** No Cargo.toml, no Cargo.lock, no dependency
//!   tree to audit. Built with plain `rustc --target *-unknown-linux-musl`
//!   (see relay/build.sh), yielding a fully static binary.
//! - **No policy, with one narrow carve-out.** The relay never parses the
//!   REQUEST, never reads config, never starts the daemon, never retries,
//!   never writes files. Every allow/deny decision for a request the daemon
//!   actually judged stays in the Python daemon. The one exception (Plan
//!   00466 N40 review 2 MA3): when the exchange fails mid-flight -- a
//!   timeout, an I/O error, an oversized or EMPTY response -- on the
//!   PreToolUse socket specifically, this file fabricates a deny rather than
//!   the ambiguous `{}` it used to. `{}` is ALSO the shape a genuinely
//!   judged "allow, nothing to add" verdict takes, so on a transport
//!   failure it is indistinguishable from a real judged allow to whatever
//!   reads stdout next -- exactly the python transport's OWN
//!   `_pretooluse_response_looks_valid` contract, mirrored here because nothing
//!   downstream of a fail-open `{}` could ever apply it. The socket's
//!   identity is read from WHICH socket path argv names it -- already this
//!   file's documented mechanism for knowing which request kind it is
//!   relaying -- not a new dependency on hook semantics. Before that deny,
//!   the request is handed whole to the `--fallback` forwarder
//!   (`judge_via_fallback`, Plan 00466 N126) so `init.sh`'s one recovery
//!   carve-out judges it; the relay itself still never parses the request.
//! - **Connect FIRST, before touching stdin.** While stdin is unread, the
//!   bash forwarder can still be exec'd as a complete substitute; the moment
//!   one stdin byte is consumed that door closes, and every later failure
//!   must fail OPEN (`{}` on stdout, exit 0) because Claude Code must always
//!   receive valid JSON — mirroring the bash rung's `emit_hook_error`
//!   contract. `{}` carries no policy: it is "no opinion", the same thing a
//!   passthrough hook emits today. The PreToolUse exception is above: its
//!   request is kept as it is read, so it can be replayed whole.
//! - **`ensure_daemon` never moves.** Daemon-down lands here as a connect
//!   failure, which execs the bash forwarder with stdin intact — so
//!   auto-start and cold-start behaviour stay exactly today's bash code path.
//!
//! Wire framing (DESIGN §2): stream stdin → socket, half-close the write side
//! (EOF marks end-of-request), read the response to EOF, copy it to stdout.
//! No newline framing in either direction — the relay is a pure byte pump.
//!
//! Argv:  hooks-relay <socket-path> [--fallback <script>] [--timeout-ms <n>]
//!                    [--no-fallback]
//! Exit codes:
//!   0  — response delivered, or a mid-exchange failure emitted a fail-open
//!        `{}` (non-PreToolUse) or a fail-closed deny (PreToolUse socket)
//!   10 — connect failed and no `--fallback` was given (diagnostic mode)
//!   11 — timeout      (only with `--no-fallback`: harness diagnostic mode)
//!   12 — I/O error or oversized response (only with `--no-fallback`)
//!   13 — argv usage error (unreachable via the generated forwarder guard)
//! Every failure path writes one `hooks-relay: <class>: <detail>` line to
//! stderr so daemon logs / debug capture can attribute transport failures.

use std::env;
use std::ffi::OsStr;
use std::io::{self, ErrorKind, Read, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{exit, Child, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

/// Matches the python3 transport's CLAUDE_HOOKS_SOCKET_TIMEOUT default (30 s).
const DEFAULT_TIMEOUT_MS: u64 = 30_000;

/// The longest `--timeout-ms` honoured. Twin of `Timeout.RELAY_TIMEOUT_CAP`
/// (seconds), which the daemon's config clamps `transport.timeout_seconds`
/// to. A forwarder deployed before that clamp keeps its old value until it
/// is redeployed, so it is clamped here too (Plan 00466 round 4).
const TIMEOUT_CAP_MS: u64 = 45_000;

/// Response size cap. Twin of the daemon's
/// `constants/protocol.py::SocketLimit.REQUEST_BUFFER_BYTES` (16 MiB): a
/// response larger than the daemon's own request bound is a protocol fault,
/// not data, so refusing it here cannot lose a legitimate verdict.
const RESPONSE_CAP_BYTES: usize = 16 * 1024 * 1024;

/// Pump buffer (DESIGN §3.1 names 64 KiB explicitly).
const PUMP_BUF_BYTES: usize = 64 * 1024;

const EXIT_CONNECT_FAIL: i32 = 10;
const EXIT_TIMEOUT: i32 = 11;
const EXIT_IO: i32 = 12;
const EXIT_USAGE: i32 = 13;

/// Names a failed PreToolUse exchange to the forwarder `judge_via_fallback`
/// runs; `init.sh` reads it at source time. Twin of init.sh's
/// `HOOKS_DAEMON_RELAY_FAILED`.
const RELAY_FAILURE_ENV: &str = "HOOKS_DAEMON_RELAY_FAILED";

/// How long `judge_via_fallback` waits for the forwarder (Plan 00466 N126
/// round 2, F3). Twin of `Timeout.RELAY_HANDOFF_BUDGET`, which caps
/// `transport.timeout_seconds` so this wait plus the relay's own ends before
/// Claude Code cancels the hook -- a cancelled PreToolUse hook lets the call
/// run unjudged.
const HANDOFF_TIMEOUT_MS: u64 = 10_000;

/// How often the hand-off checks whether the forwarder has exited.
const HANDOFF_POLL_MS: u64 = 10;

/// Nesting bound for `JsonParser`: a verdict document is two levels deep.
const JSON_MAX_DEPTH: usize = 32;

/// The launcher spellings `init.sh`'s `_recovery_command` names, in the order
/// `cli.py` resolves "the project's launcher": the daemon clone's first, so a
/// client project's own unrelated `bin/hooks-daemon` is never the one a deny
/// prints while the clone has its launcher (Plan 00466 round 3, m-A).
const RECOVERY_LAUNCHERS: [&str; 2] = [".claude/hooks-daemon/bin/hooks-daemon", "bin/hooks-daemon"];

/// The launcher's place under a daemon root.
const INSTALL_LAUNCHER: &str = "bin/hooks-daemon";

/// The daemon root the generated forwarder bakes in for `restart_command`
/// (Plan 00466 round 4, P3-2). An environment variable rather than a flag,
/// so a forwarder newer than this binary never makes it fail on usage. Kept
/// from every process this one starts.
const DAEMON_ROOT_ENV: &str = "HOOKS_DAEMON_RELAY_DAEMON_ROOT";

struct Args {
    socket_path: String,
    fallback: Option<String>,
    timeout_ms: u64,
    /// Diagnostic mode: report mid-exchange failure classes as distinct exit
    /// codes (11/12) instead of the fail-open `{}` — for test harnesses only.
    no_fallback: bool,
}

/// Failure classes after connect. Which exit code / stderr label each maps to
/// is decided in `mid_exchange_fail` — nothing else may exit mid-exchange.
enum FailClass {
    Timeout,
    Io,
    Oversize,
}

fn usage_fail(detail: &str) -> ! {
    eprintln!("hooks-relay: usage: {detail}");
    eprintln!(
        "usage: hooks-relay <socket-path> [--fallback <script>] \
         [--timeout-ms <n>] [--no-fallback]"
    );
    exit(EXIT_USAGE);
}

fn parse_args() -> Args {
    let mut socket_path: Option<String> = None;
    let mut fallback: Option<String> = None;
    let mut timeout_ms = DEFAULT_TIMEOUT_MS;
    let mut no_fallback = false;

    let mut argv = env::args().skip(1);
    while let Some(arg) = argv.next() {
        match arg.as_str() {
            "--fallback" => match argv.next() {
                Some(path) => fallback = Some(path),
                None => usage_fail("--fallback requires a script path"),
            },
            "--timeout-ms" => match argv.next().map(|v| v.parse::<u64>()) {
                Some(Ok(ms)) if ms > TIMEOUT_CAP_MS => {
                    eprintln!("hooks-relay: --timeout-ms {ms} is over the cap; using {TIMEOUT_CAP_MS}");
                    timeout_ms = TIMEOUT_CAP_MS;
                }
                Some(Ok(ms)) if ms > 0 => timeout_ms = ms,
                _ => usage_fail("--timeout-ms requires a positive integer"),
            },
            "--no-fallback" => no_fallback = true,
            _ if arg.starts_with("--") => usage_fail(&format!("unknown flag {arg}")),
            _ if socket_path.is_none() => socket_path = Some(arg),
            _ => usage_fail("more than one socket path given"),
        }
    }
    if fallback.is_some() && no_fallback {
        usage_fail("--fallback and --no-fallback are contradictory");
    }
    match socket_path {
        Some(socket_path) => Args {
            socket_path,
            fallback,
            timeout_ms,
            no_fallback,
        },
        None => usage_fail("missing socket path"),
    }
}

/// Replace this process with the bash forwarder, stdin/stdout/stderr intact.
/// `--no-relay` tells the forwarder's generated guard not to recurse into the
/// relay again (DESIGN §6.1). Only reachable while stdin is UNREAD.
fn exec_fallback(script: &str) -> ! {
    // exec() only returns on failure — on success this process image is gone.
    let err = Command::new("/bin/bash")
        .arg(script)
        .arg("--no-relay")
        .env_remove(DAEMON_ROOT_ENV)
        .exec();
    eprintln!("hooks-relay: connect: fallback exec of {script} failed: {err}");
    exit(EXIT_CONNECT_FAIL);
}

/// Connect failure: stdin untouched, so the bash rung is a full substitute.
fn connect_fail(args: &Args, detail: &str) -> ! {
    eprintln!("hooks-relay: connect: {detail}");
    match &args.fallback {
        Some(script) => exec_fallback(script),
        None => exit(EXIT_CONNECT_FAIL),
    }
}

/// True when `socket_path` names the PreToolUse per-event socket
/// (`<events-dir>/pre-tool-use.sock` — `forwarder_generator.py`'s
/// `event_file_name` for PreToolUse). Every other event stays on the
/// original fail-open contract: PreToolUse is singled out because it is the
/// one event whose fail-open `{}` gates a real, possibly destructive, tool
/// call rather than merely dropping advisory context.
fn is_pre_tool_use_socket(socket_path: &str) -> bool {
    socket_path.ends_with("pre-tool-use.sock")
}

/// Minimal JSON string escaping for the one dynamic value embedded below —
/// no serde in this file (module constraint), and the detail text is always
/// this process's own `format!` output (a path, an errno message), never
/// attacker-controlled, but escaped anyway rather than assumed safe.
fn json_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

/// A genuine PreToolUse DENY, in the same `hookSpecificOutput` shape
/// `HookResult._format_pre_tool_use_response` emits — never the two-byte
/// `{}` a fail-open would use, which is indistinguishable from a real
/// judged "allow, nothing to add" verdict.
fn deny_pre_tool_use_json(detail: &str, recovery: &str) -> String {
    format!(
        "{{\"hookSpecificOutput\":{{\"hookEventName\":\"PreToolUse\",\
         \"permissionDecision\":\"deny\",\"permissionDecisionReason\":\
         \"BLOCKED [transport-fail-closed]: hooks-relay could not obtain a verdict \
         from the daemon ({}). Denying out of caution -- this does not mean the \
         action itself is unsafe. {}\"}}}}",
        json_escape(detail),
        json_escape(recovery)
    )
}

/// Python's `shlex.quote`, which `init.sh`'s `_recovery_command` uses: a
/// word of only safe characters as it is, anything else single-quoted.
fn shell_quote(word: &str) -> String {
    let safe = |c: char| c.is_ascii_alphanumeric() || "@%+=:,./_-".contains(c);
    if !word.is_empty() && word.chars().all(safe) {
        return word.to_string();
    }
    format!("'{}'", word.replace('\'', "'\"'\"'"))
}

/// `os.path.dirname`: the parent, and the root is its own.
fn dirname(path: &Path) -> &Path {
    path.parent().unwrap_or(path)
}

/// The real path of the longest part of `path` that exists, with the rest
/// appended as written: `init.sh`'s `_resolve`, which `cli_command.py`
/// shares, so all three name the same launcher.
fn resolve(path: &Path) -> PathBuf {
    let mut head = path;
    let mut tail = Vec::new();
    loop {
        if let Ok(real) = head.canonicalize() {
            return tail.iter().rev().fold(real, |acc: PathBuf, name| acc.join(name));
        }
        match (head.parent(), head.file_name()) {
            (Some(parent), Some(name)) => {
                tail.push(name);
                head = parent;
            }
            _ => return path.to_path_buf(),
        }
    }
}

/// The project a launcher at this resolved path manages, by the rule the
/// launcher applies to itself: `init.sh`'s `_project_it_manages`. None when
/// the path is not a `bin/hooks-daemon` at all (Plan 00466 round 5, R4-2).
fn project_it_manages(launcher: &Path) -> Option<PathBuf> {
    let bin_dir = dirname(launcher);
    if launcher.file_name() != Some(OsStr::new("hooks-daemon"))
        || bin_dir.file_name() != Some(OsStr::new("bin"))
    {
        return None;
    }
    let daemon_dir = dirname(bin_dir);
    let parent = dirname(daemon_dir);
    if daemon_dir.file_name() == Some(OsStr::new("hooks-daemon"))
        && parent.file_name() == Some(OsStr::new(".claude"))
    {
        return Some(dirname(parent).to_path_buf());
    }
    Some(daemon_dir.to_path_buf())
}

/// This install's launcher, resolved, or None when it is unknown: the one
/// under `daemon_root` must manage `project`. `init.sh`'s `_installs_launcher`.
fn installs_launcher(project: &Path, daemon_root: &Path) -> Option<PathBuf> {
    if !project.is_absolute() || !daemon_root.is_absolute() {
        return None;
    }
    let launcher = resolve(&daemon_root.join(INSTALL_LAUNCHER));
    (project_it_manages(&launcher) == Some(resolve(project))).then_some(launcher)
}

/// The exempt restart a deny names, as `init.sh`'s `_recovery_command`
/// prints it: this install's launcher by absolute path, so it runs from any
/// directory (Plan 00466 round 2, m1), chosen by the same rule
/// (round 4, P3-2). The project is the one whose `.claude/hooks/` holds the
/// `--fallback` forwarder, and the daemon root is `DAEMON_ROOT_ENV`, or
/// `init.sh`'s default for a forwarder generated without it. With no such
/// forwarder the project-root spelling is all this file can name. None when
/// the install is unknown, which `init.sh` also exempts nothing for.
fn restart_command(args: &Args) -> Option<String> {
    let project = args
        .fallback
        .as_deref()
        .map(Path::new)
        .and_then(Path::parent)
        .filter(|hooks| hooks.file_name() == Some(OsStr::new("hooks")))
        .and_then(Path::parent)
        .filter(|claude| claude.file_name() == Some(OsStr::new(".claude")))
        .and_then(Path::parent);
    let Some(project) = project else {
        return Some(format!("{} restart (from the project root)", RECOVERY_LAUNCHERS[0]));
    };
    let daemon_root = env::var_os(DAEMON_ROOT_ENV)
        .map(PathBuf::from)
        .unwrap_or_else(|| project.join(".claude/hooks-daemon"));
    let launcher = installs_launcher(project, &daemon_root)?;
    let belongs = daemon_root.join(INSTALL_LAUNCHER);
    let mut spellings = RECOVERY_LAUNCHERS.map(|spelling| project.join(spelling)).to_vec();
    spellings.push(belongs.clone());
    let chosen = spellings
        .into_iter()
        .find(|spelling| launcher.is_file() && resolve(spelling) == launcher)
        .unwrap_or(belongs);
    Some(format!("{} restart", shell_quote(chosen.to_str()?)))
}

/// What a relay deny tells the agent to do about it.
fn recovery_advice(args: &Args) -> String {
    match restart_command(args) {
        Some(restart) => format!("If the daemon is wedged, run: {restart}"),
        None => "No daemon command is exempt from this deny: the daemon root this \
                 forwarder names is not a daemon install of its project, so no \
                 launcher is known to recover it. A human must restart the daemon \
                 with the ! prefix, and correct HOOKS_DAEMON_ROOT_DIR."
            .to_string(),
    }
}

/// The fail-open/fail-closed body written on a mid-exchange failure, per
/// `is_pre_tool_use_socket`.
fn fail_body(args: &Args, detail: &str) -> String {
    if is_pre_tool_use_socket(&args.socket_path) {
        deny_pre_tool_use_json(detail, &recovery_advice(args))
    } else {
        "{}".to_string()
    }
}

/// Just enough of a JSON value to judge a hand-off answer's shape (no serde:
/// module constraint). Only strings and objects are ever inspected.
enum Json {
    Scalar,
    Str(String),
    Array,
    Object(Vec<(String, Json)>),
}

/// A strict RFC 8259 parser over the forwarder's answer: one complete value,
/// nothing after it but whitespace, valid UTF-8, no duplicate object keys
/// (which readers resolve differently), bounded nesting. Every method returns
/// `None` on anything else, and the caller then treats the answer as absent.
struct JsonParser<'a> {
    bytes: &'a [u8],
    pos: usize,
    depth: usize,
}

impl JsonParser<'_> {
    fn document(bytes: &[u8]) -> Option<Json> {
        let mut parser = JsonParser {
            bytes,
            pos: 0,
            depth: 0,
        };
        let value = parser.value()?;
        parser.skip_whitespace();
        (parser.pos == bytes.len()).then_some(value)
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn next(&mut self) -> Option<u8> {
        let byte = self.peek()?;
        self.pos += 1;
        Some(byte)
    }

    fn eat(&mut self, byte: u8) -> Option<()> {
        (self.next()? == byte).then_some(())
    }

    fn skip_whitespace(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) {
            self.pos += 1;
        }
    }

    fn value(&mut self) -> Option<Json> {
        self.skip_whitespace();
        match self.peek()? {
            b'{' => self.nested(Self::object),
            b'[' => self.nested(Self::array),
            b'"' => self.string().map(Json::Str),
            b't' => self.literal(b"true"),
            b'f' => self.literal(b"false"),
            b'n' => self.literal(b"null"),
            b'-' | b'0'..=b'9' => self.number(),
            _ => None,
        }
    }

    fn nested(&mut self, parse: fn(&mut Self) -> Option<Json>) -> Option<Json> {
        if self.depth == JSON_MAX_DEPTH {
            return None;
        }
        self.depth += 1;
        let value = parse(self);
        self.depth -= 1;
        value
    }

    fn object(&mut self) -> Option<Json> {
        self.eat(b'{')?;
        let mut members: Vec<(String, Json)> = Vec::new();
        self.skip_whitespace();
        if self.peek()? == b'}' {
            self.pos += 1;
            return Some(Json::Object(members));
        }
        loop {
            self.skip_whitespace();
            let key = self.string()?;
            if members.iter().any(|(seen, _)| *seen == key) {
                return None;
            }
            self.skip_whitespace();
            self.eat(b':')?;
            let value = self.value()?;
            members.push((key, value));
            self.skip_whitespace();
            match self.next()? {
                b',' => {}
                b'}' => return Some(Json::Object(members)),
                _ => return None,
            }
        }
    }

    fn array(&mut self) -> Option<Json> {
        self.eat(b'[')?;
        self.skip_whitespace();
        if self.peek()? == b']' {
            self.pos += 1;
            return Some(Json::Array);
        }
        loop {
            self.value()?;
            self.skip_whitespace();
            match self.next()? {
                b',' => {}
                b']' => return Some(Json::Array),
                _ => return None,
            }
        }
    }

    fn literal(&mut self, word: &[u8]) -> Option<Json> {
        let end = self.pos.checked_add(word.len())?;
        if self.bytes.get(self.pos..end)? != word {
            return None;
        }
        self.pos = end;
        Some(Json::Scalar)
    }

    fn digits(&mut self) -> usize {
        let start = self.pos;
        while matches!(self.peek(), Some(b'0'..=b'9')) {
            self.pos += 1;
        }
        self.pos - start
    }

    fn number(&mut self) -> Option<Json> {
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        match self.peek()? {
            b'0' => self.pos += 1,
            b'1'..=b'9' => {
                self.digits();
            }
            _ => return None,
        }
        if self.peek() == Some(b'.') {
            self.pos += 1;
            if self.digits() == 0 {
                return None;
            }
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            self.pos += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            if self.digits() == 0 {
                return None;
            }
        }
        Some(Json::Scalar)
    }

    fn hex4(&mut self) -> Option<u32> {
        let end = self.pos.checked_add(4)?;
        let hex = self.bytes.get(self.pos..end)?;
        if !hex.iter().all(u8::is_ascii_hexdigit) {
            return None;
        }
        self.pos = end;
        u32::from_str_radix(std::str::from_utf8(hex).ok()?, 16).ok()
    }

    /// A `\u` escape's code point; a surrogate must be a complete pair.
    fn unicode_escape(&mut self) -> Option<char> {
        let first = self.hex4()?;
        let code = match first {
            0xD800..=0xDBFF => {
                self.eat(b'\\')?;
                self.eat(b'u')?;
                let low = self.hex4()?;
                if !(0xDC00..=0xDFFF).contains(&low) {
                    return None;
                }
                0x10000 + ((first - 0xD800) << 10) + (low - 0xDC00)
            }
            0xDC00..=0xDFFF => return None,
            _ => first,
        };
        char::from_u32(code)
    }

    fn string(&mut self) -> Option<String> {
        self.eat(b'"')?;
        let mut out: Vec<u8> = Vec::new();
        loop {
            match self.next()? {
                b'"' => return String::from_utf8(out).ok(),
                b'\\' => {
                    let unescaped = match self.next()? {
                        b'"' => '"',
                        b'\\' => '\\',
                        b'/' => '/',
                        b'b' => '\u{8}',
                        b'f' => '\u{c}',
                        b'n' => '\n',
                        b'r' => '\r',
                        b't' => '\t',
                        b'u' => self.unicode_escape()?,
                        _ => return None,
                    };
                    let mut utf8 = [0u8; 4];
                    out.extend_from_slice(unescaped.encode_utf8(&mut utf8).as_bytes());
                }
                0x00..=0x1F => return None,
                byte => out.push(byte),
            }
        }
    }
}

/// Plan 00466 N126 round 2 (F2): true when `answer` is a verdict the
/// hand-off may deliver. The forwarder, with `RELAY_FAILURE_ENV` set, answers
/// with one of exactly two documents: a PreToolUse deny with its reason, or
/// the recovery carve-out's context-only answer. `{}`, truncated or partial
/// JSON, an allow, an unknown field, or any other shape could only be an
/// allow the relay has not judged, so it is refused and the caller denies.
/// This reads the ANSWER's shape only; the request is still never parsed.
fn is_hand_off_verdict(answer: &[u8]) -> bool {
    let Some(Json::Object(top)) = JsonParser::document(answer) else {
        return false;
    };
    let [(key, Json::Object(output))] = top.as_slice() else {
        return false;
    };
    if key != "hookSpecificOutput" {
        return false;
    }
    const FIELDS: [&str; 4] = [
        "hookEventName",
        "permissionDecision",
        "permissionDecisionReason",
        "additionalContext",
    ];
    let all_known_strings = output
        .iter()
        .all(|(name, value)| FIELDS.contains(&name.as_str()) && matches!(value, Json::Str(_)));
    let field = |name: &str| {
        output.iter().find_map(|(seen, value)| match value {
            Json::Str(text) if seen == name => Some(text.as_str()),
            _ => None,
        })
    };
    if !all_known_strings || field("hookEventName") != Some("PreToolUse") {
        return false;
    }
    match field("permissionDecision") {
        Some(decision) => decision == "deny" && field("permissionDecisionReason").is_some(),
        None => {
            field("permissionDecisionReason").is_none() && field("additionalContext").is_some()
        }
    }
}

/// End the hand-off's forwarder: it is this process's own unreaped child,
/// so its pid cannot have been reused.
fn stop_forwarder(child: &mut Child, script: &str) {
    if let Err(err) = child.kill() {
        eprintln!("hooks-relay: judge: stopping {script} failed: {err}");
    }
}

/// The request bytes read from stdin so far, and whether stdin reached EOF.
/// Kept so a failed PreToolUse exchange can be handed over whole.
struct Request {
    bytes: Vec<u8>,
    complete: bool,
}

/// Plan 00466 N126: hand a failed PreToolUse exchange to the bash forwarder.
///
/// A wedged daemon must not deny its own restart, and whether a call is that
/// restart is a judgement this file must not make: `init.sh` holds the one
/// recovery carve-out, which resolves the launcher the command would run, and
/// a second copy here would drift from it. So the forwarder is run with the
/// whole request replayed on its stdin and `RELAY_FAILURE_ENV` naming the
/// failure; its transport then skips the daemon and denies through that
/// carve-out. Returns only when the hand-off itself failed -- stdin could not
/// be completed, the forwarder could not run, exited non-zero, outlasted
/// `HANDOFF_TIMEOUT_MS`, or answered with anything but a verdict
/// (`is_hand_off_verdict`) -- and the caller then writes its own deny.
fn judge_via_fallback(script: &str, failure: &str, request: &mut Request) {
    if !request.complete {
        if let Err(err) = io::stdin().lock().read_to_end(&mut request.bytes) {
            eprintln!("hooks-relay: judge: stdin read: {err}");
            return;
        }
        request.complete = true;
    }
    let deadline = Instant::now() + Duration::from_millis(HANDOFF_TIMEOUT_MS);
    let spawned = Command::new("/bin/bash")
        .arg(script)
        .arg("--no-relay")
        .env(RELAY_FAILURE_ENV, failure)
        .env_remove(DAEMON_ROOT_ENV)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn();
    let mut child = match spawned {
        Ok(child) => child,
        Err(err) => {
            eprintln!("hooks-relay: judge: running {script} failed: {err}");
            return;
        }
    };
    let (Some(mut child_stdin), Some(mut child_stdout)) = (child.stdin.take(), child.stdout.take())
    else {
        eprintln!("hooks-relay: judge: {script} has no stdin or stdout pipe");
        stop_forwarder(&mut child, script);
        return;
    };
    // The request is written, and the answer read, on threads of their own:
    // the forwarder may answer before it has read everything, and every wait
    // below must be bounded by the deadline. A thread still blocked when the
    // deadline passes is abandoned; this process exits right afterwards.
    let payload = std::mem::take(&mut request.bytes);
    let (written_tx, written_rx) = mpsc::channel();
    thread::spawn(move || {
        // A send error means the hand-off already gave up on this write.
        if written_tx.send(child_stdin.write_all(&payload)).is_err() {
            // Intentionally empty: see comment above.
        }
    });
    let (answer_tx, answer_rx) = mpsc::channel();
    thread::spawn(move || {
        let mut answer = Vec::new();
        let read = child_stdout.read_to_end(&mut answer).map(|_| answer);
        // A send error means the hand-off already gave up on this answer.
        if answer_tx.send(read).is_err() {
            // Intentionally empty: see comment above.
        }
    });
    let answer = match answer_rx.recv_timeout(remaining(deadline).unwrap_or_default()) {
        Ok(Ok(answer)) => answer,
        Ok(Err(err)) => {
            eprintln!("hooks-relay: judge: reading the answer from {script} failed: {err}");
            stop_forwarder(&mut child, script);
            return;
        }
        Err(_) => {
            eprintln!("hooks-relay: judge: {script} gave no answer within {HANDOFF_TIMEOUT_MS} ms");
            stop_forwarder(&mut child, script);
            return;
        }
    };
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if remaining(deadline).is_some() => {
                thread::sleep(Duration::from_millis(HANDOFF_POLL_MS));
            }
            Ok(None) => {
                eprintln!("hooks-relay: judge: {script} did not exit within {HANDOFF_TIMEOUT_MS} ms");
                stop_forwarder(&mut child, script);
                return;
            }
            Err(err) => {
                eprintln!("hooks-relay: judge: waiting on {script} failed: {err}");
                stop_forwarder(&mut child, script);
                return;
            }
        }
    };
    match written_rx.recv_timeout(remaining(deadline).unwrap_or_default()) {
        Ok(Ok(())) => {}
        Ok(Err(err)) => {
            eprintln!("hooks-relay: judge: replaying the request to {script} failed: {err}");
            return;
        }
        Err(_) => {
            eprintln!("hooks-relay: judge: the request was not replayed to {script} in time");
            return;
        }
    }
    if !status.success() || !is_hand_off_verdict(&answer) {
        eprintln!(
            "hooks-relay: judge: {script} gave no verdict ({status}, {} bytes)",
            answer.len()
        );
        return;
    }
    let mut stdout = io::stdout();
    if let Err(err) = stdout.write_all(&answer).and_then(|()| stdout.flush()) {
        eprintln!("hooks-relay: judge: stdout write failed: {err}");
    }
    exit(0);
}

/// Mid-exchange failure: stdin (partially) consumed, so exec'ing the fallback
/// in place would replay a truncated payload — forbidden. Fails OPEN (`{}`)
/// for every event except PreToolUse. A PreToolUse failure is first handed,
/// with the whole request, to `judge_via_fallback` when a `--fallback` is
/// given; if that cannot answer, or there is no fallback, it fails CLOSED (a
/// genuine deny) — see `fail_body`. Either way stdout carries valid JSON and
/// exit is 0, so Claude Code always receives something it can parse.
/// Diagnostic invocations (`--no-fallback`) get the distinct class exit code
/// instead.
fn mid_exchange_fail(args: &Args, class: FailClass, detail: &str, request: &mut Request) -> ! {
    let (label, code) = match class {
        FailClass::Timeout => ("timeout", EXIT_TIMEOUT),
        FailClass::Io => ("io", EXIT_IO),
        FailClass::Oversize => ("oversize", EXIT_IO),
    };
    eprintln!("hooks-relay: {label}: {detail}");
    if args.no_fallback {
        exit(code);
    }
    if is_pre_tool_use_socket(&args.socket_path) {
        if let Some(script) = &args.fallback {
            judge_via_fallback(script, &format!("{label}: {detail}"), request);
        }
    }
    let mut stdout = io::stdout();
    let body = fail_body(args, detail);
    // If even stdout is broken there is no channel left to fail open (or
    // closed) on; the stderr line above is the only trace either way.
    if let Err(err) = stdout.write_all(body.as_bytes()).and_then(|()| stdout.flush()) {
        eprintln!("hooks-relay: io: fail-open write to stdout failed: {err}");
    }
    exit(0);
}

/// Time left before `deadline`, or None once it has passed. The one timeout
/// budget spans the WHOLE exchange (connect + send + receive), per DESIGN
/// §3.1 — each socket operation is armed with only the remainder.
fn remaining(deadline: Instant) -> Option<Duration> {
    let now = Instant::now();
    if now >= deadline {
        None
    } else {
        Some(deadline - now)
    }
}

/// `UnixStream::connect` has no timeout variant in std, and a full daemon
/// backlog would block it indefinitely. Run it on a helper thread and wait at
/// most the remaining budget. On timeout the helper thread is abandoned —
/// safe, because both exits from `connect_fail` (exec / process exit) destroy
/// the whole process image, helper thread included.
fn connect_with_deadline(args: &Args, deadline: Instant) -> UnixStream {
    let Some(budget) = remaining(deadline) else {
        connect_fail(args, "budget exhausted before connect");
    };
    let (tx, rx) = mpsc::channel();
    let path = args.socket_path.clone();
    thread::spawn(move || {
        // A send error just means the main thread already gave up and is
        // exec'ing the fallback; there is no one left to report to.
        if tx.send(UnixStream::connect(&path)).is_err() {
            // Intentionally empty: see comment above.
        }
    });
    match rx.recv_timeout(budget) {
        Ok(Ok(stream)) => stream,
        Ok(Err(err)) => connect_fail(args, &format!("{}: {err}", args.socket_path)),
        Err(_) => connect_fail(args, &format!("{}: connect timed out", args.socket_path)),
    }
}

/// Arm the socket's read or write timeout with the remaining overall budget.
/// A zero/negative remainder is itself a timeout (std rejects Some(0) too).
fn arm_timeout(
    args: &Args,
    stream: &UnixStream,
    deadline: Instant,
    for_read: bool,
    request: &mut Request,
) {
    let Some(left) = remaining(deadline) else {
        mid_exchange_fail(args, FailClass::Timeout, "overall budget exhausted", request);
    };
    let armed = if for_read {
        stream.set_read_timeout(Some(left))
    } else {
        stream.set_write_timeout(Some(left))
    };
    if let Err(err) = armed {
        mid_exchange_fail(
            args,
            FailClass::Io,
            &format!("arming socket timeout: {err}"),
            request,
        );
    }
}

/// An expired SO_RCVTIMEO/SO_SNDTIMEO surfaces as WouldBlock (EAGAIN) or
/// TimedOut depending on platform; both mean "budget spent", not "broken".
fn classify(err: &io::Error) -> FailClass {
    match err.kind() {
        ErrorKind::WouldBlock | ErrorKind::TimedOut => FailClass::Timeout,
        _ => FailClass::Io,
    }
}

/// The error as a deny reason should name it. An expired socket timeout is
/// EAGAIN on Linux, which `io::Error` prints as "Resource temporarily
/// unavailable (os error 11)" -- true of the errno, silent about the cause.
fn describe(err: &io::Error) -> String {
    match classify(err) {
        FailClass::Timeout => "timed out".to_string(),
        FailClass::Io | FailClass::Oversize => err.to_string(),
    }
}

fn main() {
    let args = parse_args();
    let deadline = Instant::now() + Duration::from_millis(args.timeout_ms);

    // 1. Connect BEFORE reading any stdin — the only state in which the bash
    //    forwarder can still take over wholesale (see module docs).
    let mut stream = connect_with_deadline(&args, deadline);

    // 2. Pump stdin → socket. Local stdin reads are not against the socket
    //    budget (the pipe is already written by Claude Code); socket writes
    //    are re-armed with the shrinking remainder before every chunk.
    //    Every byte is also kept in `request` (see `judge_via_fallback`).
    //    stdin is read through the unlocked handle, one lock per call, so
    //    that hand-off can read the rest of it without deadlocking.
    let mut buf = vec![0u8; PUMP_BUF_BYTES];
    let mut request = Request {
        bytes: Vec::new(),
        complete: false,
    };
    let mut stdin = io::stdin();
    loop {
        let n = match stdin.read(&mut buf) {
            Ok(n) => n,
            Err(err) => mid_exchange_fail(
                &args,
                FailClass::Io,
                &format!("stdin read: {err}"),
                &mut request,
            ),
        };
        if n == 0 {
            request.complete = true;
            break; // stdin EOF: full request payload sent
        }
        request.bytes.extend_from_slice(&buf[..n]);
        arm_timeout(&args, &stream, deadline, false, &mut request);
        if let Err(err) = stream.write_all(&buf[..n]) {
            mid_exchange_fail(
                &args,
                classify(&err),
                &format!("socket write: {}", describe(&err)),
                &mut request,
            );
        }
    }

    // Half-close the write side: EOF is the request framing (DESIGN §2).
    if let Err(err) = stream.shutdown(Shutdown::Write) {
        mid_exchange_fail(
            &args,
            FailClass::Io,
            &format!("socket half-close: {err}"),
            &mut request,
        );
    }

    // 3. Read the response to EOF — BUFFERED, not streamed to stdout. If any
    //    read fails partway we must still be able to emit the fail-open `{}`
    //    as the ONLY bytes on stdout; bytes already streamed would corrupt it.
    let mut response: Vec<u8> = Vec::new();
    loop {
        arm_timeout(&args, &stream, deadline, true, &mut request);
        let n = match stream.read(&mut buf) {
            Ok(n) => n,
            Err(err) => mid_exchange_fail(
                &args,
                classify(&err),
                &format!("socket read: {}", describe(&err)),
                &mut request,
            ),
        };
        if n == 0 {
            break; // daemon closed: response complete
        }
        if response.len() + n > RESPONSE_CAP_BYTES {
            mid_exchange_fail(
                &args,
                FailClass::Oversize,
                &format!("response exceeds {RESPONSE_CAP_BYTES} bytes"),
                &mut request,
            );
        }
        response.extend_from_slice(&buf[..n]);
    }

    // 4. Deliver the verdict bytes. An EMPTY response is a transport fault,
    //    not a real judged verdict -- neither of PreToolUse's two legitimate
    //    response shapes is zero bytes (the python transport's own
    //    `_pretooluse_response_looks_valid`), so on the PreToolUse socket
    //    this is treated exactly like any other mid-exchange failure rather
    //    than delivered untouched.
    if response.is_empty() && is_pre_tool_use_socket(&args.socket_path) {
        mid_exchange_fail(
            &args,
            FailClass::Io,
            "daemon closed the connection with an empty response",
            &mut request,
        );
    }
    let mut stdout = io::stdout();
    if let Err(err) = stdout.write_all(&response).and_then(|()| stdout.flush()) {
        // Nothing more can be delivered: stdout itself is broken.
        eprintln!("hooks-relay: io: stdout write: {err}");
        exit(if args.no_fallback { EXIT_IO } else { 0 });
    }
    exit(0);
}
