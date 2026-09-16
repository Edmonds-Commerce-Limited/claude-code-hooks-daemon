"""Tests for the ``release-blocked-plan`` check (Plan 00419 N3; RED first).

``PlanWorkflow.core.md`` already states the rule outright — *"Definition of
done: merged into main, never released… A plan with such an item is not
`In Progress`; it is finished work with a mislabelled header."* It was written
down and nothing enforced it, so Plan 00409 sat `In Progress` with a success
criterion reading "BLOCKED ON HUMAN — a published version carries the fix"
while its deliverable had been on main for days.

The discrimination this check must get right is narrow and matters: staging a
release-bound consequence into `UNRELEASED/` is the CORRECT last step of a plan
and mentions releases constantly. Waiting for the release to HAPPEN is the
defect. Both talk about releases; only one blocks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.checks.release_blocked_plan import CHECK_ID, CHECKS
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level

_PLAN_DIR_REL = "CLAUDE/Plan"


def _edit_context(tmp_path: Path, content: str) -> CheckContext:
    plan = tmp_path / _PLAN_DIR_REL / "00409-example" / "PLAN.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(content)
    return CheckContext(
        project_root=tmp_path,
        plan_dir_rel=_PLAN_DIR_REL,
        file_path=plan,
        file_content=content,
        file_exists_before=True,
    )


def _run_edit(context: CheckContext) -> list:
    return CHECKS.edit.run(context)


def _plan(status: str, body: str) -> str:
    return f"""# Plan 00409: example

**Status**: {status}
**Created**: 2026-09-15
**Owner**: joseph
**Priority**: High

## Success Criteria

{body}
"""


class TestWaitingOnAReleaseIsFlagged:
    """The defect: an unticked item whose completion depends on a release."""

    @pytest.mark.parametrize(
        "line",
        [
            "- [ ] ⬜ **BLOCKED ON HUMAN** — a published version carries the fix.",
            "- [ ] ⬜ Blocked on release: the patch must ship before this closes.",
            "- [ ] ⬜ Run `/release` so the fix reaches installations.",
            "- [ ] ⬜ Acceptance-tested at release time.",
            "- [ ] ⬜ Tag and publish the version carrying this change.",
            "- [ ] ⬜ Awaiting release before this plan can close.",
        ],
    )
    def test_release_dependent_criterion_is_flagged(self, tmp_path: Path, line: str) -> None:
        findings = _run_edit(_edit_context(tmp_path, _plan("In Progress", line)))

        assert findings, f"a release-dependent criterion was not flagged: {line!r}"
        assert findings[0].check_id == CHECK_ID
        assert findings[0].level is Level.BLOCK


class TestStagingIntoTheHoldingAreaIsNeverFlagged:
    """The sanctioned shape. It mentions releases and must never be caught.

    This is the false positive that would make the check worse than useless:
    it would fire on the one step a plan is REQUIRED to take before closing.
    """

    @pytest.mark.parametrize(
        "line",
        [
            "- [x] ✅ Every release-bound consequence is in the pending-release "
            "holding area: `UNRELEASED/release-notes/01-thing.md`.",
            "- [x] ✅ This plan has no release-bound consequences: internal refactor only.",
            "- [ ] ⬜ Write the release-notes callout into `UNRELEASED/release-notes/`.",
            "- [x] ✅ A config-changes manifest is staged in `UNRELEASED/config-changes/`.",
        ],
    )
    def test_holding_area_criterion_is_not_flagged(self, tmp_path: Path, line: str) -> None:
        findings = _run_edit(_edit_context(tmp_path, _plan("In Progress", line)))

        assert not findings, f"the sanctioned holding-area shape was flagged: {line!r}"


class TestTickedItemsAreNotFlagged:
    """A ticked box is history, not a block. Flagging it would be noise."""

    def test_a_completed_release_mention_is_not_flagged(self, tmp_path: Path) -> None:
        line = "- [x] ✅ Shipped in the release that carried the fix."

        findings = _run_edit(_edit_context(tmp_path, _plan("Complete", line)))

        assert not findings


class TestTerminalPlansAreNotFlagged:
    """An archived plan recording what happened is not waiting on anything."""

    def test_complete_plan_with_release_prose_is_not_flagged(self, tmp_path: Path) -> None:
        line = "- [ ] ⬜ Blocked on release (superseded; recorded for history)."

        findings = _run_edit(_edit_context(tmp_path, _plan("Complete", line)))

        assert not findings, "a terminal plan is not waiting on a release by definition"


class TestOwnerGatedItemsAreNotFlagged:
    """A bare owner gate names no release event and must not be flagged.

    ``_WAITS_ON_RELEASE_RE``'s docstring promises "each phrase names a release
    EVENT the item depends on" — an owner ruling on an unrelated question is
    not a release event, so this is the false positive the module's own
    contract rules out.
    """

    @pytest.mark.parametrize(
        "line",
        [
            "- [ ] ⬜ **BLOCKED ON HUMAN** — the owner must choose between " "tier A and tier B.",
            "- [ ] ⬜ BLOCKED ON HUMAN: waiting for a ruling on the priority table.",
            "- [ ] ⬜ Ask the owner; blocked on human input until they reply.",
        ],
    )
    def test_owner_gate_without_a_release_mention_is_not_flagged(
        self, tmp_path: Path, line: str
    ) -> None:
        findings = _run_edit(_edit_context(tmp_path, _plan("In Progress", line)))

        assert not findings, f"an owner-gated item with no release mention was flagged: {line!r}"


class TestOrdinaryPlansAreUnaffected:
    def test_a_plan_that_never_mentions_a_release_is_clean(self, tmp_path: Path) -> None:
        line = "- [ ] ⬜ Full QA passes, the daemon restarts, CI green."

        findings = _run_edit(_edit_context(tmp_path, _plan("In Progress", line)))

        assert not findings


class TestTheRemediationSaysWhatToDo:
    def test_remediation_names_the_actual_fix(self, tmp_path: Path) -> None:
        line = "- [ ] ⬜ Blocked on release: the patch must ship before this closes."

        findings = _run_edit(_edit_context(tmp_path, _plan("In Progress", line)))

        remediation = findings[0].remediation.lower()
        assert "unreleased" in remediation or "holding area" in remediation, (
            "the remediation must point at staging into the holding area — that is "
            "the step that replaces waiting for the release"
        )
