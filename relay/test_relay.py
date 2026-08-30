#!/usr/bin/env python3
"""Test harness for the hooks-relay binary (Plan 00290, Task 3.2).

Runs the built relay binary against a stub Unix-socket server that speaks the
per-event EOF framing from DESIGN-socket-relay.md section 2: the client streams
the payload and half-closes; the server reads to EOF, writes a response, and
closes. No daemon is involved — full end-to-end acceptance against the real
daemon is Phase 6.

Usage:
    python3 relay/test_relay.py [path-to-relay-binary]

The binary defaults to the build script's output location
(untracked/relay-build/hooks-relay-x86_64-unknown-linux-musl).
Exit code 0 iff every test passes.
"""

from __future__ import annotations

import hashlib
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BINARY = REPO_ROOT / "untracked" / "relay-build" / "hooks-relay-x86_64-unknown-linux-musl"

# Mirrors the relay's diagnostic exit codes (DESIGN-socket-relay.md section 3.1).
EXIT_CONNECT_FAIL = 10
EXIT_TIMEOUT = 11
EXIT_IO = 12

RESPONSE_CAP_BYTES = 16 * 1024 * 1024  # SocketLimit.REQUEST_BUFFER_BYTES twin


class StubServer:
    """One-shot Unix-socket server implementing the EOF framing.

    mode:
      "echo"    — read request to EOF, send `response`, close.
      "silent"  — read request to EOF, then hold the connection open without
                  responding (forces the relay's read timeout).
      "abort"   — accept and close immediately (mid-exchange disconnect).
    """

    def __init__(self, sock_path: str, mode: str, response: bytes = b"") -> None:
        self.sock_path = sock_path
        self.mode = mode
        self.response = response
        self.received: bytes = b""
        self.error: BaseException | None = None
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(sock_path)
        self._listener.listen(1)
        self._listener.settimeout(30.0)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self._listener.accept()
            with conn:
                if self.mode == "abort":
                    return  # close without reading: relay sees EPIPE/ECONNRESET
                conn.settimeout(30.0)
                chunks: list[bytes] = []
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                self.received = b"".join(chunks)
                if self.mode == "silent":
                    # Hold the socket open past any sane test timeout; the
                    # relay must give up on its own, not on our close.
                    time.sleep(20.0)
                    return
                conn.sendall(self.response)
        except BaseException as exc:  # surfaced via self.error in join()
            self.error = exc
        finally:
            self._listener.close()

    def join(self) -> None:
        self._thread.join(timeout=30.0)
        if self._thread.is_alive() and self.mode != "silent":
            raise AssertionError(f"stub server thread hung (mode={self.mode})")
        if self.error is not None and self.mode != "silent":
            raise AssertionError(f"stub server error: {self.error!r}")


def run_relay(
    binary: str, argv: list[str], payload: bytes, timeout: float = 25.0
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [binary, *argv], input=payload, capture_output=True, timeout=timeout, check=False
    )


def make_fallback_script(tmp: str) -> tuple[str, str, str]:
    """Write a stand-in bash forwarder that records its argv and stdin."""
    stdin_file = str(Path(tmp) / "fallback-stdin.bin")
    args_file = str(Path(tmp) / "fallback-args.txt")
    script = str(Path(tmp) / "fake-forwarder.sh")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(
            "#!/bin/bash\n"
            f"printf '%s' \"$*\" > {args_file}\n"
            f"cat > {stdin_file}\n"
            'printf \'{"via":"fallback"}\'\n'
        )
    Path(script).chmod(stat.S_IRWXU)
    return script, stdin_file, args_file


# ---------------------------------------------------------------- test cases


def test_happy_path_roundtrip(binary: str, tmp: str) -> None:
    sock = str(Path(tmp) / "pre-tool-use.sock")
    payload = b'{"tool_name":"Bash","tool_input":{"command":"true"}}'
    response = b'{"decision":"allow","reason":"stub"}'
    server = StubServer(sock, "echo", response)
    proc = run_relay(binary, [sock], payload)
    server.join()
    assert proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr!r}"
    assert proc.stdout == response, f"stdout={proc.stdout!r}"
    assert server.received == payload, f"server got {server.received!r}"


def test_daemon_absent_exec_fallback(binary: str, tmp: str) -> None:
    sock = str(Path(tmp) / "no-daemon.sock")  # never created
    payload = b'{"hook_event_name":"PreToolUse"}'
    script, stdin_file, args_file = make_fallback_script(tmp)
    proc = run_relay(binary, [sock, "--fallback", script], payload)
    assert proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr!r}"
    assert proc.stdout == b'{"via":"fallback"}', f"stdout={proc.stdout!r}"
    with open(stdin_file, "rb") as fh:
        assert fh.read() == payload, "fallback did not receive stdin intact"
    with open(args_file, encoding="utf-8") as fh:
        assert "--no-relay" in fh.read(), "fallback not invoked with --no-relay"


