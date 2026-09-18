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

from claude_code_hooks_daemon.core.project_layout import main_repo_code_dirs
from claude_code_hooks_daemon.plan_qa.checks.common import (
    DocumentRuleChecks,
    DocumentTarget,
    document_rule_checks,
)
from claude_code_hooks_daemon.plan_qa.model import PlanStatus
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    Finding,
    Level,
)
from claude_code_hooks_daemon.utils.authored_paths import contained_authored_path
from claude_code_hooks_daemon.utils.markdown_fences import lines_outside_fences

CHECK_ID: Final[str] = "path-existence"

# A plan whose work has not begun names the files it INTENDS to create, so
# "does not exist" is the expected state rather than drift. Every finding on
# this repo's first whole-tree scan was a plan in one of these states.
_WORK_NOT_BEGUN_STATUSES: Final[frozenset[PlanStatus]] = frozenset(
    {PlanStatus.NOT_STARTED, PlanStatus.BLOCKED, PlanStatus.DORMANT}
)

_INLINE_CODE_RE: Final[re.Pattern[str]] = re.compile(r"`([^`\n]+)`")
_MAX_REPORTED_PATHS: Final[int] = 10


def _project_path_pattern(context: CheckContext) -> re.Pattern[str]:
    """Match a project-path-shaped inline-code span.

    "Main repo code dirs" is read from the ProjectLayout facade (Plan 00288
    Task 4.3/C5) instead of the hardcoded src/tests/config triple.
    """
    code_dirs = "|".join(re.escape(d) for d in main_repo_code_dirs(context.layout))
    return re.compile(rf"^(?:{code_dirs})/[A-Za-z0-9_./-]+$")


def _rule(context: CheckContext, target: DocumentTarget) -> list[Finding]:
    if target.in_archive or target.doc.status in _WORK_NOT_BEGUN_STATUSES:
        return []

    project_path_re = _project_path_pattern(context)
    missing: list[str] = []
    for line in lines_outside_fences(target.text):
        for span in _INLINE_CODE_RE.findall(line):
            if not project_path_re.match(span):
                continue
            if span in missing:
                continue
            # CONTAINED, not merely normalised. The span comes out of a PLAN.md,
            # so it is authored; `_project_path_pattern` gates only the PREFIX,
            # and its character class allows `.` and `/`, so
            # `src/../../etc/passwd` matches and normalises clean out of the
            # repository. A plain existence answer over that is an ORACLE --
            # whether this finding appears reports whether the host path is
            # there. Outside the repository is not a project path, so the
            # escaping span joins `missing`: the check's own question is
            # "does this exist IN THIS PROJECT", and the answer is no.
            resolved = contained_authored_path(context.project_root, span)
            if resolved is None or not resolved.exists():
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
