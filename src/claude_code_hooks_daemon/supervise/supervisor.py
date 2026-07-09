"""Transparent PTY supervisor (v0).

Spawns a child process on a pseudo-terminal and faithfully forwards
stdin/stdout and window-resize events, so an interactive TUI (e.g. `claude`)
behaves identically to running it directly. Input bytes are observed and
counted, but v0 performs NO keystroke injection -- it is a pure, transparent
passthrough. Injection and the decision state machine are out of scope for
v0 (see v1).

Standalone by design: stdlib only (`os`/`pty`/`select`/`termios`/`signal`/
`fcntl`/`struct`/`tty`). No daemon runtime/server imports.
"""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import tty
from dataclasses import dataclass
from typing import TYPE_CHECKING

from claude_code_hooks_daemon.supervise.decision_log import DecisionLog

if TYPE_CHECKING:
    from types import FrameType

_READ_CHUNK_SIZE = 4096
_FALLBACK_WINSIZE = struct.pack("HHHH", 24, 80, 0, 0)


@dataclass
class InputActivity:
    """Tracks observed stdin activity forwarded to the supervised child."""

    bytes_seen: int = 0
    last_input_monotonic: float | None = None

    def record(self, data: bytes) -> None:
        """Record a chunk of stdin data that was forwarded to the child."""
        self.bytes_seen += len(data)
        self.last_input_monotonic = os.times().elapsed


def _get_winsize(stdin_fd: int) -> bytes:
    """Read the controlling terminal's window size, falling back if unavailable."""
    try:
        return fcntl.ioctl(stdin_fd, termios.TIOCGWINSZ, b"\x00" * 8)
    except OSError:
        return _FALLBACK_WINSIZE


def _set_winsize(master_fd: int, stdin_fd: int) -> None:
    """Copy the controlling terminal's window size onto the pty master fd."""
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, _get_winsize(stdin_fd))


def _exit_code_from_status(status: int) -> int:
    """Translate a `waitpid` status into a shell-style exit code."""
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 1


def supervise(
    argv: list[str],
    *,
    dry_run: bool = True,
    log: DecisionLog | None = None,
    activity: InputActivity | None = None,
    stdin_fd: int | None = None,
) -> int:
    """Run `argv` under a PTY, transparently forwarding I/O.

    Args:
        argv: The child command and its arguments (argv[0] is the executable).
        dry_run: v0 is always transparent; this only controls what is logged.
            Injection does not exist yet in v0, so this has no behavioural
            effect on the child beyond the logged summary.
        log: Optional decision log to record a one-line summary to on exit.
        activity: Optional `InputActivity` to record stdin byte counts into.
            A fresh one is created internally if not supplied.
        stdin_fd: File descriptor to read supervisor input from. Defaults to
            `sys.stdin.fileno()`. Overridable so callers (and tests) can pass
            a real fd directly, bypassing wrappers that don't expose one.

    Returns:
        The child's exit code (or 128+signal if it died from a signal).

    Raises:
        ValueError: If `argv` is empty.
    """
    if not argv:
        raise ValueError("supervise() requires a non-empty argv")

    activity = activity if activity is not None else InputActivity()
    stdin_fd = stdin_fd if stdin_fd is not None else sys.stdin.fileno()

    pid, master_fd = pty.fork()
    if pid == 0:  # pragma: no cover - runs in the forked child process
        # SECURITY: no shell involved -- argv is passed directly to execvp as
        # a list (never a shell string), so there is no command-injection
        # surface here. This IS the supervisor's job: exec the wrapped
        # process (e.g. `claude`) on the child side of the PTY.
        os.execvp(argv[0], argv)  # nosec B606
        os._exit(127)  # unreachable on success

    _set_winsize(master_fd, stdin_fd)

    old_termios: list[int | list[bytes | int]] | None = None
    stdin_is_tty = os.isatty(stdin_fd)
    if stdin_is_tty:
        old_termios = termios.tcgetattr(stdin_fd)
        tty.setraw(stdin_fd)

    def _on_winch(_signum: int, _frame: FrameType | None) -> None:
        _set_winsize(master_fd, stdin_fd)

    previous_handler = signal.signal(signal.SIGWINCH, _on_winch)

    try:
        _forward_io(stdin_fd, master_fd, activity)
    finally:
        signal.signal(signal.SIGWINCH, previous_handler)
        if old_termios is not None:
            termios.tcsetattr(stdin_fd, termios.TCSAFLUSH, old_termios)

    _pid, status = os.waitpid(pid, 0)
    exit_code = _exit_code_from_status(status)

    if log is not None:
        mode = "dry-run" if dry_run else "armed (no-op in v0)"
        log.write(
            f"supervisor active ({mode}); transparent passthrough; "
            f"{activity.bytes_seen} input bytes observed"
        )

    return exit_code


def _forward_io(stdin_fd: int, master_fd: int, activity: InputActivity) -> None:
    """Select loop: forward stdin -> master, and master -> stdout."""
    while True:
        try:
            readable, _, _ = select.select([stdin_fd, master_fd], [], [])
        except OSError as exc:
            if exc.errno == errno.EINTR:
                continue
            raise

        if stdin_fd in readable:
            data = os.read(stdin_fd, _READ_CHUNK_SIZE)
            if data:
                activity.record(data)
                os.write(master_fd, data)

        if master_fd in readable:
            try:
                output = os.read(master_fd, _READ_CHUNK_SIZE)
            except OSError:
                output = b""
            if not output:
                return
            os.write(sys.stdout.fileno(), output)