def test_connect_fail_diagnostic_exit(binary: str, tmp: str) -> None:
    sock = str(Path(tmp) / "no-daemon-diag.sock")
    proc = run_relay(binary, [sock], b"{}")
    assert proc.returncode == EXIT_CONNECT_FAIL, f"exit={proc.returncode}"
    assert proc.stdout == b"", f"stdout={proc.stdout!r}"
    assert b"hooks-relay: connect:" in proc.stderr, f"stderr={proc.stderr!r}"


def test_timeout_fail_open(binary: str, tmp: str) -> None:
    sock = str(Path(tmp) / "silent.sock")
    StubServer(sock, "silent")
    start = time.monotonic()
    proc = run_relay(binary, [sock, "--timeout-ms", "500"], b'{"k":1}')
    elapsed = time.monotonic() - start
    assert proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr!r}"
    assert proc.stdout == b"{}", f"stdout={proc.stdout!r}"
    assert elapsed < 5.0, f"timeout took {elapsed:.1f}s for a 500ms budget"
    assert b"hooks-relay: timeout:" in proc.stderr, f"stderr={proc.stderr!r}"


def test_timeout_diagnostic_exit(binary: str, tmp: str) -> None:
    sock = str(Path(tmp) / "silent-diag.sock")
    StubServer(sock, "silent")
    proc = run_relay(binary, [sock, "--timeout-ms", "500", "--no-fallback"], b'{"k":1}')
    assert proc.returncode == EXIT_TIMEOUT, f"exit={proc.returncode}"
    assert proc.stdout == b"", f"stdout={proc.stdout!r}"


def test_mid_exchange_disconnect_fail_open(binary: str, tmp: str) -> None:
    sock = str(Path(tmp) / "abort.sock")
    server = StubServer(sock, "abort")
    # 4 MiB payload: far beyond socket buffers, so the relay is still writing
    # when the server side is already closed and hits EPIPE/ECONNRESET.
    payload = b"x" * (4 * 1024 * 1024)
    proc = run_relay(binary, [sock], payload)
    server.join()
    assert proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr!r}"
    assert proc.stdout == b"{}", f"stdout={proc.stdout!r}"


def test_mid_exchange_disconnect_diagnostic_exit(binary: str, tmp: str) -> None:
    sock = str(Path(tmp) / "abort-diag.sock")
    server = StubServer(sock, "abort")
    payload = b"x" * (4 * 1024 * 1024)
    proc = run_relay(binary, [sock, "--no-fallback"], payload)
    server.join()
    assert proc.returncode == EXIT_IO, f"exit={proc.returncode} stderr={proc.stderr!r}"
    assert proc.stdout == b"", f"stdout={proc.stdout!r}"


def test_large_payload_roundtrip(binary: str, tmp: str) -> None:
    sock = str(Path(tmp) / "large.sock")
    payload = os.urandom(2 * 1024 * 1024)  # 2 MiB, larger than the 64 KiB pump
    response = os.urandom(2 * 1024 * 1024)  # large response direction too
    server = StubServer(sock, "echo", response)
    proc = run_relay(binary, [sock], payload)
    server.join()
    assert proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr!r}"
    assert hashlib.sha256(proc.stdout).digest() == hashlib.sha256(response).digest()
    assert hashlib.sha256(server.received).digest() == hashlib.sha256(payload).digest()


def test_oversized_response_diagnostic_exit(binary: str, tmp: str) -> None:
    sock = str(Path(tmp) / "oversize.sock")
    response = b"y" * (RESPONSE_CAP_BYTES + 1)
    server = StubServer(sock, "echo", response)
    proc = run_relay(binary, [sock, "--no-fallback"], b"{}")
    server.join()
    assert proc.returncode == EXIT_IO, f"exit={proc.returncode} stderr={proc.stderr!r}"
    assert proc.stdout == b"", f"stdout={proc.stdout!r}"
    assert b"oversize" in proc.stderr, f"stderr={proc.stderr!r}"


TESTS: list[Callable[[str, str], None]] = [
    test_happy_path_roundtrip,
    test_daemon_absent_exec_fallback,
    test_connect_fail_diagnostic_exit,
    test_timeout_fail_open,
    test_timeout_diagnostic_exit,
    test_mid_exchange_disconnect_fail_open,
    test_mid_exchange_disconnect_diagnostic_exit,
    test_large_payload_roundtrip,
    test_oversized_response_diagnostic_exit,
]


def main() -> int:
    binary = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_BINARY)
    if not os.access(binary, os.X_OK):
        print(f"relay binary not found/executable: {binary}", file=sys.stderr)
        print("build it first: bash relay/build.sh", file=sys.stderr)
        return 2
    failures = 0
    for test in TESTS:
        # Fresh short tmpdir per test keeps unix socket paths under the
        # AF_UNIX 108-byte path limit and isolates leftover sockets.
        with tempfile.TemporaryDirectory(prefix="relay-t-") as tmp:
            try:
                test(binary, tmp)
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {test.__name__}: {exc}")
            except Exception as exc:  # counted and reported, never hidden
                failures += 1
                print(f"ERROR {test.__name__}: {exc!r}")
            else:
                print(f"PASS {test.__name__}")
    print(f"{len(TESTS) - failures}/{len(TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
