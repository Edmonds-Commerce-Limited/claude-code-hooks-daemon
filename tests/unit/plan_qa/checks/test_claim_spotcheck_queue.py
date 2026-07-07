"""Tests for the claim-spotcheck-queue check (Plan 00144; sin B3)."""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.claim_spotcheck_queue import CHECK
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PROJECT_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"


def _context(readme_text: str | None) -> CheckContext:
    readme = ReadmeIndex.parse(readme_text) if readme_text is not None else None
    return CheckContext(
        project_root=_PROJECT_ROOT,
        plan_dir_rel=_PLAN_DIR_REL,
        readme=readme,
    )


class TestSpec:
    def test_registered_for_sweep_stage(self) -> None:
        assert CHECK.check_id == "claim-spotcheck-queue"
        assert CHECK.stage == Stage.SWEEP
        assert CHECK.level == Level.ADVISE
        assert CHECK.sins == ("B3",)


class TestPreconditions:
    def test_no_readme_returns_empty(self) -> None:
        context = _context(None)
        assert CHECK.run(context) == []


class TestFindings:
    def test_stable_status_is_clean(self) -> None:
        text = (
            "# Plans Index\n\n## Active Plans\n"
            "- [00001: Widget](00001-widget/PLAN.md) - In Progress\n"
        )
        assert CHECK.run(_context(text)) == []

    def test_pr_open_claim_advises(self) -> None:
        text = (
            "# Plans Index\n\n## Active Plans\n"
            "- [00001: Widget](00001-widget/PLAN.md) - PR #42 open\n"
        )
        findings = CHECK.run(_context(text))
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "claim-spotcheck-queue"
        assert finding.level == Level.ADVISE
        assert "00001" in finding.message
        assert "PR #42 open" in finding.message

    def test_pr_draft_claim_advises(self) -> None:
        text = (
            "# Plans Index\n\n## Active Plans\n"
            "- [00002: Gadget](00002-gadget/PLAN.md) - PR #7 draft, needs review\n"
        )
        findings = CHECK.run(_context(text))
        assert len(findings) == 1
        assert "00002" in findings[0].message

    def test_awaiting_merge_claim_advises(self) -> None:
        text = (
            "# Plans Index\n\n## Active Plans\n"
            "- [00003: Thing](00003-thing/PLAN.md) - awaiting merge\n"
        )
        findings = CHECK.run(_context(text))
        assert len(findings) == 1
        assert "00003" in findings[0].message

    def test_in_review_claim_advises(self) -> None:
        text = (
            "# Plans Index\n\n## Active Plans\n"
            "- [00004: Thing](00004-thing/PLAN.md) - in review\n"
        )
        findings = CHECK.run(_context(text))
        assert len(findings) == 1
        assert "00004" in findings[0].message

    def test_awaiting_approval_claim_advises(self) -> None:
        text = (
            "# Plans Index\n\n## Active Plans\n"
            "- [00005: Thing](00005-thing/PLAN.md) - awaiting approval\n"
        )
        findings = CHECK.run(_context(text))
        assert len(findings) == 1
        assert "00005" in findings[0].message

    def test_ignores_non_active_section(self) -> None:
        text = (
            "# Plans Index\n\n## Completed Plans\n"
            "- [00006: Thing](00006-thing/PLAN.md) - PR #9 open\n"
        )
        assert CHECK.run(_context(text)) == []

    def test_multiple_matches_in_one_finding(self) -> None:
        text = (
            "# Plans Index\n\n## Active Plans\n"
            "- [00001: Widget](00001-widget/PLAN.md) - PR #42 open\n"
            "- [00002: Gadget](00002-gadget/PLAN.md) - in review\n"
        )
        findings = CHECK.run(_context(text))
        assert len(findings) == 1
        assert "00001" in findings[0].message
        assert "00002" in findings[0].message
