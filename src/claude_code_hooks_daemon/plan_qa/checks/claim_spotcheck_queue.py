"""Check ``claim-spotcheck-queue`` (Stage 3, advise; sin B3).

Active-section README rows sometimes carry status text that is only true at
the instant it was written — "PR #42 open", "awaiting merge", "in review".
Nothing re-checks these once written, so the index drifts silently once the
PR actually merges. This check queues each volatile claim for a spot-check.
"""

import re
from typing import Final

from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeSection
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "claim-spotcheck-queue"

_PR_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"PR\s*#\d+", re.IGNORECASE)
_PR_STATE_WORD_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:open|draft|awaiting)\b", re.IGNORECASE
)
_OTHER_VOLATILE_RE: Final[re.Pattern[str]] = re.compile(
    r"awaiting\s+merge|in\s+review|awaiting\s+approval", re.IGNORECASE
)

_REMEDIATION: Final[str] = (
    "Spot-check each listed claim against reality (the PR may have merged "
    "or the review may have concluded) and refresh the row."
)


def _is_volatile_claim(status_text: str) -> bool:
    if _PR_NUMBER_RE.search(status_text) and _PR_STATE_WORD_RE.search(status_text):
        return True
    return bool(_OTHER_VOLATILE_RE.search(status_text))


def _run(context: CheckContext) -> list[Finding]:
    if context.readme is None:
        return []

    matches = [
        row
        for row in context.readme.rows
        if row.section == ReadmeSection.ACTIVE
        and row.status_text is not None
        and _is_volatile_claim(row.status_text)
    ]
    if not matches:
        return []

    lines = [
        f"- {'/'.join(f'{number:05d}' for number in row.numbers)}: {row.status_text}"
        for row in matches
    ]
    message = "Volatile status claims due for a spot-check:\n" + "\n".join(lines)

    return [
        Finding(
            check_id=CHECK_ID,
            level=Level.ADVISE,
            message=message,
            remediation=_REMEDIATION,
            path=None,
        )
    ]


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.SWEEP,
    level=Level.ADVISE,
    sins=("B3",),
    run=_run,
)
