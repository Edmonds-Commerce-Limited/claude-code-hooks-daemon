"""SupervisorIndicatorHandler - ccy PTY supervisor overseer indicator.

Shows, at a glance, whether the ccy PTY supervisor (``claude-supervise.py``)
is overseeing the session — a top hat (🎩, the "Fat Controller" that directs
the session) whose BACKGROUND colour encodes the state:

- active + armed    -> 🎩 green  background (overseeing + will auto-compact)
- active + dry-run  -> 🎩 yellow background (overseeing only, won't act)
- not active        -> 🎩 orange background (a supervisor exists but is down)
- not configured    -> no segment at all (no supervisor status file present)

Emoji glyphs ignore ANSI *foreground* colour, so the state colour is carried
via the ANSI *background* (which does render behind the glyph) — one icon, no
second glyph.

The "not configured" state renders NOTHING so the handler is safe to enable by
default: a project that never runs the ccy supervisor has no status file and
therefore shows no icon, while a project whose supervisor died leaves its
status file behind and gets the orange alarm.

Detection reads the supervisor's own status file rather than probing live
processes each render. The (pid, armed) identity it resolves is IMMUTABLE for
the lifetime of a given supervisor process, so it is MEMOISED after the first
successful resolution: subsequent renders do only a cheap ``os.kill(pid, 0)``
liveness probe instead of re-reading the (multi-kB) ``/proc/<pid>/cmdline``
every ~1-2s. A crash still flips to orange because the liveness probe runs
every render; when the cached supervisor dies the cache is dropped and the next
render re-resolves (picking up a replacement supervisor if one started).

ANY unexpected failure fails safe to NO segment — this handler must never raise
and never break the status line (mirrors the fail-silent pattern used by
``daemon_stats.py``).
"""

import errno
import json
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest

logger = logging.getLogger(__name__)

# These MUST match the supervisor's own constants in
# ``.claude/ccy/claude-supervise.py`` (``_LOG_SUBDIRECTORY`` /
# ``_SUPERVISOR_STATUS_FILENAME``) — the supervisor writes its status file
# there and this handler must read the exact same path.
_STATUS_SUBDIRECTORY = "supervise"
_STATUS_FILENAME = "supervisor-status.json"

# The supervisor's own cmdline marker and arm flag — used to confirm a live
# pid is genuinely the supervisor (pid-reuse guard) and whether it was
# launched armed.
_SUPERVISOR_CMDLINE_MARKER = "claude-supervise"
_SUPERVISOR_ARM_FLAG = "--arm"

# The top hat — the "Fat Controller" overseeing/directing the session. A single
# glyph; state is carried by the ANSI BACKGROUND colour behind it (foreground
# colour does not tint an emoji, but the cell background does render).
_ICON = "🎩"

# ANSI background SGR codes. Green/yellow are the standard 8-colour backgrounds;
# orange has no 8-colour slot so it uses a 256-colour background (208 == orange).
# A leading/trailing space gives the background body around the wide glyph.
_BG_GREEN = "\033[42m"
_BG_YELLOW = "\033[43m"
_BG_ORANGE = "\033[48;5;208m"
_ANSI_RESET = "\033[0m"


class _SupervisorState(Enum):
    """Detected supervisor state."""

    ACTIVE_ARMED = "active_armed"
    ACTIVE_DRYRUN = "active_dryrun"
    NOT_ACTIVE = "not_active"
    NOT_CONFIGURED = "not_configured"


# State -> the background SGR that colours the top hat. NOT_CONFIGURED has no
# entry: it renders no segment at all (see ``handle``).
_STATE_BACKGROUND: dict[_SupervisorState, str] = {
    _SupervisorState.ACTIVE_ARMED: _BG_GREEN,
    _SupervisorState.ACTIVE_DRYRUN: _BG_YELLOW,
    _SupervisorState.NOT_ACTIVE: _BG_ORANGE,
}


