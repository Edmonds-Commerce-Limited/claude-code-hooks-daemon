"""Last-run state for the config-optimisation review (Plan 00308).

Follows the ``skill_scan.state`` / ``version_check`` pattern: a JSON sidecar
under the daemon untracked dir. Missing or corrupt state is treated as
"never run" (fails toward reminding, never toward permanent silence), and
write failures are logged and swallowed rather than raised.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Filename for the state sidecar, placed directly under the daemon untracked
#: dir (same directory as ``version_check_cache.json``).
STATE_FILE_NAME = "config_optimisation_state.json"

_LAST_RUN_VERSION = "last_run_version"
_LAST_RUN_AT = "last_run_at"


@dataclass(frozen=True)
class ConfigOptimisationState:
    """The persisted config-optimisation last-run record."""

    last_run_version: str | None = None
    last_run_at: float | None = None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def load_state(path: Path) -> ConfigOptimisationState:
    """Read the state file; corrupt or missing yields the never-run state."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ConfigOptimisationState()
    if not isinstance(raw, dict):
        return ConfigOptimisationState()
    version = raw.get(_LAST_RUN_VERSION)
    return ConfigOptimisationState(
        last_run_version=version if isinstance(version, str) else None,
        last_run_at=_as_float(raw.get(_LAST_RUN_AT)),
    )


def record_run(path: Path, version: str, now: float | None = None) -> None:
    """Record that the config-optimisation review ran against ``version``."""
    payload = {
        _LAST_RUN_VERSION: version,
        _LAST_RUN_AT: now if now is not None else time.time(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:
        logger.debug("Failed to write config-optimisation state %s: %s", path, exc)
