"""Tests for DismissiveLanguageChecker nitpick strategy."""

from claude_code_hooks_daemon.nitpick.checkers.dismissive import (
    DismissiveLanguageChecker,
)
from claude_code_hooks_daemon.nitpick.protocol import NitpickChecker


class TestDismissiveLanguageChecker:
    """Tests for DismissiveLanguageChecker."""

    def test_implements_protocol(self) -> None:
        """DismissiveLanguageChecker satisfies NitpickChecker protocol."""
        checker = DismissiveLanguageChecker()
        assert isinstance(checker, NitpickChecker)

    def test_checker_id(self) -> None:
        """Checker has correct ID."""
        checker = DismissiveLanguageChecker()
        assert checker.checker_id == "dismissive_language"

    def test_clean_text_returns_empty(self) -> None:
        """No findings for text without dismissive language."""
        checker = DismissiveLanguageChecker()
        findings = checker.check("I fixed the bug and all tests pass.")
        assert findings == []

    def test_empty_text_returns_empty(self) -> None:
        """No findings for empty text."""
        checker = DismissiveLanguageChecker()
        assert checker.check("") == []

    def test_detects_not_our_problem(self) -> None:
        """Detects 'not caused by our changes' pattern."""
        checker = DismissiveLanguageChecker()
        findings = checker.check("This error is not caused by our changes.")
        assert len(findings) >= 1
        assert all(f.checker_id == "dismissive_language" for f in findings)
        assert all(f.category == "not_our_problem" for f in findings)

    def test_detects_pre_existing(self) -> None:
        """Detects 'pre-existing issue' pattern."""
        checker = DismissiveLanguageChecker()
        findings = checker.check("This is a pre-existing issue in the codebase.")
        assert len(findings) == 1
        assert findings[0].category == "not_our_problem"

    def test_detects_out_of_scope(self) -> None:
        """Detects 'outside the scope of' pattern."""
        checker = DismissiveLanguageChecker()
        findings = checker.check("That's outside the scope of this task.")
        assert len(findings) == 1
        assert findings[0].category == "out_of_scope"

    def test_detects_separate_concern(self) -> None:
        """Detects 'separate concern' pattern."""
        checker = DismissiveLanguageChecker()
        findings = checker.check("That's a separate concern entirely.")
        assert len(findings) == 1
        assert findings[0].category == "out_of_scope"

    def test_detects_someone_elses_job(self) -> None:
        """Detects 'not our responsibility' pattern."""
        checker = DismissiveLanguageChecker()
        findings = checker.check("That's not our responsibility to fix.")
        assert len(findings) == 1
        assert findings[0].category == "someone_elses_job"

    def test_detects_defer_ignore(self) -> None:
        """Detects 'can be addressed later' pattern."""
        checker = DismissiveLanguageChecker()
        findings = checker.check("This can be addressed later in a follow-up.")
        assert len(findings) == 1
        assert findings[0].category == "defer_ignore"

    def test_detects_no_issues_with_my(self) -> None:
        """Detects 'no issues with my' — the dogfooding failure pattern."""
        checker = DismissiveLanguageChecker()
        findings = checker.check("There are no issues with my new code.")
        assert len(findings) >= 1
        assert any(f.category == "not_our_problem" for f in findings)

    def test_detects_not_introduced_by_my_change(self) -> None:
        """Detects 'not introduced by my change' pattern."""
        checker = DismissiveLanguageChecker()
        findings = checker.check("This was not introduced by my change.")
        assert len(findings) >= 1

    def test_multiple_findings(self) -> None:
        """Returns multiple findings for text with multiple patterns."""
        checker = DismissiveLanguageChecker()
        text = "This is a pre-existing issue. It's outside the scope of our work."
        findings = checker.check(text)
        assert len(findings) >= 2

    def test_case_insensitive(self) -> None:
        """Pattern matching is case-insensitive."""
        checker = DismissiveLanguageChecker()
        findings = checker.check("This is a PRE-EXISTING ISSUE in the code.")
        assert len(findings) == 1

    def test_finding_has_matched_pattern(self) -> None:
        """Each finding includes the matched pattern."""
        checker = DismissiveLanguageChecker()
        findings = checker.check("This is a pre-existing issue.")
        assert len(findings) == 1
        assert findings[0].matched_pattern != ""