class SupervisorIndicatorHandler(Handler):
    """Show whether the ccy PTY supervisor is overseeing the session."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUPERVISOR_INDICATOR,
            priority=Priority.SUPERVISOR_INDICATOR,
            terminal=False,
            tags=[
                HandlerTag.STATUSLINE,
                HandlerTag.DISPLAY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # Memoised supervisor identity (immutable per supervisor process).
        # Populated on the first successful resolution; the fast render path
        # then only re-checks pid liveness. Dropped when the cached pid dies.
        self._cached_pid: int | None = None
        self._cached_armed: bool | None = None

    def get_default_enabled(self) -> bool:
        """On by default.

        Safe to ship enabled because the segment renders NOTHING when no
        supervisor status file exists (the NOT_CONFIGURED state) — a project
        that never runs the ccy supervisor shows no icon at all. Projects that
        DO run the supervisor get the green/yellow/orange top hat. See the
        module docstring for the state table.
        """
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status line events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return the supervisor-indicator segment, failing safe on any error."""
        try:
            state = self._detect_state()
        except Exception as e:
            # Fail silent: a false orange alarm would be more misleading than
            # simply omitting the segment on an unexpected error.
            logger.debug("Failed to detect supervisor state: %s", e)
            return HookResult(context=[])

        background = _STATE_BACKGROUND.get(state)
        if background is None:
            # NOT_CONFIGURED — no supervisor status file, render nothing.
            return HookResult(context=[])
        return HookResult(context=[f"| {background} {_ICON} {_ANSI_RESET}"])

    def _detect_state(self) -> _SupervisorState:
        """Detect the supervisor state, using the memoised identity fast path."""
        # Fast path: a previously-resolved supervisor. Only the cheap liveness
        # probe runs — no status-file or /proc/cmdline read.
        if self._cached_pid is not None:
            if self._pid_alive(self._cached_pid):
                return (
                    _SupervisorState.ACTIVE_ARMED
                    if self._cached_armed
                    else _SupervisorState.ACTIVE_DRYRUN
                )
            # Cached supervisor died — drop the cache and re-resolve below so a
            # replacement supervisor (new pid) is picked up.
            self._cached_pid = None
            self._cached_armed = None

        return self._resolve_state()

    def _resolve_state(self) -> _SupervisorState:
        """Full resolution: read status file + cmdline, memoising on success."""
        status = self._read_status(self._status_file_path())
        if status is None:
            # No status file at all -> supervisor not configured (render nothing).
            # A present-but-unreadable file is treated as NOT_ACTIVE below.
            if not self._status_file_path().exists():
                return _SupervisorState.NOT_CONFIGURED
            return _SupervisorState.NOT_ACTIVE

        pid = status.get("pid")
        if not isinstance(pid, int) or not self._pid_alive(pid):
            return _SupervisorState.NOT_ACTIVE

        cmdline = self._read_cmdline(pid)
        if cmdline is None or _SUPERVISOR_CMDLINE_MARKER not in cmdline:
            # Unreadable, or the pid was reused by an unrelated process.
            return _SupervisorState.NOT_ACTIVE

        armed = _SUPERVISOR_ARM_FLAG in cmdline
        # Memoise the immutable identity for the fast path.
        self._cached_pid = pid
        self._cached_armed = armed
        return _SupervisorState.ACTIVE_ARMED if armed else _SupervisorState.ACTIVE_DRYRUN

    def _status_file_path(self) -> Path:
        """Return the path to the supervisor's status file."""
        return ProjectContext.daemon_untracked_dir() / _STATUS_SUBDIRECTORY / _STATUS_FILENAME

    def _read_status(self, status_path: Path) -> dict[str, Any] | None:
        """Read and parse the supervisor status file, or None if unusable."""
        if not status_path.exists():
            return None
        try:
            data: Any = json.loads(status_path.read_text())
        except (OSError, ValueError) as e:
            logger.debug("Failed to read supervisor status file %s: %s", status_path, e)
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _pid_alive(self, pid: int) -> bool:
        """Return True if a process with the given pid exists."""
        try:
            os.kill(pid, 0)
        except OSError as e:
            if e.errno == errno.EPERM:
                # Process exists but we don't own it - still alive.
                return True
            return False
        return True

    def _read_cmdline(self, pid: int) -> str | None:
        """Read /proc/{pid}/cmdline as a space-separated string, or None."""
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        try:
            raw = cmdline_path.read_bytes()
        except OSError as e:
            logger.debug("Failed to read cmdline for pid %s: %s", pid, e)
            return None
        return raw.decode(errors="replace").replace("\x00", " ")

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import Decision, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="supervisor indicator handler test",
                command='echo "test"',
                description=(
                    "Verify the supervisor indicator shows a top hat (🎩) with "
                    "a green background when the ccy supervisor is active and "
                    "armed, yellow when active but dry-run, orange when a "
                    "supervisor exists but is down, and no segment when no "
                    "supervisor is configured. Confirmed active by the daemon "
                    "loading without errors."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            )
        ]
