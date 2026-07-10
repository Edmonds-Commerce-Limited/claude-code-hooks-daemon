#!/usr/bin/env python3
"""claude-supervise: a standalone, stdlib-only PTY supervisor for wrapping `claude`.

This file is intentionally standalone: it imports nothing from
`claude_code_hooks_daemon` (no pydantic, no daemon venv). It runs under the
container's system `python3` so that upgrading (or breaking) the hooks-daemon
venv can never take down every `ccy` launch.

v0 is a transparent, dry-run PTY passthrough: it spawns the wrapped process on
a pseudo-terminal, forwards stdin/stdout/window-resize faithfully, and
observes input activity -- but performs NO keystroke injection. Injection and
the state machine that decides when to inject are out of scope for v0 (v1).

Usage:
    claude-supervise.py [--dry-run | --arm] [--log PATH] -- <child argv...>
"""

from __future__ import annotations

import argparse
import enum
import errno
import fcntl
import json
import os
import pty
import select
import signal
import struct
import sys
import termios
import tty
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import FrameType

_READ_CHUNK_SIZE = 4096
_FALLBACK_WINSIZE = struct.pack("HHHH", 24, 80, 0, 0)
_LOG_SUBDIRECTORY = "supervise"
_LOG_FILENAME = "decision.log"

_USAGE = "Usage: claude-supervise.py [--dry-run | --arm] [--log PATH] -- <child argv...>\n"


@dataclass
class InputActivity:
    """Tracks observed stdin activity forwarded to the supervised child."""

    bytes_seen: int = 0
    last_input_monotonic: float | None = None

    def record(self, data: bytes) -> None:
        """Record a chunk of stdin data that was forwarded to the child."""
        self.bytes_seen += len(data)
        self.last_input_monotonic = os.times().elapsed


class DecisionLog:
    """Append-only, timestamped log file for supervisor decisions/observations.

    Every line is timestamped and written immediately (no buffering) so a
    crash or forced kill of the supervised session never loses prior
    observations. Write failures are never swallowed -- FAIL FAST so a broken
    log path is surfaced immediately rather than silently discarding
    supervisor context.
    """

    def __init__(self, path: Path | None = None) -> None:
        """Create (or attach to) a decision log file.

        Args:
            path: Explicit log file path. When omitted, defaults to
                ``$CLAUDE_PROJECT_DIR/untracked/supervise/decision.log``
                (falling back to the current working directory when the
                environment variable is unset).

        Raises:
            OSError: If the parent directory cannot be created.
        """
        self._path = path if path is not None else self._default_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _default_path() -> Path:
        project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
        return project_dir / "untracked" / _LOG_SUBDIRECTORY / _LOG_FILENAME

    @property
    def path(self) -> Path:
        """Absolute path to the underlying log file."""
        return self._path

    def write(self, message: str) -> None:
        """Append a single timestamped line to the log.

        Args:
            message: The message to record.

        Raises:
            OSError: If the file cannot be written (never swallowed).
        """
        timestamp = datetime.now(UTC).isoformat()
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")


# ---------------------------------------------------------------------------
# Compact decision logic (Plan 00135 Slice 2, dry-run)
#
# The daemon writes an observe-only "context sidecar" JSON per session
# (handlers/status_line/context_sidecar.py). This supervisor READS the freshest
# sidecar and runs the Decision H state machine to decide when it WOULD inject
# `/compact` (and, once compaction is under way, `continue`). In the dry-run
# phase these decisions are LOGGED ONLY -- nothing is ever written to the child
# PTY. Arming the actual keystroke injection is a separate, later step.
# ---------------------------------------------------------------------------

_SIDECAR_SUBDIR = "context-sidecar"

# State-machine policy defaults (seconds / counts). Conservative on purpose.
_DEFAULT_FRESHNESS_SECONDS = 30.0
_DEFAULT_COOLDOWN_SECONDS = 300.0
_DEFAULT_AWAIT_TIMEOUT_SECONDS = 120.0
_DEFAULT_MAX_INJECTIONS = 20


class Decision(enum.Enum):
    """What the supervisor WOULD do this evaluation (dry-run logs it)."""

    NOOP = "noop"
    WOULD_COMPACT = "would-compact"
    WOULD_CONTINUE = "would-continue"


class SupervisorState(enum.Enum):
    """Two-state compact-and-resume machine (Decision H)."""

    MONITOR = "monitor"
    AWAIT_COMPACTING = "await-compacting"


