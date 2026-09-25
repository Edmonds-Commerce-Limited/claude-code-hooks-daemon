"""Shared PLAN.md Write/Edit trigger matching (Plan 00466 RV3-n5).

Two handlers need to agree on exactly what counts as "a Write/Edit landing
on an active plan's PLAN.md": ``goal_injection`` (PostToolUse) reads the
post-write status; ``plan_status_snapshot`` (PreToolUse) records the
pre-write one for the SAME tool call, keyed by ``tool_use_id``. If each
implemented its own copy of this matching logic, the two could silently
drift apart over time -- a snapshot recorded for one definition of "the
trigger" consumed against a different one would break the Pre/Post pairing
RV3-n5 depends on. This module is the single shared implementation; both
handlers call into it (``GoalInjectionHandler`` keeps its own
``_plan_dir``/``_plan_path_pattern``/``_is_inside_project`` methods as thin
delegating wrappers for compatibility).
"""

import logging
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.core.utils import get_file_path

logger = logging.getLogger(__name__)

FALLBACK_PLAN_DIR: Final[str] = "CLAUDE/Plan"
COMPLETED_SEGMENT: Final[str] = "/Completed/"

#: RV8-n4: a symlinked/aliased PLAN.md that resolves outside the trigger
#: pattern logs a WARNING -- but `matched_plan_write_or_edit` runs once at
#: PreToolUse (`plan_status_snapshot`) and once at PostToolUse
#: (`goal_injection`) for the SAME tool call, so an unfixed alias would log
#: it twice per call, forever. Bounded FIFO of paths already warned about,
#: so a long-lived daemon does not grow this without limit; guarded by a
#: lock because dispatch runs on a thread pool.
_WARNED_UNRESOLVED_PATHS: Final[OrderedDict[str, None]] = OrderedDict()
_WARN_LOCK: Final[threading.Lock] = threading.Lock()
_MAX_WARNED_UNRESOLVED_PATHS: Final[int] = 256


def reset_warned_unresolved_paths() -> None:
    """Drop every remembered path. For tests, and a deliberate reload."""
    with _WARN_LOCK:
        _WARNED_UNRESOLVED_PATHS.clear()


def _warn_unresolved_once(file_path: str, unresolved_folder: str) -> None:
    """Log the "resolves outside the pattern" WARNING at most once per
    ``file_path`` -- see :data:`_WARNED_UNRESOLVED_PATHS`."""
    with _WARN_LOCK:
        if file_path in _WARNED_UNRESOLVED_PATHS:
            return
        _WARNED_UNRESOLVED_PATHS[file_path] = None
        if len(_WARNED_UNRESOLVED_PATHS) > _MAX_WARNED_UNRESOLVED_PATHS:
            _WARNED_UNRESOLVED_PATHS.popitem(last=False)
    logger.warning(
        "plan_trigger: %r resolves to a path outside the plan pattern "
        "(unresolved capture was %r) -- treating as unmatched rather "
        "than ledgering it under an alias that cannot retire",
        file_path,
        unresolved_folder,
    )


class PlanUnreadable(Exception):
    """Raised when a plan's PLAN.md exists but cannot be read or decoded.

    Shared by ``goal_injection._read_plan`` (post-write) and
    ``plan_status_snapshot._read_plan`` (pre-write) -- both read the SAME
    kind of file for the SAME reason (advisory sensing for a hook handler
    that must never raise out of its own dispatch), so both raise this ONE
    domain exception rather than each inventing its own. Each caller
    catches it explicitly, logs a WARNING naming the path and cause, and
    takes its own documented fail-open branch -- never a bare
    ``return None`` inside the except itself.
    """


def plan_dir_for(project_layout: ProjectLayout | None) -> str:
    """Configured plan directory (facade, or the matching default)."""
    return project_layout.plan_dir if project_layout is not None else FALLBACK_PLAN_DIR


