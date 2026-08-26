"""TTL state for the skill-scan cadence (Plan 00274).

Follows the ``version_check`` cache pattern: a JSON sidecar under the daemon
untracked dir, corrupt/missing treated as expired (fails toward a
suggestion, never toward silence forever), write failures logged and
swallowed. ``last_attempt_at`` is tracked separately from ``last_scan_at``
so a failed scan retries without nagging every session.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.skill_scan.constants import (
    ATTEMPT_QUIET_SECONDS,
    SECONDS_PER_DAY,
)

logger = logging.getLogger(__name__)

_LAST_SCAN_AT = "last_scan_at"
_LAST_ATTEMPT_AT = "last_attempt_at"
_LAST_REPORT_PATH = "last_report_path"


@dataclass(frozen=True)
class ScanState:
    """The persisted scan cadence state."""

    last_scan_at: float | None = None
    last_attempt_at: float | None = None
    last_report_path: str | None = None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def load_state(path: Path) -> ScanState:
    """Read the state file; corrupt or missing yields the empty state."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ScanState()
    if not isinstance(raw, dict):
        return ScanState()
    report_path = raw.get(_LAST_REPORT_PATH)
    return ScanState(
        last_scan_at=_as_float(raw.get(_LAST_SCAN_AT)),
        last_attempt_at=_as_float(raw.get(_LAST_ATTEMPT_AT)),
        last_report_path=report_path if isinstance(report_path, str) else None,
    )


def _write_state(path: Path, state: ScanState) -> None:
    payload = {
        _LAST_SCAN_AT: state.last_scan_at,
        _LAST_ATTEMPT_AT: state.last_attempt_at,
        _LAST_REPORT_PATH: state.last_report_path,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:
        logger.debug("Failed to write skill-scan state %s: %s", path, exc)


def record_attempt(path: Path, now: float | None = None) -> None:
    """Record that a scan was attempted (model stage may have failed)."""
    current = load_state(path)
    _write_state(
        path,
        ScanState(
            last_scan_at=current.last_scan_at,
            last_attempt_at=now if now is not None else time.time(),
            last_report_path=current.last_report_path,
        ),
    )


def record_success(path: Path, report_path: str, now: float | None = None) -> None:
    """Record a completed scan and its report path."""
    stamp = now if now is not None else time.time()
    _write_state(
        path,
        ScanState(last_scan_at=stamp, last_attempt_at=stamp, last_report_path=report_path),
    )


def is_advisory_due(state: ScanState, interval_days: int, now: float | None = None) -> bool:
    """Should the SessionStart advisory fire (or the CLI's TTL gate open)?

    Due when no successful scan happened inside ``interval_days`` — UNLESS an
    attempt was made recently (:data:`ATTEMPT_QUIET_SECONDS`), so a
    permanently-failing environment retries daily instead of nagging every
    session.
    """
    moment = now if now is not None else time.time()
    if state.last_scan_at is not None:
        if (moment - state.last_scan_at) < interval_days * SECONDS_PER_DAY:
            return False
    if state.last_attempt_at is not None:
        if (moment - state.last_attempt_at) < ATTEMPT_QUIET_SECONDS:
            return False
    return True
