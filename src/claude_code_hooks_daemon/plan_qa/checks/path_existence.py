"""Check ``path-existence`` (Stage 1 + 3, advise; sin E5).

Plans routinely name real repository paths for reviewer orientation. When
those paths are renamed or removed by a later refactor, the plan silently
goes stale. This check scans inline-code spans that look like project
paths (``src/``, ``tests/``, ``config/``) and advises when they no longer
exist on disk. Archived plans are exempt: history is allowed to reference
paths that have since moved.

Registered at EDIT *and* SWEEP (Plan 00230). This rule rots by construction —
a plan goes stale when OTHER files move, not when the plan is edited — so a
write-time-only registration could only ever catch it by coincidence.
"""

import re
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    DocumentRuleChecks,
    DocumentTarget,
    document_rule_checks,
)
from claude_code_hooks_daemon.plan_qa.model import PlanStatus, lines_outside_fences
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    Finding,
    Level,
)

CHECK_ID: Final[str] = "path-existence"

# A plan whose work has not begun names the files it INTENDS to create, so
# "does not exist" is the expected state rather than drift. Every finding on
# this repo's first whole-tree scan was a plan in one of these states.
_WORK_NOT_BEGUN_STATUSES: Final[frozenset[PlanStatus]] = frozenset(
    {PlanStatus.NOT_STARTED, PlanStatus.BLOCKED, PlanStatus.DORMANT}
)

_INLINE_CODE_RE: Final[re.Pattern[str]] = re.compile(r"`([^`\n]+)`")
_PROJECT_PATH_RE: Final[re.Pattern[str]] = re.compile(r"^(?:src/|tests/|config/)[A-Za-z0-9_./-]+$")
_MAX_REPORTED_PATHS: Final[int] = 10


def _rule(context: CheckContext, target: DocumentTarget) -> list[Finding]:
    if target.in_archive or target.doc.status in _WORK_NOT_BEGUN_STATUSES:
        return []

    missing: list[str] = []
    for line in lines_outside_fences(target.text):
        for span in _INLINE_CODE_RE.findall(line):
            if not _PROJECT_PATH_RE.match(span):
                continue
            if span in missing:
                continue
            if not (context.project_root / span).exists():
                missing.append(span)

    if not missing:
        return []

    reported = missing[:_MAX_REPORTED_PATHS]
    return [
        Finding(
            check_id=CHECK_ID,
            level=Level.ADVISE,
            message=f"PLAN.md references path(s) that do not exist: {', '.join(reported)}",
            remediation="Update the plan to reference the current paths, or note the refactor.",
            path=target.rel_path,
        )
    ]


CHECKS: Final[DocumentRuleChecks] = document_rule_checks(
    check_id=CHECK_ID,
    level=Level.ADVISE,
    sins=("E5",),
    rule=_rule,
)
