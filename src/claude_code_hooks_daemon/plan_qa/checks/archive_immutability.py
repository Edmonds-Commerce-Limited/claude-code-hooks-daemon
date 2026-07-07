"""Check ``archive-immutability`` (Stage 1, advise; sin A5).

Archived plans are historical record: editing one rewrites what actually
happened. This is advisory-only because deliberate corrections (a wrong
status header, a typo) are legitimate — the check just asks the author to
confirm the edit is intentional rather than an accidental drive-by change.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import edit_target
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "archive-immutability"

_REMEDIATION: Final[str] = (
    "Confirm this is a deliberate correction (e.g. a status header fix); "
    "otherwise leave archived plans untouched."
)


def _run(context: CheckContext) -> list[Finding]:
    target = edit_target(context)
    if target is None or not target.in_archive or context.file_exists_before is not True:
        return []

    return [
        Finding(
            check_id=CHECK_ID,
            level=Level.ADVISE,
            message="Editing an archived PLAN.md rewrites project history",
            remediation=_REMEDIATION,
            path=target.rel_path,
        )
    ]


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.EDIT,
    level=Level.ADVISE,
    sins=("A5",),
    run=_run,
)
