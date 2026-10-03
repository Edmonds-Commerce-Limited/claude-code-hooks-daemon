"""Latest subscription-usage snapshot, kept from the Status event (Plan 00479).

Every Status payload on a claude.ai Pro or Max session carries
``rate_limits.five_hour`` and ``rate_limits.seven_day``, each with
``used_percentage`` (0 to 100, possibly fractional) and ``resets_at`` (epoch
seconds). No other hook event carries usage, so the daemon keeps the last
reading here for every handler that wants it: the status-line segment today,
a host usage ceiling later.

**Usage is account-wide**, not per-session, so there is ONE snapshot and not
one per session. Two copies of it exist:

- in memory, on the :class:`UsageTracker` the data layer owns (the hot copy);
- in ``{daemon_untracked_dir}/usage-snapshot.json`` (the host-wide copy), so a
  freshly restarted daemon, or a handler asked before any Status event has
  arrived, still has the last reading.

**A window past its ``resets_at`` reads as absent.** The percentage stops
describing the account the moment the window rolls over, and a stale high
reading must never look like a live one. Expiry is applied when the snapshot
is READ, against the clock the reader supplies, so a snapshot that was fresh
when stored expires on its own.

**An event without usage changes nothing.** A payload before the session's
first response, or on a plan that has no usage data, must not erase a good
reading another session has already supplied. A payload carrying one window
updates that window and leaves the other alone.

**Persistence fails open.** The file is written atomically (private temp file
then ``replace``), only when the reading changed or a heartbeat has elapsed
(the Status event arrives about once a second), and an I/O failure is logged
once per attempt and never raised: the in-memory copy stays authoritative.
"""

import json
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

#: Payload key carrying the usage windows.
RATE_LIMITS_KEY: Final[str] = "rate_limits"

#: Window keys, as the payload and the persisted file spell them.
FIVE_HOUR_KEY: Final[str] = "five_hour"
SEVEN_DAY_KEY: Final[str] = "seven_day"

_USED_PERCENTAGE: Final[str] = "used_percentage"
_RESETS_AT: Final[str] = "resets_at"
_OBSERVED_AT: Final[str] = "observed_at"

#: File name of the host-wide copy, directly under the daemon untracked dir.
STATE_FILE_NAME: Final[str] = "usage-snapshot.json"

#: An unchanged reading is re-persisted after this many seconds, so the file's
#: ``observed_at`` stays a usable freshness signal for a reader.
PERSIST_HEARTBEAT_SECONDS: Final[float] = 60.0

_MAX_PERCENT: Final[float] = 100.0


@dataclass(frozen=True)
class UsageWindow:
    """One usage window as last reported.

    Attributes:
        used_percentage: Share of the window used, 0 to 100.
        resets_at: Epoch seconds at which the window rolls over.
        observed_at: Epoch seconds at which the daemon saw this reading.
    """

    used_percentage: float
    resets_at: int
    observed_at: float

    def seconds_until_reset(self, now: float) -> int:
        """Whole seconds until ``resets_at``, never negative."""
        return max(int(self.resets_at - now), 0)


@dataclass(frozen=True)
class UsageSnapshot:
    """The live usage windows; a window that is absent or expired is ``None``."""

    five_hour: UsageWindow | None
    seven_day: UsageWindow | None

    def highest_used_percentage(self) -> float | None:
        """The larger used percentage of the present windows, or None if neither is."""
        values = [w.used_percentage for w in (self.five_hour, self.seven_day) if w is not None]
        return max(values) if values else None


def _parse_window(raw: object, observed_at: float) -> UsageWindow | None:
    """A validated window, or None when the payload value cannot be trusted."""
    if not isinstance(raw, dict):
        return None
    pct = raw.get(_USED_PERCENTAGE)
    resets_at = raw.get(_RESETS_AT)
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        return None
    if isinstance(resets_at, bool) or not isinstance(resets_at, (int, float)):
        return None
    if not math.isfinite(pct) or not 0.0 <= pct <= _MAX_PERCENT:
        return None
    if not math.isfinite(resets_at) or resets_at <= 0:
        return None
    return UsageWindow(float(pct), int(resets_at), observed_at)


def _parse_persisted_window(raw: object) -> UsageWindow | None:
    """A window read back from the state file (which also carries ``observed_at``)."""
    if not isinstance(raw, dict):
        return None
    observed = raw.get(_OBSERVED_AT)
    if isinstance(observed, bool) or not isinstance(observed, (int, float)):
        return None
    return _parse_window(raw, float(observed))


def _window_to_json(window: UsageWindow) -> dict[str, float | int]:
    return {
        _USED_PERCENTAGE: window.used_percentage,
        _RESETS_AT: window.resets_at,
        _OBSERVED_AT: window.observed_at,
    }


def _live(window: UsageWindow | None, now: float) -> UsageWindow | None:
    """``window`` unless it has reached its reset instant."""
    if window is None or window.resets_at <= now:
        return None
    return window


