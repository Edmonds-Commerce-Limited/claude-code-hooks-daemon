"""Persistent project-handler load-failure state (Plan 00143).

When project-level handlers fail to load (e.g. an upgrade introduced a new
required abstract method an older handler does not implement), the daemon does
the safe thing and skips them — but historically did so *silently*, leaving an
agent to work a whole session believing protections were live when they were
not.

This module persists the **running daemon's** actual load failures to a small
JSON state file under the daemon untracked dir, so two consumers can surface a
loud, recurring signal:

  1. the ``project_handler_load_checker`` SessionStart handler (loud alert), and
  2. the ``status`` / ``health`` / ``check`` CLI commands (degraded signal).

The state always reflects the running daemon: ``write_load_failures`` is called
on every startup and clears the file when there are zero failures, so a daemon
that now loads cleanly erases any stale degraded state. The alert therefore
persists until the handler is fixed AND the daemon restarted — which is exactly
the correct remediation.

Security: the state file lives under ``ProjectContext.daemon_untracked_dir()``,
never ``/tmp`` (B108).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoadFailure

logger = logging.getLogger(__name__)

# State file under the daemon untracked dir (never /tmp — B108).
_STATE_FILENAME: Final[str] = "project-handler-load-failures.json"

# Bump if the on-disk shape changes; readers tolerate older/unknown shapes.
_SCHEMA_VERSION: Final[int] = 1

# JSON keys (named constants — single source of truth for the on-disk schema).
_KEY_SCHEMA_VERSION: Final[str] = "schema_version"
_KEY_LOADED_COUNT: Final[str] = "loaded_count"
_KEY_FAILED_COUNT: Final[str] = "failed_count"
_KEY_FAILURES: Final[str] = "failures"
_KEY_FILENAME: Final[str] = "filename"
_KEY_EVENT_DIR: Final[str] = "event_dir"
_KEY_REASON: Final[str] = "reason"


@dataclass(frozen=True)
class ProjectHandlerHealthState:
    """The persisted health of project-handler loading for the running daemon.

    Attributes:
        failures: Structured records of every handler that failed to load.
        loaded_count: How many project handlers loaded successfully.
    """

    failures: list[ProjectHandlerLoadFailure] = field(default_factory=list)
    loaded_count: int = 0

    @property
    def is_degraded(self) -> bool:
        """True iff one or more project handlers failed to load."""
        return bool(self.failures)

    @property
    def failed_count(self) -> int:
        """Number of project handlers that failed to load."""
        return len(self.failures)


def state_file_path() -> Path:
    """Return the absolute path to the load-failure state file."""
    return ProjectContext.daemon_untracked_dir() / _STATE_FILENAME


def write_load_failures(
    failures: list[ProjectHandlerLoadFailure],
    *,
    loaded_count: int,
) -> None:
    """Persist the current load failures, or clear the state when there are none.

    Always-rewrite semantics: passing an empty ``failures`` list clears any
    previously-persisted degraded state, so a daemon that now loads cleanly
    erases stale failures. A filesystem error never crashes the daemon — it is
    logged (visibly, not swallowed) and startup proceeds.

    Args:
        failures: The handlers that failed to load this startup.
        loaded_count: How many project handlers loaded successfully.
    """
    if not failures:
        clear_load_failures()
        return

    payload: dict[str, Any] = {
        _KEY_SCHEMA_VERSION: _SCHEMA_VERSION,
        _KEY_LOADED_COUNT: loaded_count,
        _KEY_FAILED_COUNT: len(failures),
        _KEY_FAILURES: [
            {
                _KEY_FILENAME: failure.filename,
                _KEY_EVENT_DIR: failure.event_dir,
                _KEY_REASON: failure.reason,
            }
            for failure in failures
        ],
    }

    path = state_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to persist project-handler health state to %s: %s", path, exc)


def clear_load_failures() -> None:
    """Remove the load-failure state file (idempotent when already absent)."""
    path = state_file_path()
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Failed to clear project-handler health state at %s: %s", path, exc)


def read_load_failures() -> ProjectHandlerHealthState:
    """Read the persisted health state; a missing/corrupt file reads as healthy.

    Resolves the state file via the ProjectContext singleton (the daemon path).

    Returns:
        A :class:`ProjectHandlerHealthState`. Absence of the file means the
        running daemon loaded every project handler (or has none) — healthy.
    """
    return read_load_failures_at(ProjectContext.daemon_untracked_dir())


def read_load_failures_at(untracked_dir: Path) -> ProjectHandlerHealthState:
    """Read the persisted health state from an explicit untracked directory.

    Lets callers (notably the CLI) resolve the daemon's state file
    deterministically — e.g. from a project root — without depending on the
    ProjectContext singleton being initialised for the right project.

    Args:
        untracked_dir: The daemon untracked directory to read the state from.

    Returns:
        A :class:`ProjectHandlerHealthState`; a missing/corrupt file reads as
        healthy.
    """
    path = untracked_dir / _STATE_FILENAME
    if not path.exists():
        return ProjectHandlerHealthState()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to read project-handler health state at %s: %s", path, exc)
        return ProjectHandlerHealthState()

    if not isinstance(data, dict):
        logger.warning("project-handler health state at %s is not a JSON object; ignoring", path)
        return ProjectHandlerHealthState()

    raw_failures = data.get(_KEY_FAILURES, [])
    failures = [
        ProjectHandlerLoadFailure(
            filename=str(item.get(_KEY_FILENAME, "")),
            event_dir=str(item.get(_KEY_EVENT_DIR, "")),
            reason=str(item.get(_KEY_REASON, "")),
        )
        for item in raw_failures
        if isinstance(item, dict)
    ]
    try:
        loaded_count = int(data.get(_KEY_LOADED_COUNT, 0))
    except (TypeError, ValueError) as exc:
        # Plan 00200 Task 5.5: match the visibility already given to the two
        # parse failures above (JSON decode / non-dict payload) rather than
        # silently defaulting the summary count to 0.
        logger.warning(
            "project-handler health state at %s has a malformed %s field: %s",
            path,
            _KEY_LOADED_COUNT,
            exc,
        )
        loaded_count = 0

    return ProjectHandlerHealthState(failures=failures, loaded_count=loaded_count)
