"""Tests for ``docs_qa.report`` (Plan 00284, Task 3.1a)."""

from claude_code_hooks_daemon.docs_qa.report import (
    CLEAN_SCOPE_CORPUS,
    MAX_ADVISORY_FINDINGS_SHOWN,
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

    def test_under_the_cap_shows_every_finding(self) -> None:
        findings = [
            Finding(
                check_id="module-doc-budget",
                severity=Severity.ADVISE,
                message=f"finding {i}",
                remediation="fix it",
                path=f"src/mod{i}/CLAUDE.md",
            )
            for i in range(3)
        ]
        text = format_advisory(findings)
        for i in range(3):
            assert f"finding {i}" in text
        assert "more" not in text

    def test_a_starved_check_still_gets_at_least_one_slot(self) -> None:
        """Registration-order accumulation must not let one prolific check
        (10 findings) starve out a check that only ever produces one
        finding (Task 3.1h)."""
        prolific = [
            Finding(
                check_id="at-import-census",
                severity=Severity.ADVISE,
                message=f"prolific {i}",
                remediation="fix it",
                path=f"CLAUDE/mod{i}.md",
            )
            for i in range(10)
        ]
        rare = [
            Finding(
                check_id="duplicate-block",
                severity=Severity.ADVISE,
                message="rare finding",
                remediation="fix it",
                path="CLAUDE/Other.md",
            )
        ]
        text = format_advisory([*prolific, *rare])
        assert "duplicate-block" in text
        assert "rare finding" in text
        # The prolific check must still be represented too.
        assert "at-import-census" in text
        omitted = len(prolific) + len(rare) - MAX_ADVISORY_FINDINGS_SHOWN
        assert f"{omitted} more" in text

    def test_block_severity_checks_are_round_robined_before_advise(self) -> None:
        block_findings = [
            Finding(
                check_id="pointer-resolves",
                severity=Severity.BLOCK,
                message=f"block {i}",
                remediation="fix it",
                path=f"CLAUDE/b{i}.md",
            )
            for i in range(9)
        ]
        advise_finding = Finding(
            check_id="quote-drift",
            severity=Severity.ADVISE,
            message="advise finding",
            remediation="fix it",
            path="CLAUDE/a.md",
        )
        text = format_advisory([*block_findings, advise_finding])
        assert "quote-drift" in text
        assert "advise finding" in text

    def test_over_the_cap_is_truncated_with_a_count_and_cli_pointer(self) -> None:
        findings = [
            Finding(
                check_id="module-doc-budget",
                severity=Severity.ADVISE,
                message=f"finding {i}",
                remediation="fix it",
                path=f"src/mod{i}/CLAUDE.md",
            )
            for i in range(12)
        ]
        text = format_advisory(findings)
        assert "finding 0" in text
        assert f"finding {MAX_ADVISORY_FINDINGS_SHOWN - 1}" in text
        assert f"finding {MAX_ADVISORY_FINDINGS_SHOWN}" not in text
        omitted = len(findings) - MAX_ADVISORY_FINDINGS_SHOWN
        assert f"{omitted} more" in text
        assert "docs-qa" in text


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
