"""Check ``task-grammar`` (Stage 1, advise; sin E6).

Ad-hoc progress markers (``[✓]``, ``[⏳]``, ``[~]``) are unparseable by
tooling that expects the template's checkbox + status-icon grammar. New
material is held to the block-level standard (via :func:`level_for_plan`);
existing files being edited for other reasons only get advice so a small
edit does not force a full grammar rewrite.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import edit_target, level_for_plan
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "task-grammar"

_REMEDIATION: Final[str] = (
    "Use the template task grammar instead of ad-hoc markers like [✓], [⏳], "
    "[~]: `- [ ] ⬜ **Task N.N**: ...` for pending work, `- [x] ✅ ...` for done."
)


def _run(context: CheckContext) -> list[Finding]:
    target = edit_target(context)
    if target is None or target.doc.tasks.legacy_marker_lines == 0:
        return []

    level = (
        level_for_plan(context, target.plan_number)
        if context.file_exists_before is False
        else Level.ADVISE
    )

    return [
        Finding(
            check_id=CHECK_ID,
            level=level,
            message="PLAN.md uses ad-hoc legacy task markers instead of the template grammar",
            remediation=_REMEDIATION,
            path=target.rel_path,
        )
    ]


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.EDIT,
    level=Level.ADVISE,
    sins=("E6",),
    run=_run,
)