@dataclass(frozen=True)
class SidecarReading:
    """A parsed snapshot of the daemon-written context sidecar."""

    red: bool
    tier: str
    pct: float
    session_id: str
    ts: float
    seq: int
    writer_pid: int
    compacting: bool
    stale: bool


@dataclass(frozen=True)
class CompactPolicy:
    """Tunable guards for the compact state machine."""

    freshness_seconds: float = _DEFAULT_FRESHNESS_SECONDS
    cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS
    await_timeout_seconds: float = _DEFAULT_AWAIT_TIMEOUT_SECONDS
    max_injections: int = _DEFAULT_MAX_INJECTIONS


@dataclass(frozen=True)
class Evaluation:
    """The outcome of one state-machine evaluation."""

    decision: Decision
    reason: str


def _coerce_float(value: object) -> float:
    """Best-effort float coercion; non-numeric values become 0.0."""
    return float(value) if isinstance(value, (int, float)) else 0.0


def _coerce_int(value: object) -> int:
    """Best-effort int coercion; non-numeric values become 0."""
    return int(value) if isinstance(value, (int, float)) else 0


def _default_sidecar_dir() -> Path:
    """Resolve the daemon's context-sidecar directory from the environment.

    Mirrors ``DecisionLog._default_path``: uses ``$CLAUDE_PROJECT_DIR`` (the
    project root, exported by ccy in-container), falling back to the current
    working directory when the variable is unset.
    """
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    return project_dir / "untracked" / _SIDECAR_SUBDIR


def load_freshest_sidecar(
    directory: Path, *, now: float, freshness_seconds: float
) -> SidecarReading | None:
    """Load the freshest (max-``ts``) sidecar JSON in ``directory``.

    Returns None when the directory is absent or contains no parseable
    sidecar. Malformed files are skipped (they may be from an older schema or
    a foreign writer) rather than aborting the scan -- the freshest VALID
    reading wins. ``stale`` is set when ``now - ts`` exceeds
    ``freshness_seconds`` (the daemon has not rendered a status line recently,
    so the session is idle or gone and must not be acted on).

    Args:
        directory: The ``context-sidecar`` directory to scan.
        now: Current epoch time (injected for deterministic tests).
        freshness_seconds: Age beyond which a reading is marked ``stale``.

    Returns:
        The freshest valid ``SidecarReading``, or None if none is available.
    """
    if not directory.is_dir():
        return None

    freshest_data = None
    freshest_ts = float("-inf")
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Unreadable or malformed sidecar -- skip and keep scanning.
            continue
        if not isinstance(data, dict):
            continue
        ts = _coerce_float(data.get("ts"))
        if ts > freshest_ts:
            freshest_ts = ts
            freshest_data = data

    if freshest_data is None:
        return None

    return SidecarReading(
        red=bool(freshest_data.get("red", False)),
        tier=str(freshest_data.get("tier", "")),
        pct=_coerce_float(freshest_data.get("pct")),
        session_id=str(freshest_data.get("session_id", "")),
        ts=freshest_ts,
        seq=_coerce_int(freshest_data.get("seq")),
        writer_pid=_coerce_int(freshest_data.get("writer_pid")),
        compacting=bool(freshest_data.get("compacting", False)),
        stale=(now - freshest_ts) > freshness_seconds,
    )


