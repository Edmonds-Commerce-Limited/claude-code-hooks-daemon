"""Check ``journal-entry-with-progress`` (Stage 2, advise; Plan 00163 P3).

A commit that changes a plan's ``PLAN.md`` *tasks* (ticks a checkbox, adds or
removes a task, flips a status icon) but stages no journal entry under that
plan's ``JOURNAL/`` leaves the activity log silently behind the work it should
record. This is an encouragement, not a gate: it ships ADVISE and is scoped to
plans at or above the journal grandfather threshold so the ~160 legacy plans
that never carried a ``JOURNAL/`` are never nagged.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    has_staged_journal_entry,
    journal_in_commit_scope,
    plan_number_for_folder,
    staged_plan_md_folder,
)
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts, StagedChange
from claude_code_hooks_daemon.plan_qa.model import PlanDoc
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "journal-entry-with-progress"

_ADD_STATUS: Final[str] = "A"
_MODIFY_STATUS: Final[str] = "M"
_PROGRESS_STATUSES: Final[tuple[str, ...]] = (_ADD_STATUS, _MODIFY_STATUS)


def _tasks_changed(gitfacts: GitFacts, change: StagedChange) -> bool:
    """Whether the staged PLAN.md's task counts differ from HEAD.

    A brand-new plan (no HEAD side) counts as a task change when it already
    carries checkboxes; otherwise the parsed :class:`TaskCounts` of the staged
    and HEAD documents are compared directly.
    """
    # A/M changes are always present in the index, so ``staged_file_text`` is
    # never None here; ``or ""`` keeps the parse total for the type-checker
    # without an unreachable guard branch.
    staged_text = gitfacts.staged_file_text(change.path) or ""
    staged_tasks = PlanDoc.parse(staged_text).tasks
    head_text = gitfacts.head_file_text(change.old_path or change.path)
    if head_text is None:
        return staged_tasks.total_checkboxes > 0
    return PlanDoc.parse(head_text).tasks != staged_tasks


def _run(context: CheckContext) -> list[Finding]:
    gitfacts = context.gitfacts
    if gitfacts is None:
        return []

    findings: list[Finding] = []
    for change in gitfacts.staged_changes():
        if change.status not in _PROGRESS_STATUSES:
            continue
        folder = staged_plan_md_folder(change.path, context.plan_dir_rel)
        if folder is None:
            continue
        plan_number = plan_number_for_folder(folder)
        if not journal_in_commit_scope(context, plan_number):
            continue
        if not _tasks_changed(gitfacts, change):
            continue
        if has_staged_journal_entry(context, folder):
            continue
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.ADVISE,
                message=(
                    f"Plan {plan_number:05d} changes its PLAN.md tasks in this "
                    "commit but stages no journal entry"
                ),
                remediation=(
                    f"Append a `## HH:MM · category · REF` entry to "
                    f"{folder}/{context.journal_dir_name}/ recording what changed, "
                    "and stage it in this commit."
                ),
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
