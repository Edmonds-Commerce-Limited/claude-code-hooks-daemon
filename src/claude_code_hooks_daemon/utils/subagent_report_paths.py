"""Shared subagent report persistence primitives (Plan 00460 Task 1.6).

The daemon persists EVERY sub-agent's ``last_assistant_message`` to a
gitignored, bounded location at SubagentStop, regardless of agent type or
``Write`` access -- the owner's own question ("is there a hook we can use
... to ensure sub agent reports are persisted to file?") answered at the
daemon level rather than depending on per-agent cooperation. Saving to a
gitignored path (``untracked/``, confirmed at this repository's own
``.gitignore``) discloses nothing new to git, so none of the Write-time
content checks (sensitive-content, secret-file, markdown-location) that
ruled out an EARLIER, tracked-destination version of this idea (Task 1.2)
apply here.

Two handlers share these primitives without any cross-handler in-memory
coupling (no precedent for that anywhere in this codebase, and a
timestamp computed twice in the same dispatch can straddle a second
boundary regardless): ``subagent_report_persistence`` (SubagentStop,
priority 10) WRITES using :func:`write_new_file_never_overwrite`;
``subagent_report_size_blocker`` (SubagentStop, priority 15) LOOKS UP
what was already saved using :func:`find_persisted_report`, which globs
by agent type/id rather than trusting an exact filename match.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

#: Fallback location for every persisted report. Configurable per handler
#: via ``options.report_dir`` -- if a project changes one, change the
#: other, or the size blocker's glob lookup and the persister's write
#: target diverge (a safe degradation: the lookup just finds nothing and
#: the size blocker falls back to its pre-Task-1.6 message).
DEFAULT_REPORT_DIR: Final[str] = "untracked/agent-reports/"

_PLACEHOLDER_AGENT_TYPE: Final[str] = "unknown-agent-type"
_PLACEHOLDER_AGENT_ID: Final[str] = "unknown-agent-id"

#: Characters kept as-is in a filename component; everything else (path
#: separators, colons in a plugin-scoped agent type like
#: ``my-plugin:review:security``, whitespace) becomes an underscore.
_SAFE_COMPONENT_RE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]")

_FILENAME_TIMESTAMP_FORMAT: Final[str] = "%y%m%d-%H%M%S"
_MD_SUFFIX: Final[str] = ".md"

#: How many numeric-suffix attempts :func:`write_new_file_never_overwrite`
#: makes before giving up. A real collision (two SubagentStops for the
#: same agent_id in the same wall-clock second) is already a rare edge
#: case; this many attempts exhausting is rarer still and logged, not
#: silently dropped.
_MAX_COLLISION_ATTEMPTS: Final[int] = 20

_FILE_MODE: Final[int] = 0o644


def _sanitise(value: str) -> str:
    """A filesystem-safe filename component, or ``""`` for an empty input."""
    return _SAFE_COMPONENT_RE.sub("_", value)


def report_filename(agent_type: str, agent_id: str, *, when: datetime) -> str:
    """``<yymmdd>-<HHMMSS>-<agent_type>-<agent_id>.md``, filesystem-safe.

    An empty ``agent_type``/``agent_id`` (SubagentStop's contract treats
    both as unconditional, but a caller should never trust that blindly)
    renders a documented placeholder rather than an ugly double-hyphen.
    """
    stamp = when.strftime(_FILENAME_TIMESTAMP_FORMAT)
    safe_type = _sanitise(agent_type) or _PLACEHOLDER_AGENT_TYPE
    safe_id = _sanitise(agent_id) or _PLACEHOLDER_AGENT_ID
    return f"{stamp}-{safe_type}-{safe_id}{_MD_SUFFIX}"


def _candidate_path(directory: Path, filename: str, attempt: int) -> Path:
    """``filename`` unchanged on the first attempt, else ``-N`` before the suffix."""
    if attempt == 0:
        return directory / filename
    stem = filename[: -len(_MD_SUFFIX)] if filename.endswith(_MD_SUFFIX) else filename
    return directory / f"{stem}-{attempt + 1}{_MD_SUFFIX}"


def write_new_file_never_overwrite(
    directory: Path, filename: str, content: str, *, max_attempts: int = _MAX_COLLISION_ATTEMPTS
) -> Path | None:
    """Atomically create a NEW file under ``directory``, never overwriting.

    Uses ``O_CREAT | O_EXCL`` -- atomic at the OS level, so two daemon
    threads racing to create the same path can never both succeed against
    the same name. A collision (the path already exists) retries with a
    ``-2``, ``-3``, ... numeric suffix before the ``.md`` extension, up to
    ``max_attempts``.

    Returns the path actually written, or ``None`` on any failure
    (directory could not be created, every attempt collided, or an
    ``OSError`` writing the content) -- logged, never raised. The caller
    is a SubagentStop sensor: persistence failing must never block a
    stopping agent.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("subagent_report_paths: cannot create %s: %s", directory, exc)
        return None

    for attempt in range(max_attempts):
        candidate = _candidate_path(directory, filename, attempt)
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, _FILE_MODE)
        except FileExistsError:
            continue
        except OSError as exc:
            logger.warning("subagent_report_paths: cannot create %s: %s", candidate, exc)
            return None
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(content)
        except OSError as exc:
            logger.warning("subagent_report_paths: cannot write %s: %s", candidate, exc)
            return None
        return candidate

    logger.warning(
        "subagent_report_paths: exhausted %d collision suffixes for %s in %s",
        max_attempts,
        filename,
        directory,
    )
    return None


def find_persisted_report(directory: Path, agent_type: str, agent_id: str) -> Path | None:
    """The most recently persisted report for ``agent_type``/``agent_id``, or None.

    Globs by agent type/id rather than reconstructing an exact filename:
    the persister and a caller of this function each compute their own
    timestamp, which can straddle a second boundary within the same
    dispatch, and a collision-suffixed filename would not match an exact
    reconstruction either. An empty ``agent_id`` (SubagentStop is
    documented to always carry one, but this must not trust that blindly)
    matches nothing, since the persister's own placeholder-substitution
    would otherwise make every "unknown agent" report look like a match
    for every other.

    "Most recent" is decided lexicographically: the filename's leading
    ``yymmdd-HHMMSS`` stamp sorts chronologically as a string, so the
    lexicographically-last match is also the newest.
    """
    if not agent_id:
        return None
    if not directory.is_dir():
        return None
    safe_type = _sanitise(agent_type) or _PLACEHOLDER_AGENT_TYPE
    safe_id = _sanitise(agent_id)
    pattern = f"*-{safe_type}-{safe_id}*{_MD_SUFFIX}"
    try:
        matches = sorted(directory.glob(pattern))
    except OSError as exc:
        logger.debug("subagent_report_paths: cannot glob %s: %s", directory, exc)
        return None
    return matches[-1] if matches else None
