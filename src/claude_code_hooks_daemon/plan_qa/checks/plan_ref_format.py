"""Check ``plan-ref-format`` (Stage 2, advise; sin G3).

A commit that touches the plan directory should reference its plan using the
canonical ``Plan NNNNN`` form (zero-padded, capitalised) so plan references
stay greppable across the whole repository history.
"""

import re
from typing import Final

from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "plan-ref-format"

_CANONICAL_REF_RE: Final[re.Pattern[str]] = re.compile(r"Plan \d{5}")

_REMEDIATION: Final[str] = (
    "Reference the plan as `Plan NNNNN:` (zero-padded, capitalised) for " "greppable traceability."
)


def _run(context: CheckContext) -> list[Finding]:
    if context.commit_message is None or context.gitfacts is None:
        return []

    prefix = context.plan_dir_rel.rstrip("/") + "/"
    touches_plan_dir = any(
        change.path.startswith(prefix) for change in context.gitfacts.staged_changes()
    )
    if not touches_plan_dir:
        return []

    if _CANONICAL_REF_RE.search(context.commit_message):
        return []

    return [
        Finding(
            check_id=CHECK_ID,
            level=Level.ADVISE,
            message="Commit touches the plan directory without a canonical `Plan NNNNN` reference",
            remediation=_REMEDIATION,
        )
    ]


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.COMMIT,
    level=Level.ADVISE,
    sins=("G3",),
    run=_run,
)
