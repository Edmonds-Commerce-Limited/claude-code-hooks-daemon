"""Check ``journal-completion-entry`` (Stage 2, advise; Plan 00163 P3).

A commit that flips a plan to a terminal status (Complete, Cancelled,
Superseded) without staging a closing journal entry loses the single most
valuable hand-off datapoint: why the plan ended and what a future agent should
know. This coupling is OPT-IN — it fires only when
``plan_workflow.qa.journal.enforce_on_completion`` is true — and always ADVISE.

Detecting a *real* closing entry is subtler than a presence test: completing a
plan ``git mv``\\s the whole folder into the archive, so the existing day-files
ride along as renames. :func:`has_staged_journal_entry` therefore only counts
an Added file, a Modified file, or a rename whose content actually grew.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    has_staged_journal_entry,
    journal_in_commit_scope,
    plan_number_for_folder,
    staged_plan_md_folder,
)
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts, StagedChange
from claude_code_hooks_daemon.plan_qa.model import (
    JOURNAL_BODY_FILE_HINT,
    PlanDoc,
    journal_append_command,
)
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "journal-completion-entry"

_CLOSING_CATEGORY: Final[str] = "handoff"


def _is_terminal_flip(gitfacts: GitFacts, change: StagedChange) -> bool:
    """Whether the staged PLAN.md flips to terminal from a non-terminal HEAD."""
    staged_text = gitfacts.staged_file_text(change.path)
    if staged_text is None:
        return False
    if not PlanDoc.parse(staged_text).is_terminal:
        return False
    head_text = gitfacts.head_file_text(change.old_path or change.path)
    return head_text is None or not PlanDoc.parse(head_text).is_terminal


def _remediation(plan_dir: str, plan_number: int | None) -> str:
    command = journal_append_command(plan_dir, plan_number, _CLOSING_CATEGORY)
    return (
        f"Append a closing entry (why it ended, hand-off state) with `{command}` "
        f"({JOURNAL_BODY_FILE_HINT}), and stage the day-file in this commit."
    )


def _run(context: CheckContext) -> list[Finding]:
    if not context.journal_enforce_on_completion:
        return []
    gitfacts = context.gitfacts
    if gitfacts is None:
        return []

    findings: list[Finding] = []
    for change in gitfacts.staged_changes():
        folder = staged_plan_md_folder(change.path, context.plan_dir_rel)
        if folder is None:
            continue
        plan_number = plan_number_for_folder(folder)
        if not journal_in_commit_scope(context, plan_number):
            continue
        if not _is_terminal_flip(gitfacts, change):
            continue
        if has_staged_journal_entry(context, folder):
            continue
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.ADVISE,
                message=(
                    f"Plan {plan_number:05d} flips to a terminal status in this "
                    "commit but stages no closing journal entry"
                ),
                remediation=_remediation(context.plan_dir_rel, plan_number),
                path=change.path,
            )
        )
    return findings


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.COMMIT,
    level=Level.ADVISE,
    sins=(),
    run=_run,
)
