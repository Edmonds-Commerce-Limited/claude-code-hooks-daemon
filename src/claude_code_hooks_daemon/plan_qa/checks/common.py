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

_MARKDOWN_SUFFIX: Final[str] = ".md"

# Journal mode tokens (mirror PlanWorkflowQaJournalConfig.mode).
_JOURNAL_MODE_OFF: Final[str] = "off"
_JOURNAL_MODE_BLOCK: Final[str] = "block"


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


@dataclass(frozen=True)
class JournalEditTarget:
    """A journal day-file edit resolved against the plan directory."""

    rel_path: str
    plan_number: int | None
    basename: str


def journal_edit_target(context: CheckContext) -> JournalEditTarget | None:
    """Resolve an EDIT context to a journal day-file target, or ``None``.

    ``None`` means "this check does not apply": no file in the context, the
    file is not a ``.md`` directly inside a ``{journal_dir_name}/`` directory,
    or that directory is not inside a ``NNNNN-*`` plan folder under the plan
    directory. Journalling being disabled (``journal_enabled`` false or
    ``journal_mode == "off"``) is also a documented no-match.
    """
    if context.file_path is None or context.file_content is None:
        return None
    if not context.journal_enabled or context.journal_mode == _JOURNAL_MODE_OFF:
        return None
    if context.file_path.suffix != _MARKDOWN_SUFFIX:
        return None
    if not context.file_path.is_relative_to(context.plan_dir):
        return None

    # Layout: <plan_dir>/[archive/]NNNNN-name/<journal_dir_name>/<file>.md — the
    # file's parent must be the journal dir, and its grandparent the plan folder.
    parent = context.file_path.parent
    if parent.name != context.journal_dir_name:
        return None
    folder_match = _PLAN_FOLDER_NUMBER_RE.match(parent.parent.name)
    plan_number = int(folder_match.group(1)) if folder_match else None

    rel_path = str(context.file_path.relative_to(context.project_root))
    return JournalEditTarget(
        rel_path=rel_path,
        plan_number=plan_number,
        basename=context.file_path.name,
    )


def journal_level(context: CheckContext) -> Level:
    """BLOCK only when journal enforcement has been ratcheted to ``block``.

    Journalling ships advise-first (Plan 00163 Decision 4); only the
    naming check may ever honour ``mode: block``.
    """
    return Level.BLOCK if context.journal_mode == _JOURNAL_MODE_BLOCK else Level.ADVISE


def journalling_active(context: CheckContext) -> bool:
    """Whether journal checks should run at all under the current policy."""
    return context.journal_enabled and context.journal_mode != _JOURNAL_MODE_OFF
