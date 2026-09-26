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

#: The shared, human/agent-facing non-plan-work destination (dispatch
#: declaration fallback, PlanWorkflow's own template). NOT where the
#: persister writes -- see :data:`DEFAULT_PERSISTED_REPORT_DIR` below
#: (review finding B2: retention pruning this directory once deleted
#: deliberately-authored reports living alongside the daemon's own).
DEFAULT_REPORT_DIR: Final[str] = "untracked/agent-reports/"

#: Where :func:`write_new_file_never_overwrite` actually persists every
#: reply, and the only directory retention (`prune_directory`) is ever
#: pointed at. A dedicated subdirectory of :data:`DEFAULT_REPORT_DIR` that
#: ONLY the daemon writes into, so pruning can never touch a hand-authored
#: report living in the parent directory. Configurable per handler via
#: ``options.report_dir``/``options.persisted_report_dir`` -- if a project
#: changes one, change the other, or the size blocker's glob lookup and the
#: persister's write target diverge (a safe degradation: the lookup just
#: finds nothing and the size blocker falls back to its pre-Task-1.6
#: message).
DEFAULT_PERSISTED_REPORT_DIR: Final[str] = f"{DEFAULT_REPORT_DIR}auto/"

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

#: Owner-only (review m8): a persisted reply can carry sensitive material a
#: sub-agent quoted from the codebase it was reading, matching the 0600
#: convention `retention.cap_log_file` already preserves and the
#: hand-authored reports already in this tree use.
_FILE_MODE: Final[int] = 0o600
_DIR_MODE: Final[int] = 0o700

_GITIGNORE_FILENAME: Final[str] = ".gitignore"
#: Review B1: the only prior evidence a persisted reply's directory was
#: gitignored was a test against THIS repo's `.gitignore` -- nothing
#: enforced it at runtime, so a client project with no matching rule could
#: `git add -A` unvetted reply content straight into a commit. A
#: self-ignoring directory (Git's own documented idiom: a `.gitignore`
#: containing `*`) makes the guarantee travel WITH the directory, in every
#: project, rather than depending on what that project's own ignore rules
#: happen to say.
_GITIGNORE_CONTENT: Final[str] = "*\n"


def sanitise_component(value: str) -> str:
    """A filesystem-safe filename component, or ``""`` for an empty input.

    Public because a report path this module does not write must still name
    an agent the same way: ``subagent_report_size_blocker`` prescribes a
    fallback path from the same agent type (Plan 00468 G12).
    """
    return _SAFE_COMPONENT_RE.sub("_", value)


def _ensure_self_ignoring(directory: Path) -> None:
    """Write a ``*`` ``.gitignore`` into ``directory`` if it has none yet.

    Best-effort and idempotent: an existing ``.gitignore`` (a project's own,
    or one this function wrote on an earlier call) is left untouched, and a
    write failure is logged, never raised -- the caller is a SubagentStop
    sensor (review B1's guarantee is a defence in depth, not the only line
    of defence: a project should still gitignore ``untracked/`` itself).
    """
    gitignore_path = directory / _GITIGNORE_FILENAME
    if gitignore_path.exists():
        return
    try:
        gitignore_path.write_text(_GITIGNORE_CONTENT)
    except OSError as exc:
        logger.warning("subagent_report_paths: cannot write %s: %s", gitignore_path, exc)


def resolve_confined_report_dir(root: Path, report_dir: str) -> Path | None:
    """``root / report_dir``, resolved, or ``None`` when unsafe.

    Review M1: ``report_dir`` arrives from YAML by blind ``setattr``, so an
    empty string, ``"."``, an absolute path or a ``..``-escaping path are
    all real runtime possibilities, not just theoretical -- and each one
    would make the persister write, and retention PRUNE, somewhere far
    wider than intended (probes P2/P3 in the review: an empty value made
    ``README.md`` a pruning candidate; an absolute value wrote outside the
    project root entirely). Rejects: empty, ``"."``/``"./"``, an absolute
    path, any path containing a ``..`` segment, and a path that resolves to
    the root itself or escapes it. Returns ``None`` for all of those --
    callers must skip persistence entirely rather than guess a safer
    target.
    """
    if not report_dir or report_dir in (".", "./"):
        return None
    candidate = Path(report_dir)
    if candidate.is_absolute():
        return None
    if ".." in candidate.parts:
        return None
    resolved_root = root.resolve()
    resolved_target = (root / candidate).resolve()
    if resolved_target == resolved_root:
        return None
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved_target


def report_filename(agent_type: str, agent_id: str, *, when: datetime) -> str:
    """``<yymmdd>-<HHMMSS>-<agent_type>-<agent_id>.md``, filesystem-safe.

    An empty ``agent_type``/``agent_id`` (SubagentStop's contract treats
    both as unconditional, but a caller should never trust that blindly)
    renders a documented placeholder rather than an ugly double-hyphen.
    """
    stamp = when.strftime(_FILENAME_TIMESTAMP_FORMAT)
    safe_type = sanitise_component(agent_type) or _PLACEHOLDER_AGENT_TYPE
    safe_id = sanitise_component(agent_id) or _PLACEHOLDER_AGENT_ID
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
        directory.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
    except OSError as exc:
        logger.warning("subagent_report_paths: cannot create %s: %s", directory, exc)
        return None
    _ensure_self_ignoring(directory)

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
            # Review m3: O_CREAT already created the file before the write
            # failed -- an empty/truncated file left behind would later be
            # cited by find_persisted_report (m2) and count against
            # retention as though it were a complete reply.
            try:
                candidate.unlink(missing_ok=True)
            except OSError as unlink_exc:
                logger.warning(
                    "subagent_report_paths: cannot remove partial write %s: %s",
                    candidate,
                    unlink_exc,
                )
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

    "Most recent" is decided by file modification time, tie-broken by name
    for determinism. NOT lexicographic filename order (review m1): ``-``
    (0x2d) sorts before ``.`` (0x2e), so a plain string sort puts a
    collision-suffixed ``...-2.md`` BEFORE the unsuffixed original -- exactly
    backwards, since the suffixed file is always the newer of the two a
    collision produced. The same ordering bug also puts ``-10`` before
    ``-2``.
    """
    if not agent_id:
        return None
    if not directory.is_dir():
        return None
    safe_type = sanitise_component(agent_type) or _PLACEHOLDER_AGENT_TYPE
    safe_id = sanitise_component(agent_id)
    pattern = f"*-{safe_type}-{safe_id}*{_MD_SUFFIX}"
    try:
        matches = list(directory.glob(pattern))
    except OSError as exc:
        logger.debug("subagent_report_paths: cannot glob %s: %s", directory, exc)
        return None
    if not matches:
        return None
    try:
        return max(matches, key=lambda path: (path.stat().st_mtime, path.name))
    except OSError as exc:
        logger.debug("subagent_report_paths: cannot stat matches in %s: %s", directory, exc)
        return None
