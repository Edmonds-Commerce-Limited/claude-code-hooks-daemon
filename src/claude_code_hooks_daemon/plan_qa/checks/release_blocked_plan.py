"""Check ``release-blocked-plan`` (Stage 1 + 3, block; sins A3, A1).

``PlanWorkflow.core.md`` states the rule outright: *"Definition of done: merged
into main, never released… Do NOT write a task, success criterion, or status
line that waits on a release… A plan with such an item is not ``In Progress``;
it is finished work with a mislabelled header."*

It was written down and nothing enforced it, so Plan 00409 sat ``In Progress``
with a criterion reading "BLOCKED ON HUMAN — a published version carries the
fix" while its deliverable had been merged for days. This check is the
enforcement that documentation alone did not provide (Plan 00419 N3).

**The discrimination that matters.** Staging a release-bound consequence into
``CLAUDE/UPGRADES/UNRELEASED/`` is the CORRECT last step of a plan, and it
mentions releases constantly. Waiting for a release to HAPPEN is the defect.
Both talk about releases; only one blocks. So a line naming the holding area is
never flagged, however it is worded — a check that fires on the required step
would be worse than no check, because it would teach authors to stop staging.
"""

import re
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    DocumentRuleChecks,
    DocumentTarget,
    document_rule_checks,
)
from claude_code_hooks_daemon.plan_qa.model import PlanStatus
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Finding, Level

CHECK_ID: Final[str] = "release-blocked-plan"

_NON_TERMINAL_STATUSES: Final[frozenset[PlanStatus]] = frozenset(
    {PlanStatus.NOT_STARTED, PlanStatus.IN_PROGRESS}
)

#: An UNTICKED checkbox line. A ticked box records history and blocks nothing,
#: so flagging one would be pure noise.
_UNTICKED_RE: Final[re.Pattern[str]] = re.compile(r"^\s*[-*]\s*\[ \]")

#: The sanctioned shape: staging into the pending-release holding area. Checked
#: FIRST and unconditionally exempting, because this is the step a plan is
#: required to take and it necessarily says "release".
_HOLDING_AREA_RE: Final[re.Pattern[str]] = re.compile(
    r"UNRELEASED|holding area|release-bound consequence", re.IGNORECASE
)

#: Waiting ON a release. High precision by design: each phrase names a release
#: EVENT the item depends on, not a release ARTEFACT the item produces.
_WAITS_ON_RELEASE_RE: Final[re.Pattern[str]] = re.compile(
    r"blocked on (?:a )?(?:human )?(?:/)?release"
    r"|published version carries"
    r"|run `?/release"
    r"|at release time"
    r"|tag and publish"
    r"|awaiting (?:the )?release"
    r"|until (?:it is )?released"
    r"|once (?:it is )?released",
    re.IGNORECASE,
)

_REMEDIATION: Final[str] = (
    "A plan is done when its work is merged into main — a release is never part "
    "of it. Replace the waiting item with the step that actually belongs to the "
    "plan: stage the release-bound consequence in "
    "`CLAUDE/UPGRADES/UNRELEASED/` (a release-notes callout, a config-changes "
    "manifest, a post-upgrade task), then close the plan. The release bundles "
    "whatever is on main when a human runs it; it is gated on main, not on any "
    "plan, and no plan is gated on it."
)


def _rule(_context: CheckContext, target: DocumentTarget) -> list[Finding]:
    """Flag an unticked item in a live plan whose completion awaits a release.

    The context is unused: everything this rule needs is on the target, which
    is what lets it run unchanged at edit time and sweep time.
    """
    doc = target.doc
    if doc.status is None or doc.status not in _NON_TERMINAL_STATUSES:
        return []

    findings: list[Finding] = []
    for line in target.text.splitlines():
        if not _UNTICKED_RE.match(line):
            continue
        if _HOLDING_AREA_RE.search(line):
            continue
        if not _WAITS_ON_RELEASE_RE.search(line):
            continue
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.BLOCK,
                message=(
                    f"{target.rel_path}: an unticked item waits on a RELEASE — {line.strip()[:120]}"
                ),
                remediation=_REMEDIATION,
                path=target.rel_path,
            )
        )
        # One finding per document: the remediation is identical for every
        # offending line, and a plan with six of them should read one clear
        # instruction rather than six copies of it.
        break

    return findings


CHECKS: Final[DocumentRuleChecks] = document_rule_checks(
    check_id=CHECK_ID,
    level=Level.BLOCK,
    sins=("A3", "A1"),
    rule=_rule,
)
