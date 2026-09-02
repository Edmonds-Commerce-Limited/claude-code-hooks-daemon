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

This handler also renders TRANSIENT supervisor messages (the Ctrl+Z "ignored"
notice and future ones, Plan 00173): the supervisor's ``StatusMessagePoster``
writes a TTL-bounded ``supervise/status-message.json`` and, while one is live,
this handler paints the top hat AND the message text as ONE attached segment on
a shared background (warning level = orange, black text for legibility) — never
a separate status section with a second top hat. When the message expires the
plain state top hat returns.

The "not configured" state renders NOTHING so the handler is safe to enable by
default: a project that never runs the ccy supervisor shows no icon, while a
project whose supervisor died (a status file left behind, no live process) gets
the orange alarm.

Detection is grounded in the live PROCESS, not merely the status file — the
supervisor's status file was observed going missing while the supervisor was
still running (``claude-supervise.py --arm``), which used to make the icon
vanish even though the safety net was on. Resolution therefore: (1) trust the
status file when it names a live supervisor pid, else (2) scan ``/proc`` for a
live ``claude-supervise`` process, else (3) fall back to orange/none based on
whether a status file is present at all.

Three throttles keep the per-render cost low, because ``handle`` runs on EVERY
status-line render:

- POSITIVE cache: the resolved (pid, armed) identity is IMMUTABLE for the
  lifetime of a supervisor process, so once a supervisor is found it is
  MEMOISED — later renders do only a cheap ``os.kill(pid, 0)`` liveness probe
  instead of the status-file read or the ``/proc`` scan. A crash still flips to
  orange because the liveness probe runs every render; when the cached
  supervisor dies the cache is dropped and the next render re-resolves (picking
  up a replacement).
- NEGATIVE cache: the common case is a project that never runs the supervisor,
  where resolution finds nothing. That "no live supervisor" outcome (NOT_ACTIVE
  or NOT_CONFIGURED) is throttled with a short TTL
  (``_NEGATIVE_CACHE_TTL_SECONDS``) so repeated renders reuse it instead of
  re-resolving every time; a newly-started supervisor — which writes a status
  file — is still picked up within one TTL. Any positive resolution clears the
  negative cache, and a positive cache going stale (supervisor died) also
  invalidates it so the replacement scan is not suppressed.
- WALK throttle: the ``/proc`` scan is a separate, much harder throttle
  (``_PROC_WALK_INTERVAL_SECONDS``), because it costs far more than the other
  two paths and answers a much rarer question. It reads ``cmdline`` for EVERY
  numeric pid, and it exists only for the case where the status file is
  missing while the supervisor is alive. Tying it to the negative-cache TTL
  priced the cheap, precise detector at the expensive fallback's rate.

