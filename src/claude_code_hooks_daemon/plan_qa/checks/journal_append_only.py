"""Check ``journal-append-only`` (Stage 1, advise; Plan 00163).

A journal day-file is an append-only log: an edit must only ADD to the end.
The check compares the pre-edit on-disk content (``file_content_before``,
threaded by ``plan_qa_edit``) with the would-be content on a
trailing-newline-normalised prefix test:

- new file (no ``file_content_before``) → creation, clean
- ``after`` starts with ``before`` → pure append, clean
- ``after`` is shorter than ``before`` → truncation advisory
- otherwise → earlier-history rewrite advisory

Advisory FOREVER (Decision 4): a same-day typo fix is a legitimate non-append,
and a false block on someone's log is worse than a missed nudge. ``mode:
block`` never escalates this check.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import journal_edit_target
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "journal-append-only"

_REMEDIATION: Final[str] = (
    "Journals are append-only and unbounded by design — length is never a problem, "
    "so do not tidy or trim one. Add a NEW dated entry at the bottom instead of "
    "editing or removing earlier ones. Corrections are new entries, never rewrites."
)

_NEWLINE: Final[str] = "\n"


def _run(context: CheckContext) -> list[Finding]:
    target = journal_edit_target(context)
    if target is None:
        return []

    before = context.file_content_before
    if before is None or context.file_content is None:
        # Creation (or no would-be content) — nothing earlier to preserve.
        return []

    before_body = before.rstrip(_NEWLINE)
    after_body = context.file_content.rstrip(_NEWLINE)
    if after_body.startswith(before_body):
        return []

    if len(after_body) < len(before_body):
        detail = "shrinks the journal — earlier entries were removed"
    else:
        detail = "rewrites earlier journal history"
    return [
        Finding(
            check_id=CHECK_ID,
            level=Level.ADVISE,
            message=f"Edit to `{target.rel_path}` {detail}",
            remediation=_REMEDIATION,
            path=target.rel_path,
        )
    ]


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.EDIT,
    level=Level.ADVISE,
    sins=(),
    run=_run,
)