def _read_file(state_file: Path) -> tuple[UsageWindow | None, UsageWindow | None]:
    """The persisted windows, or (None, None) when the file is absent or unusable."""
    try:
        data: Any = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return (None, None)
    except (OSError, ValueError) as exc:
        logger.debug("Usage snapshot file unreadable (%s): %s", state_file, exc)
        return (None, None)
    if not isinstance(data, dict):
        return (None, None)
    return (
        _parse_persisted_window(data.get(FIVE_HOUR_KEY)),
        _parse_persisted_window(data.get(SEVEN_DAY_KEY)),
    )


def _write_state_file(state_file: Path, payload: dict[str, dict[str, float | int]]) -> bool:
    """Atomically replace ``state_file`` with ``payload``; False when the disk refused.

    Private temp file then ``replace``, so a concurrent reader (another daemon
    on the host) never sees a half-written file.
    """
    tmp_path = unique_temp_path(state_file)
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(state_file)
    except OSError as exc:
        logger.warning("Could not persist usage snapshot to %s: %s", state_file, exc)
        _discard_temp_file(tmp_path)
        return False
    return True


def _discard_temp_file(tmp_path: Path) -> None:
    """Remove a temp file a failed write left behind.

    The write failure is already reported, so a failed cleanup is logged at
    debug level only (it usually means the temp file was never created).
    """
    try:
        tmp_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("Could not remove usage snapshot temp file %s: %s", tmp_path, exc)


def usage_state_file(daemon_untracked_dir: Path) -> Path:
    """The host-wide snapshot file inside the daemon's untracked directory."""
    return daemon_untracked_dir / STATE_FILE_NAME


def resolve_usage_state_file() -> Path | None:
    """The snapshot file for the running project, or None before ProjectContext exists."""
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    if not ProjectContext.is_initialized():
        logger.debug("No project context; usage snapshot is memory-only")
        return None
    return usage_state_file(ProjectContext.daemon_untracked_dir())


class UsageTracker:
    """Holds the latest usage windows and mirrors them to a host-wide file."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._five_hour: UsageWindow | None = None
        self._seven_day: UsageWindow | None = None
        # (percentage, resets_at) pairs last handed to the persister, and when.
        self._persisted_key: tuple[tuple[float, int] | None, tuple[float, int] | None] | None = None
        self._persisted_at: float = 0.0

    def reset(self) -> None:
        """Forget everything held in memory. For tests and session cleanup."""
        with self._lock:
            self._five_hour = None
            self._seven_day = None
            self._persisted_key = None
            self._persisted_at = 0.0

    def update_from_status_event(
        self,
        hook_input: dict[str, Any],
        *,
        now: float,
        state_file: Path | None = None,
    ) -> None:
        """Fold a Status event's ``rate_limits`` into the snapshot.

        Args:
            hook_input: Status event payload.
            now: Epoch seconds at which the event was observed.
            state_file: Host-wide file to mirror to, or None for memory only.
        """
        rate_limits = hook_input.get(RATE_LIMITS_KEY)
        if not isinstance(rate_limits, dict):
            return
        five = _parse_window(rate_limits.get(FIVE_HOUR_KEY), now)
        seven = _parse_window(rate_limits.get(SEVEN_DAY_KEY), now)
        if five is None and seven is None:
            return
        with self._lock:
            if five is not None:
                self._five_hour = five
            if seven is not None:
                self._seven_day = seven
            self._persist_locked(state_file, now)

    def _persist_locked(self, state_file: Path | None, now: float) -> None:
        """Write the file if the reading changed or the heartbeat elapsed. Never raises."""
        if state_file is None:
            return
        key = (
            (
                (self._five_hour.used_percentage, self._five_hour.resets_at)
                if self._five_hour
                else None
            ),
            (
                (self._seven_day.used_percentage, self._seven_day.resets_at)
                if self._seven_day
                else None
            ),
        )
        if key == self._persisted_key and now - self._persisted_at < PERSIST_HEARTBEAT_SECONDS:
            return
        # Recorded before the write, so a failing disk is retried once per
        # change or heartbeat rather than on every Status event.
        self._persisted_key = key
        self._persisted_at = now
        payload = {
            name: _window_to_json(window)
            for name, window in ((FIVE_HOUR_KEY, self._five_hour), (SEVEN_DAY_KEY, self._seven_day))
            if window is not None
        }
        _write_state_file(state_file, payload)

    def latest(self, *, now: float, state_file: Path | None = None) -> UsageSnapshot | None:
        """The live usage windows, or None when there are none.

        Memory is authoritative once any Status event has been seen. Until
        then the host-wide file, when given, supplies the last reading.

        Args:
            now: Epoch seconds the caller judges expiry against.
            state_file: Host-wide file to fall back to, or None for memory only.
        """
        with self._lock:
            five, seven = self._five_hour, self._seven_day
        if five is None and seven is None and state_file is not None:
            five, seven = _read_file(state_file)
        five, seven = _live(five, now), _live(seven, now)
        if five is None and seven is None:
            return None
        return UsageSnapshot(five_hour=five, seven_day=seven)