class CompactStateMachine:
    """Decision H compact-and-resume machine (pure; injects nothing).

    MONITOR: when the sidecar is fresh + red AND the session is idle AND the
    cooldown/cap allow it, decide WOULD_COMPACT and move to AWAIT_COMPACTING.

    AWAIT_COMPACTING: once the sidecar reports ``compacting`` (compaction has
    started), decide WOULD_CONTINUE and return to MONITOR (starting the
    cooldown). If compaction never starts within ``await_timeout_seconds``,
    give up and return to MONITOR so a missed transition cannot wedge the
    machine forever.
    """

    def __init__(self, policy: CompactPolicy) -> None:
        self._policy = policy
        self.state = SupervisorState.MONITOR
        self._injections = 0
        self._last_action_ts: float | None = None

    def evaluate(self, reading: SidecarReading | None, *, idle: bool, now: float) -> Evaluation:
        """Advance the machine one step and return what it WOULD do."""
        if self.state is SupervisorState.AWAIT_COMPACTING:
            return self._evaluate_await(reading, now=now)
        return self._evaluate_monitor(reading, idle=idle, now=now)

    def _evaluate_monitor(
        self, reading: SidecarReading | None, *, idle: bool, now: float
    ) -> Evaluation:
        if reading is None:
            return Evaluation(Decision.NOOP, "no sidecar reading")
        if reading.stale:
            return Evaluation(Decision.NOOP, "sidecar stale")
        if not reading.red:
            return Evaluation(Decision.NOOP, f"not red (tier={reading.tier})")
        if not idle:
            return Evaluation(Decision.NOOP, "session busy (composing)")
        if self._injections >= self._policy.max_injections:
            return Evaluation(Decision.NOOP, "injection cap reached")
        if not self._cooldown_elapsed(now):
            return Evaluation(Decision.NOOP, "cooldown active")

        self._injections += 1
        self._last_action_ts = now
        self.state = SupervisorState.AWAIT_COMPACTING
        return Evaluation(
            Decision.WOULD_COMPACT,
            f"red at {reading.pct:.0f}% + idle -> would inject /compact",
        )

    def _evaluate_await(self, reading: SidecarReading | None, *, now: float) -> Evaluation:
        if reading is not None and reading.compacting:
            self._last_action_ts = now
            self.state = SupervisorState.MONITOR
            return Evaluation(
                Decision.WOULD_CONTINUE,
                "compaction under way -> would inject continue",
            )
        if self._await_timed_out(now):
            self.state = SupervisorState.MONITOR
            return Evaluation(Decision.NOOP, "await-compacting timed out -> back to monitor")
        return Evaluation(Decision.NOOP, "awaiting compaction start")

    def _cooldown_elapsed(self, now: float) -> bool:
        if self._last_action_ts is None:
            return True
        return (now - self._last_action_ts) >= self._policy.cooldown_seconds

    def _await_timed_out(self, now: float) -> bool:
        if self._last_action_ts is None:
            return False
        return (now - self._last_action_ts) > self._policy.await_timeout_seconds


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
        log: Optional decision log to record a startup line and an on-exit
            summary to.
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
    mode = "dry-run" if dry_run else "armed (no-op in v0)"

    if log is not None:
        log.write(f"supervisor active ({mode}); transparent passthrough; wrapping: {argv}")

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
        log.write(
            f"supervisor exiting ({mode}); transparent passthrough; "
            f"{activity.bytes_seen} input bytes observed"
        )

    return exit_code


def _split_child_argv(argv: list[str]) -> list[str] | None:
    """Return everything after the first `--` separator, or None if absent/empty."""
    if "--" not in argv:
        return None
    child = argv[argv.index("--") + 1 :]
    return child if child else None


def _parse_supervisor_flags(argv: list[str]) -> argparse.Namespace:
    """Parse only the flags that appear before `--` (argparse never sees the child argv)."""
    supervisor_argv = argv[: argv.index("--")] if "--" in argv else argv

    parser = argparse.ArgumentParser(
        prog="claude-supervise",
        description="Transparent PTY supervisor for wrapping `claude` (v0).",
        add_help=False,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Log-only observation mode (default). No behavioural effect in v0.",
    )
    mode_group.add_argument(
        "--arm",
        dest="dry_run",
        action="store_false",
        help="Documented no-op in v0 (injection does not exist yet); reserved for v1.",
    )
    parser.add_argument(
        "--log",
        dest="log_path",
        type=Path,
        default=None,
        help="Decision log file path (default: $CLAUDE_PROJECT_DIR/untracked/supervise/).",
    )
    return parser.parse_args(supervisor_argv)


def _resolve_decision_log(explicit_path: Path | None) -> DecisionLog:
    """Build the DecisionLog from an explicit path, or the environment-derived default."""
    return DecisionLog(explicit_path)


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, run the PTY supervisor, return the exit code.

    Args:
        argv: Command-line arguments (excluding program name). Defaults to
            `sys.argv[1:]` when None.

    Returns:
        2 if no child argv is supplied after `--`; otherwise the supervised
        child's exit code.
    """
    argv = argv if argv is not None else sys.argv[1:]

    child_argv = _split_child_argv(argv)
    if child_argv is None:
        sys.stderr.write(_USAGE)
        return 2

    flags = _parse_supervisor_flags(argv)
    log = _resolve_decision_log(flags.log_path)

    return supervise(child_argv, dry_run=flags.dry_run, log=log)


if __name__ == "__main__":
    raise SystemExit(main())
