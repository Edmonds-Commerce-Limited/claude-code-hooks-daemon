"""Check ``plan-shrink-without-journal`` (Stage 2, advise; Plan 00190 Task 3.5).

Guards Hazard 1 of the size design: telling an agent "your plan is too big"
invites DELETION, when the intended move is to RELOCATE dated narrative into
the plan's ``JOURNAL/`` OR EXTRACT durable-but-current detail into a named
supporting document in the plan folder (Plan 00211). All three are easy to
tell apart at commit time — a relocation stages a journal entry, an
extraction stages a brand-new supporting doc, a deletion stages neither.

So a commit that shrinks a ``PLAN.md`` sharply while staging neither a
journal entry nor a new supporting doc under that plan is flagged. Advisory
only, and deliberately so: a genuine curation pass that drops obsolete
content is legitimate, and git retains the history either way. The point is
to make the agent *notice* which of the two (delete vs. relocate/extract) it
just did.

Before Plan 00211 this check recognised ONLY the journal-entry signal, so a
pure extraction — the field report's own restructure commit shrank PLAN.md
by 9,525 bytes while staging three brand-new supporting ``.md`` files, with
no journal entry at all — would have been misread as a deletion.

Grandfathered plans are out of scope for the same reason as the other journal
couplings — plans that never carried a ``JOURNAL/`` cannot relocate into one.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    has_staged_journal_entry,
    has_staged_supporting_doc,
    journal_in_commit_scope,
    plan_number_for_folder,
    staged_plan_md_folder,
)
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "plan-shrink-without-journal"

_MODIFY_STATUS: Final[str] = "M"

# Ordinary editing churn (rewording a task, dropping a stale bullet) removes a
# few hundred bytes. Losing this much at once is a different kind of event.
_SIGNIFICANT_SHRINK_BYTES: Final[int] = 2_000


def _run(context: CheckContext) -> list[Finding]:
    gitfacts = context.gitfacts
    if gitfacts is None:
        return []

    findings: list[Finding] = []
    for change in gitfacts.staged_changes():
        if change.status != _MODIFY_STATUS:
            continue
        folder = staged_plan_md_folder(change.path, context.plan_dir_rel)
        if folder is None:
            continue
        plan_number = plan_number_for_folder(folder)
        if not journal_in_commit_scope(context, plan_number):
            continue

        head_text = gitfacts.head_file_text(change.old_path or change.path)
        if head_text is None:
            continue
        staged_text = gitfacts.staged_file_text(change.path) or ""
        lost_bytes = len(head_text) - len(staged_text)
        if lost_bytes < _SIGNIFICANT_SHRINK_BYTES:
            continue
        if has_staged_journal_entry(context, folder) or has_staged_supporting_doc(context, folder):
            continue

        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.ADVISE,
                message=(
                    f"Plan {plan_number:05d} loses {lost_bytes:,} bytes from its "
                    "PLAN.md in this commit but stages no journal entry and no new "
                    "supporting document — content may have been DELETED rather "
                    "than relocated or extracted"
                ),
                remediation=(
                    "If that content was dated narrative — progress notes, "
                    "incident write-ups, hand-off prose — it belongs in "
                    f"{folder}/{context.journal_dir_name}/, which is append-only and "
                    "unbounded by design; append it there and stage it in this "
                    "commit. If it was durable-but-current detail — research "
                    "output, findings, decisions and their reasoning, evidence "
                    f"tables — EXTRACT it into a named supporting document in "
                    f"{folder}/ instead and stage it in this commit. If the "
                    "content is genuinely obsolete, this is fine as it stands: "
                    "git keeps the history."
                ),
                path=change.path,
            )
        )
    return findings


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.COMMIT,
    level=Level.ADVISE,
    # Post-audit category (Plan 00190), like the journal checks.
    sins=(),
    run=_run,
)
