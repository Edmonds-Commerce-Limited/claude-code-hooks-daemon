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
        Path(file_path).resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return True


def matched_plan_write_or_edit(
    hook_input: dict[str, Any], project_layout: ProjectLayout | None
) -> tuple[str, str] | None:
    """``(file_path, folder)`` when ``hook_input`` is a Write/Edit landing on
    an active plan's PLAN.md; ``None`` otherwise. ``folder`` is the
    ``<digits>-<name>`` capture group.
    """
    if hook_input.get(HookInputField.TOOL_NAME) not in (ToolName.WRITE, ToolName.EDIT):
        return None
    file_path = get_file_path(hook_input) or ""
    normalized = file_path.replace("\\", "/")
    if COMPLETED_SEGMENT in normalized:
        return None
    match = plan_path_pattern(plan_dir_for(project_layout)).search(normalized)
    if match is None:
        return None
    if not is_inside_project(file_path):
        return None
    return file_path, match.group(1)
