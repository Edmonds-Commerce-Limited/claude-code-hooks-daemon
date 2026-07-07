"""Tests for plan_qa.report — finding renderers (Plan 00144, Task 1.5)."""

from claude_code_hooks_daemon.plan_qa.report import (
    format_advisory,
    format_block_reason,
    format_cli_report,
)
from claude_code_hooks_daemon.plan_qa.types import Finding, Level


def _finding(check_id: str = "test-check", level: Level = Level.BLOCK) -> Finding:
    return Finding(
        check_id=check_id,
        level=level,
        message="the invariant that was violated",
        remediation="the exact fix to apply",
        path="CLAUDE/Plan/00001-x/PLAN.md",
    )


class TestBlockReason:
    def test_names_check_message_and_remediation(self) -> None:
        text = format_block_reason([_finding("status-line-present")])
        assert "status-line-present" in text
        assert "the invariant that was violated" in text
        assert "the exact fix to apply" in text

    def test_multiple_findings_all_rendered(self) -> None:
        text = format_block_reason([_finding("first"), _finding("second")])
        assert "first" in text
        assert "second" in text


class TestAdvisory:
    def test_lists_all_findings(self) -> None:
        text = format_advisory([_finding("a"), _finding("b", level=Level.ADVISE)])
        assert "a" in text
        assert "b" in text

    def test_includes_path_when_present(self) -> None:
        text = format_advisory([_finding()])
        assert "CLAUDE/Plan/00001-x/PLAN.md" in text


class TestCliReport:
    def test_empty_is_clean(self) -> None:
        text = format_cli_report([])
        assert "0 finding" in text

    def test_counts_by_level(self) -> None:
        findings = [
            _finding("x", level=Level.BLOCK),
            _finding("y", level=Level.ADVISE),
            _finding("z", level=Level.ADVISE),
        ]
        text = format_cli_report(findings)
        assert "3 finding" in text
        assert "1 block" in text
        assert "2 advise" in text
        assert "CLAUDE/Plan/00001-x/PLAN.md" in text

    def test_finding_without_path_renders(self) -> None:
        finding = Finding(check_id="p", level=Level.ADVISE, message="m", remediation="r")
        text = format_cli_report([finding])
        assert "1 finding" in text
        assert "m" in text
