"""Shared helpers for Stage 1 (edit-time) plan QA checks.

Every edit-time check starts the same way: is this Write/Edit targeting a
``PLAN.md`` under the configured plan directory, and if so what does the
would-be content parse to? :func:`edit_target` answers that once, so each
check module stays a single focused rule.
"""

import re
from dataclasses import dataclass
from typing import Final

from claude_code_hooks_daemon.plan_qa.model import PLAN_DOC_FILENAME, PlanDoc
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level

_PLAN_FOLDER_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{1,5})-[a-zA-Z]")


@dataclass(frozen=True)
class EditTarget:
    """A PLAN.md edit resolved against the plan directory."""

    rel_path: str
    plan_number: int | None
    doc: PlanDoc
    in_archive: bool


def edit_target(context: CheckContext) -> EditTarget | None:
    """Resolve an EDIT context to a plan-document target, or ``None``.

    ``None`` means "this check does not apply": no file in the context, not
    named ``PLAN.md``, or not under the configured plan directory.
    """
    if context.file_path is None or context.file_content is None:
        return None
    if context.file_path.name != PLAN_DOC_FILENAME:
        return None
    # Outside the plan dir = "check does not apply" (a documented no-match
    # signal, not an error condition).
    if not context.file_path.is_relative_to(context.plan_dir):
        return None

    rel = context.file_path.relative_to(context.plan_dir)
    parts = rel.parts
    archive_dirs = {context.completed_dir}
    if context.cancelled_dir is not None:
        archive_dirs.add(context.cancelled_dir)
    in_archive = len(parts) > 0 and parts[0] in archive_dirs

    folder_name = parts[-2] if len(parts) >= 2 else ""
    number_match = _PLAN_FOLDER_NUMBER_RE.match(folder_name)
    plan_number = int(number_match.group(1)) if number_match else None

    rel_path = str(context.file_path.relative_to(context.project_root))
    return EditTarget(
        rel_path=rel_path,
        plan_number=plan_number,
        doc=PlanDoc.parse(context.file_content),
        in_archive=in_archive,
    )


def level_for_plan(context: CheckContext, plan_number: int | None) -> Level:
    """BLOCK for new material, ADVISE for grandfathered legacy plans.

    The ratchet only loosens for plans explicitly allowlisted in
    ``legacy_plan_allowlist`` — unknown or unnumbered material is held to
    the full standard.
    """
    if plan_number is not None and plan_number in context.legacy_plan_allowlist:
        return Level.ADVISE
    return Level.BLOCK