def plan_path_pattern(plan_dir: str) -> re.Pattern[str]:
    """Compile the trigger pattern for ``plan_dir``.

    Matches ``<plan_dir>/<digits>-<name>/PLAN.md`` (the ``/Completed/``
    exclusion is checked separately by callers via ``COMPLETED_SEGMENT``).
    """
    return re.compile(rf"{re.escape(plan_dir)}/(\d+-[^/]+)/PLAN\.md$")


def is_inside_project(file_path: str) -> bool:
    """True when ``file_path`` lives under this project's root.

    The trigger pattern is applied with ``search``, so any path merely
    CONTAINING ``<plan_dir>/NNNNN-name/PLAN.md`` matches wherever it lives.
    Fails OPEN -- an unresolvable path or uninitialised context keeps the
    pre-existing behaviour rather than silently disabling the trigger.
    """
    try:
        root = ProjectContext.project_root().resolve()
    except (RuntimeError, OSError) as e:
        logger.warning("plan_trigger: project-root check skipped: %s", e)
        return True
    try:
        # RV4-n7: a symlink-loop PLAN.md makes resolve() raise RuntimeError
        # (Python's own maximum-recursion / ELOOP detection), not OSError --
        # caught here alongside (ValueError, OSError) so it reads as "not
        # inside" rather than escaping raw.
        Path(file_path).resolve().relative_to(root)
    except (ValueError, OSError, RuntimeError):
        return False
    return True


def matched_plan_write_or_edit(
    hook_input: dict[str, Any], project_layout: ProjectLayout | None
) -> tuple[str, str] | None:
    """``(file_path, folder)`` when ``hook_input`` is a Write/Edit landing on
    an active plan's PLAN.md; ``None`` otherwise. ``folder`` is the
    ``<digits>-<name>`` capture group.

    RV7-m3: ``folder`` is the capture from the RESOLVED path, not the raw
    ``file_path`` text -- a plan folder reached through a symlinked alias
    (``CLAUDE/Plan/00301-l -> 00300-c``) must ledger under the TARGET's
    number, the one that actually retires when the plan completes, never
    the link's. Once ``is_inside_project`` confirms containment (which
    already resolves the same path to check it), the pattern is re-applied
    to that SAME resolved path, expressed relative to the resolved project
    root, and that capture wins over the unresolved one.
    """
    if hook_input.get(HookInputField.TOOL_NAME) not in (ToolName.WRITE, ToolName.EDIT):
        return None
    file_path = get_file_path(hook_input) or ""
    normalized = file_path.replace("\\", "/")
    if COMPLETED_SEGMENT in normalized:
        return None
    pattern = plan_path_pattern(plan_dir_for(project_layout))
    match = pattern.search(normalized)
    if match is None:
        return None
    if not is_inside_project(file_path):
        return None
    resolved_folder = _resolved_folder_capture(
        file_path, pattern, unresolved_folder=match.group(1)
    )
    if resolved_folder is None:
        _warn_unresolved_once(file_path, match.group(1))
        return None
    return file_path, resolved_folder


def _resolved_folder_capture(
    file_path: str, pattern: re.Pattern[str], *, unresolved_folder: str
) -> str | None:
    """Re-apply ``pattern`` to ``file_path`` fully resolved (symlinks
    followed) and expressed relative to the resolved project root.

    Returns ``unresolved_folder`` -- the caller's own already-matched
    capture -- when the root or the path itself cannot be resolved: an
    unresolvable ROOT is a project-setup problem the caller already fails
    open for via ``is_inside_project``, so this must not manufacture a
    false negative on top of that. Returns ``None`` only when the resolved
    path no longer matches ``pattern`` at all -- a real containment edge
    case, not a resolution failure -- which the caller logs and treats as
    unmatched.
    """
    try:
        root = ProjectContext.project_root().resolve()
    except (RuntimeError, OSError):
        return unresolved_folder
    try:
        relative = Path(file_path).resolve().relative_to(root).as_posix()
    except (ValueError, OSError, RuntimeError):
        return unresolved_folder
    resolved_match = pattern.search(relative)
    return resolved_match.group(1) if resolved_match is not None else None