ANY unexpected failure fails safe to NO segment — this handler must never raise
and never break the status line (mirrors the fail-silent pattern used by
``daemon_stats.py``).
"""

import errno
import json
import logging
import math
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, ProjectContext
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase

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
# The supervisor runs a `--worker` decision subprocess alongside the host. Both
# carry the cmdline marker; when scanning /proc we prefer the HOST (whose pid is
# stable) and fall back to the worker only if the host is not matched.
_SUPERVISOR_WORKER_FLAG = "--worker"

# TTL (seconds) for the negative cache: a "no live supervisor found" resolution
# is reused for this long before it is re-derived, so a non-ccy project does not
# repeat the resolution on every status-line render. Kept short so the orange
# "supervisor down" alarm and the green "came back" flip stay responsive;
# ``time.monotonic`` backs it so a wall-clock change cannot wedge it.
#
# At the measured ~1.04s render interval this serves ceil(5/1.04) = 5 renders
# per miss, comfortably outside the resonance band that
# ``test_render_ttl_resonance.py`` guards (Plan 00238 Task 2.1). This TTL is
# NOT the cost problem — see the walk interval below for what is.
_NEGATIVE_CACHE_TTL_SECONDS = 5.0

# Interval (seconds) between /proc WALKS, throttled INDEPENDENTLY of the
# negative cache above (Plan 00238 Task 2.2).
#
# The two detectors have very different costs and very different jobs, and
# tying them to one TTL priced the cheap one at the expensive one's rate:
#
# - The status file is the fast, precise detector — two stats, and a supervisor
#   that starts normally writes one. It stays at the negative-cache rate, so a
#   newly-started supervisor is still picked up within ~5 seconds.
# - The /proc walk is the slow, imprecise FALLBACK, existing only for the rare
#   inconsistency where the status file goes missing while the supervisor is
#   alive (observed live). It reads /proc/<pid>/cmdline for EVERY numeric pid:
#   measured at ~20us per pid, so ~10ms on a 500-process desktop. Repeating
#   that every 5s forever is ~360,000 /proc reads an hour for a project that
#   will never run the supervisor, which is the common case.
#
# One minute bounds how long that rare inconsistency can mis-render a
# decorative segment, and cuts the walk rate 12-fold. It is ~57 renders at the
# measured interval, nowhere near the resonance band.
_PROC_WALK_INTERVAL_SECONDS = 60.0

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
# Black foreground for message TEXT rendered on a coloured background. The top
# hat is an emoji (foreground colour does not tint it) but the adjacent message
# text does, and the terminal's default dim-grey foreground is illegible on
# orange — so message text is forced to black (matches ``model_context``'s
# black-on-orange context tier).
_FG_BLACK = "\033[30m"

# Transient supervisor -> status-line message channel. The supervisor's
# ``StatusMessagePoster`` writes ``supervise/status-message.json`` (same
# ``_STATUS_SUBDIRECTORY``); this handler renders it ATTACHED to the top hat so a
# notice is one visual unit with the supervisor, not a separate status section.
# The filename/level string are the on-disk contract shared with the supervisor
# (``_STATUS_MESSAGE_FILENAME`` / ``_STATUS_LEVEL_WARNING``) and MUST match.
_MESSAGE_FILENAME = "status-message.json"
_MESSAGE_LEVEL_WARNING = "warning"


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


class SupervisorIndicatorHandler(StatusLineHandlerBase):
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
        # Negative cache: a "no live supervisor" resolution (NOT_ACTIVE or
        # NOT_CONFIGURED) is reused until this monotonic deadline, so a non-ccy
        # project does not re-resolve on every render. Cleared on any positive
        # resolution and when a stale positive cache is dropped.
        self._negative_cache_state: _SupervisorState | None = None
        self._negative_cache_until: float | None = None
        # Monotonic stamp of the last fruitless /proc walk, throttled separately
        # and far harder than the negative cache above — it is the expensive,
        # rarely-useful fallback. Cleared whenever a replacement scan must run
        # immediately (a positive resolution, or a cached supervisor dying).
        self._last_walk_at: float | None = None

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

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Return the supervisor-indicator segment, failing safe on any error.

        A transient supervisor message (Ctrl+Z notice, etc.) is rendered
        ATTACHED to the top hat — one segment, one top hat, the message text
        immediately adjacent on the same background — so it reads as the
        supervisor speaking, never a separate status section. A warning-level
        message paints the whole block orange; otherwise the message rides the
        current state background. When there is no message the plain state top
        hat renders as before.
        """
        message = self._safe_active_message()

        try:
            state = self._detect_state()
        except Exception as e:
            # Fail silent: a false orange alarm would be more misleading than
            # simply omitting the segment on an unexpected error.
            logger.debug("Failed to detect supervisor state: %s", e)
            state = None

        background = _STATE_BACKGROUND.get(state) if state is not None else None

        if message is not None:
            text, level = message
            # Warning paints the whole top-hat block orange; other levels ride
            # the current state colour (falling back to orange if unknown). Text
            # is forced black so it is legible on any of these backgrounds.
            msg_bg = _BG_ORANGE if level == _MESSAGE_LEVEL_WARNING else (background or _BG_ORANGE)
            return AdvisoryResult(context=[f"| {msg_bg}{_FG_BLACK} {_ICON} {text} {_ANSI_RESET}"])

        if background is None:
            # NOT_CONFIGURED and no message — no supervisor status file, render nothing.
            return AdvisoryResult(context=[])
        return AdvisoryResult(context=[f"| {background} {_ICON} {_ANSI_RESET}"])

    def _safe_active_message(self) -> tuple[str, str] | None:
        """Return ``(text, level)`` for the current unexpired message, or None.

        Fail-silent wrapper: any error (missing/malformed/unreadable file) yields
        None so a bad message file can never break the status line.
        """
        try:
            return self._active_message()
        except Exception as e:
            logger.debug("Failed to read supervisor status message: %s", e)
            return None

    def _active_message(self) -> tuple[str, str] | None:
        """Resolve the current transient message as ``(text, level)`` or None.

        None when the message file is absent, malformed, empty-text, missing/
        non-numeric ``expires_at``, or already expired. Expiry is checked against
        the WALL clock because the supervisor writes ``expires_at`` as
        ``time.time() + ttl`` — both sides must use the same clock (NOT the
        monotonic clock used for the negative-cache TTL).

        A payload carrying ``countdown: true`` gets the seconds remaining
        appended to its text, so a longer-lived notice (the audit banner)
        visibly announces that it will clear itself. The key is absent on
        keystroke hints, whose own wording already names any relevant window.
        """
        message = self._read_message(self._message_file_path())
        if message is None:
            return None
        text = message.get("text")
        expires_at = message.get("expires_at")
        level = message.get("level")
        if not isinstance(text, str) or not text.strip():
            return None
        # bool is a subclass of int — exclude it so a stray `true` is not a time.
        if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
            return None
        now = self._wall_now()
        if now >= expires_at:
            return None
        level_str = level if isinstance(level, str) else ""
        rendered = text.strip()
        if message.get("countdown") is True:
            # Rounded UP so a live notice never reads "0s" (which looks stuck)
            # in its final part-second before expiry.
            rendered = f"{rendered} ({math.ceil(expires_at - now)}s)"
        return rendered, level_str

    def _wall_now(self) -> float:
        """Wall-clock epoch seconds (indirected for deterministic testing)."""
        return time.time()

    def _message_file_path(self) -> Path:
        """Return the path to the supervisor's transient message file."""
        return ProjectContext.daemon_untracked_dir() / _STATUS_SUBDIRECTORY / _MESSAGE_FILENAME

    def _read_message(self, path: Path) -> dict[str, Any] | None:
        """Read and parse the transient message file, or None if unusable."""
        if not path.exists():
            return None
        try:
            data: Any = json.loads(path.read_text())
        except (OSError, ValueError) as e:
            logger.debug("Failed to read status message file %s: %s", path, e)
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _now(self) -> float:
        """Monotonic clock reading (indirected for deterministic testing)."""
        return time.monotonic()

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
            # Cached supervisor died — drop the caches and re-resolve below so a
            # replacement supervisor (new pid) is picked up immediately. Neither
            # the negative cache NOR the walk throttle may suppress that
            # replacement scan, which is why both are cleared here.
            self._cached_pid = None
            self._cached_armed = None
            self._negative_cache_state = None
            self._negative_cache_until = None
            self._last_walk_at = None

        # Negative fast path: a recent "no live supervisor" outcome is reused
        # within its TTL so non-ccy projects do not re-resolve every render.
        now = self._now()
        if self._negative_cache_until is not None and now < self._negative_cache_until:
            assert self._negative_cache_state is not None
            return self._negative_cache_state

        return self._resolve_state(now)

    def _resolve_state(self, now: float) -> _SupervisorState:
        """Full resolution, memoising the identity on success.

        Ground truth is "is an armed supervisor PROCESS running", not "does a
        status file exist": the supervisor's status file can go missing while
        the supervisor is very much alive (observed live — the icon vanished
        while ``claude-supervise.py --arm`` was still running). So:

        1. Fast, precise: if the status file names a LIVE supervisor pid, use it.
        2. Fallback: scan ``/proc`` for a live ``claude-supervise`` process, so a
           missing/stale status file never hides an active safety net.
        3. Otherwise decide "down" vs "never configured" from whether a status
           file is present at all (keeps the handler silent for non-ccy projects).
        """
        status_path = self._status_file_path()
        status_present = status_path.exists()
        status = self._read_status(status_path)

        # 1. Status file names a live, genuine supervisor -> use it directly.
        if status is not None:
            pid = status.get("pid")
            if isinstance(pid, int) and self._pid_alive(pid):
                cmdline = self._read_cmdline(pid)
                if cmdline is not None and _SUPERVISOR_CMDLINE_MARKER in cmdline:
                    return self._activate(pid, _SUPERVISOR_ARM_FLAG in cmdline)

        # 2. No usable status-file pid -> discover the supervisor by process.
        #    Throttled independently of (and far harder than) the negative cache:
        #    the walk is the expensive fallback, not the primary detector.
        if self._may_walk(now):
            self._last_walk_at = now
            found = self._scan_for_supervisor()
            if found is not None:
                return self._activate(found[0], found[1])

        # 3. Nothing live. Orange alarm if a supervisor was configured (status
        #    file present) but is down; otherwise render nothing (never configured).
        state = _SupervisorState.NOT_ACTIVE if status_present else _SupervisorState.NOT_CONFIGURED
        # Throttle this negative outcome so the /proc walk is not repeated on
        # every render until the TTL elapses.
        self._negative_cache_state = state
        self._negative_cache_until = now + _NEGATIVE_CACHE_TTL_SECONDS
        return state

    def _may_walk(self, now: float) -> bool:
        """Return True when the /proc walk is due.

        The walk is the fallback for a supervisor whose status file has gone
        missing. Throttling it separately means the cheap, precise status-file
        probe keeps running at the negative-cache rate while the expensive scan
        happens at most once per interval.
        """
        if self._last_walk_at is None:
            return True
        return now - self._last_walk_at >= _PROC_WALK_INTERVAL_SECONDS

    def _activate(self, pid: int, armed: bool) -> _SupervisorState:
        """Memoise a resolved supervisor identity and return its active state."""
        self._cached_pid = pid
        self._cached_armed = armed
        # A positive resolution invalidates any pending negative throttle, and
        # the walk throttle with it: if this supervisor later dies, the
        # replacement scan must not be blocked by a stamp from before it.
        self._negative_cache_state = None
        self._negative_cache_until = None
        self._last_walk_at = None
        return _SupervisorState.ACTIVE_ARMED if armed else _SupervisorState.ACTIVE_DRYRUN

    def _scan_for_supervisor(self) -> tuple[int, bool] | None:
        """Find a live ``claude-supervise`` process by scanning ``/proc``.

        Returns ``(pid, armed)`` for the supervisor HOST when found (preferred
        over the ``--worker`` child, whose pid churns on worker restarts), or the
        worker as a fallback, or None if no supervisor process is running. Only
        runs on a cache miss (a missing status file, or a dead cached pid), so
        the per-render cost stays the cheap ``os.kill`` liveness probe. Never
        raises — an unreadable ``/proc`` yields None (fail-safe to no segment).
        """
        proc_root = Path("/proc")
        try:
            entries = list(proc_root.iterdir())
        except OSError as e:
            logger.debug("Failed to scan /proc for supervisor: %s", e)
            return None

        worker_match: tuple[int, bool] | None = None
        for entry in entries:
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            cmdline = self._read_cmdline(pid)
            if cmdline is None or _SUPERVISOR_CMDLINE_MARKER not in cmdline:
                continue
            armed = _SUPERVISOR_ARM_FLAG in cmdline
            if _SUPERVISOR_WORKER_FLAG not in cmdline:
                return (pid, armed)  # the host is authoritative; stop here
            if worker_match is None:
                worker_match = (pid, armed)
        return worker_match

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
