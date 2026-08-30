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
//! - **No policy.** The relay never parses JSON, never reads config, never
//!   starts the daemon, never retries, never writes files, and contains no
//!   hook event names. The event is encoded in WHICH socket path argv names;
//!   every allow/deny decision stays in the Python daemon.
//! - **Connect FIRST, before touching stdin.** While stdin is unread, the
//!   bash forwarder can still be exec'd as a complete substitute; the moment
//!   one stdin byte is consumed that door closes, and every later failure
//!   must fail OPEN (`{}` on stdout, exit 0) because Claude Code must always
//!   receive valid JSON — mirroring the bash rung's `emit_hook_error`
//!   contract. `{}` carries no policy: it is "no opinion", the same thing a
//!   passthrough hook emits today.
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
//!   0  — response delivered, or a mid-exchange failure emitted fail-open `{}`
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
use std::process::{exit, Command};
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

/// Mid-exchange failure: stdin (partially) consumed, so exec'ing the fallback
/// would replay a truncated payload — forbidden. Fail OPEN instead: `{}` on
/// stdout, exit 0, so Claude Code always receives valid JSON. Diagnostic
/// invocations (`--no-fallback`) get the distinct class exit code instead.
fn mid_exchange_fail(args: &Args, class: FailClass, detail: &str) -> ! {
    let (label, code) = match class {
        FailClass::Timeout => ("timeout", EXIT_TIMEOUT),
        FailClass::Io => ("io", EXIT_IO),
        FailClass::Oversize => ("oversize", EXIT_IO),
    };
    eprintln!("hooks-relay: {label}: {detail}");
    if args.no_fallback {
        exit(code);
    }
    let mut stdout = io::stdout();
    // If even stdout is broken there is no channel left to fail open on;
    // the stderr line above is the only trace either way.
    if let Err(err) = stdout.write_all(b"{}").and_then(|()| stdout.flush()) {
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
fn arm_timeout(args: &Args, stream: &UnixStream, deadline: Instant, for_read: bool) {
    let Some(left) = remaining(deadline) else {
        mid_exchange_fail(args, FailClass::Timeout, "overall budget exhausted");
    };
    let armed = if for_read {
        stream.set_read_timeout(Some(left))
    } else {
        stream.set_write_timeout(Some(left))
    };
    if let Err(err) = armed {
        mid_exchange_fail(args, FailClass::Io, &format!("arming socket timeout: {err}"));
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

fn main() {
    let args = parse_args();
    let deadline = Instant::now() + Duration::from_millis(args.timeout_ms);

    // 1. Connect BEFORE reading any stdin — the only state in which the bash
    //    forwarder can still take over wholesale (see module docs).
    let mut stream = connect_with_deadline(&args, deadline);

    // 2. Pump stdin → socket. Local stdin reads are not against the socket
    //    budget (the pipe is already written by Claude Code); socket writes
    //    are re-armed with the shrinking remainder before every chunk.
    let mut buf = vec![0u8; PUMP_BUF_BYTES];
    let mut stdin = io::stdin().lock();
    loop {
        let n = match stdin.read(&mut buf) {
            Ok(n) => n,
            Err(err) => mid_exchange_fail(&args, FailClass::Io, &format!("stdin read: {err}")),
        };
        if n == 0 {
            break; // stdin EOF: full request payload sent
        }
        arm_timeout(&args, &stream, deadline, false);
        if let Err(err) = stream.write_all(&buf[..n]) {
            mid_exchange_fail(&args, classify(&err), &format!("socket write: {err}"));
        }
    }

    // Half-close the write side: EOF is the request framing (DESIGN §2).
    if let Err(err) = stream.shutdown(Shutdown::Write) {
        mid_exchange_fail(&args, FailClass::Io, &format!("socket half-close: {err}"));
    }

    // 3. Read the response to EOF — BUFFERED, not streamed to stdout. If any
    //    read fails partway we must still be able to emit the fail-open `{}`
    //    as the ONLY bytes on stdout; bytes already streamed would corrupt it.
    let mut response: Vec<u8> = Vec::new();
    loop {
        arm_timeout(&args, &stream, deadline, true);
        let n = match stream.read(&mut buf) {
            Ok(n) => n,
            Err(err) => mid_exchange_fail(&args, classify(&err), &format!("socket read: {err}")),
        };
        if n == 0 {
            break; // daemon closed: response complete
        }
        if response.len() + n > RESPONSE_CAP_BYTES {
            mid_exchange_fail(
                &args,
                FailClass::Oversize,
                &format!("response exceeds {RESPONSE_CAP_BYTES} bytes"),
            );
        }
        response.extend_from_slice(&buf[..n]);
    }

    // 4. Deliver the verdict bytes untouched.
    let mut stdout = io::stdout();
    if let Err(err) = stdout.write_all(&response).and_then(|()| stdout.flush()) {
        mid_exchange_fail(&args, FailClass::Io, &format!("stdout write: {err}"));
    }
    exit(0);
}
