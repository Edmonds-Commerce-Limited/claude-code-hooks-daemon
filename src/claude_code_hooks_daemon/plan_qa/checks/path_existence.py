"""Check ``path-existence`` (Stage 1, advise; sin E5).

Plans routinely name real repository paths for reviewer orientation. When
those paths are renamed or removed by a later refactor, the plan silently
goes stale. This check scans inline-code spans that look like project
paths (``src/``, ``tests/``, ``config/``) and advises when they no longer
exist on disk. Archived plans are exempt: history is allowed to reference
paths that have since moved.
"""

import re
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import edit_target
from claude_code_hooks_daemon.plan_qa.model import lines_outside_fences
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "path-existence"

_INLINE_CODE_RE: Final[re.Pattern[str]] = re.compile(r"`([^`\n]+)`")
_PROJECT_PATH_RE: Final[re.Pattern[str]] = re.compile(r"^(?:src/|tests/|config/)[A-Za-z0-9_./-]+$")
_MAX_REPORTED_PATHS: Final[int] = 10


def _run(context: CheckContext) -> list[Finding]:
    target = edit_target(context)
    if target is None or target.in_archive:
        return []

    assert context.file_content is not None  # narrowed by edit_target succeeding

    missing: list[str] = []
    for line in lines_outside_fences(context.file_content):
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


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.EDIT,
    level=Level.ADVISE,
    sins=("E5",),
    run=_run,
)
