"""Tests for ``docs_qa.report`` (Plan 00284, Task 3.1a)."""

from claude_code_hooks_daemon.docs_qa.report import (
    CLEAN_SCOPE_CORPUS,
    format_advisory,
    format_block_reason,
    format_cli_report,
)
from claude_code_hooks_daemon.docs_qa.types import Finding, Severity

_FINDING = Finding(
    check_id="pointer-resolves",
    severity=Severity.BLOCK,
    message="Link target does not exist: Nope.md",
    remediation="Fix or remove the link.",
    path="CLAUDE/Foo.md",
)
_ADVISE_FINDING = Finding(
    check_id="pointer-resolves",
    severity=Severity.ADVISE,
    message="Link target does not exist: Old.md",
    remediation="Fix or remove the link.",
    path="CLAUDE/Bar.md",
)


class TestFormatBlockReason:
    def test_names_check_path_and_remediation(self) -> None:
        text = format_block_reason([_FINDING])
        assert "pointer-resolves" in text
        assert "CLAUDE/Foo.md" in text
        assert "Fix or remove the link." in text


class TestFormatAdvisory:
    def test_names_check_and_message(self) -> None:
        text = format_advisory([_ADVISE_FINDING])
        assert "pointer-resolves" in text
        assert "Old.md" in text


class TestFormatCliReport:
    def test_clean_report_names_the_scope(self) -> None:
        text = format_cli_report([])
        assert "0 finding" in text
        assert CLEAN_SCOPE_CORPUS in text

    def test_clean_report_accepts_custom_scope(self) -> None:
        text = format_cli_report([], clean_scope="CLAUDE/Foo.md is clean")
        assert "CLAUDE/Foo.md is clean" in text

    def test_counts_block_and_advise_separately(self) -> None:
        text = format_cli_report([_FINDING, _ADVISE_FINDING])
        assert "2 finding" in text
        assert "1 block" in text
        assert "1 advise" in text
        assert "pointer-resolves" in text
