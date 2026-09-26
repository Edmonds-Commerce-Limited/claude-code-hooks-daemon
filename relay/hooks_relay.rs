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
use std::io::{self, ErrorKind, Read, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::os::unix::process::CommandExt;
use std::process::{exit, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

/// Matches the python3 transport's CLAUDE_HOOKS_SOCKET_TIMEOUT default (30 s).
const DEFAULT_TIMEOUT_MS: u64 = 30_000;

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
    let err = Command::new("/bin/bash").arg(script).arg("--no-relay").exec();
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
fn deny_pre_tool_use_json(detail: &str) -> String {
    format!(
        "{{\"hookSpecificOutput\":{{\"hookEventName\":\"PreToolUse\",\
         \"permissionDecision\":\"deny\",\"permissionDecisionReason\":\
         \"BLOCKED [transport-fail-closed]: hooks-relay could not obtain a verdict \
         from the daemon ({}). Denying out of caution -- this does not mean the \
         action itself is unsafe. If the daemon is wedged, run: bin/hooks-daemon restart\"}}}}",
        json_escape(detail)
    )
}

/// The fail-open/fail-closed body written on a mid-exchange failure, per
/// `is_pre_tool_use_socket`.
fn fail_body(args: &Args, detail: &str) -> String {
    if is_pre_tool_use_socket(&args.socket_path) {
        deny_pre_tool_use_json(detail)
    } else {
        "{}".to_string()
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
/// be completed, the forwarder could not run, exited non-zero or wrote
/// nothing -- and the caller then writes its own deny.
fn judge_via_fallback(script: &str, failure: &str, request: &mut Request) {
    if !request.complete {
        if let Err(err) = io::stdin().lock().read_to_end(&mut request.bytes) {
            eprintln!("hooks-relay: judge: stdin read: {err}");
            return;
        }
        request.complete = true;
    }
    let spawned = Command::new("/bin/bash")
        .arg(script)
        .arg("--no-relay")
        .env(RELAY_FAILURE_ENV, failure)
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
    let Some(mut child_stdin) = child.stdin.take() else {
        eprintln!("hooks-relay: judge: {script} has no stdin pipe");
        return;
    };
    let payload = std::mem::take(&mut request.bytes);
    // Written on its own thread: the forwarder may answer before it has read
    // everything, and a pipe that fills would otherwise deadlock the wait.
    let writer = thread::spawn(move || child_stdin.write_all(&payload));
    let output = child.wait_with_output();
    match writer.join() {
        Ok(Ok(())) => {}
        Ok(Err(err)) => {
            eprintln!("hooks-relay: judge: replaying the request to {script} failed: {err}");
            return;
        }
        Err(_) => {
            eprintln!("hooks-relay: judge: the request writer thread panicked");
            return;
        }
    }
    let output = match output {
        Ok(output) => output,
        Err(err) => {
            eprintln!("hooks-relay: judge: waiting on {script} failed: {err}");
            return;
        }
    };
    if !output.status.success() || output.stdout.is_empty() {
        eprintln!(
            "hooks-relay: judge: {script} gave no answer ({}, {} bytes)",
            output.status,
            output.stdout.len()
        );
        return;
    }
    let mut stdout = io::stdout();
    if let Err(err) = stdout.write_all(&output.stdout).and_then(|()| stdout.flush()) {
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
