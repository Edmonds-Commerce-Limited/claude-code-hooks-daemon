"""Tests for HedgingLanguageChecker nitpick strategy."""

from claude_code_hooks_daemon.nitpick.checkers.hedging import (
    HedgingLanguageChecker,
)
from claude_code_hooks_daemon.nitpick.protocol import NitpickChecker


class TestHedgingLanguageChecker:
    """Tests for HedgingLanguageChecker."""

    def test_implements_protocol(self) -> None:
        """HedgingLanguageChecker satisfies NitpickChecker protocol."""
        checker = HedgingLanguageChecker()
        assert isinstance(checker, NitpickChecker)

    def test_checker_id(self) -> None:
        """Checker has correct ID."""
        checker = HedgingLanguageChecker()
        assert checker.checker_id == "hedging_language"

    def test_clean_text_returns_empty(self) -> None:
        """No findings for text without hedging language."""
        checker = HedgingLanguageChecker()
        findings = checker.check("The function returns a list of integers.")
        assert findings == []

    def test_empty_text_returns_empty(self) -> None:
        """No findings for empty text."""
        checker = HedgingLanguageChecker()
        assert checker.check("") == []

    def test_detects_memory_based_guessing(self) -> None:
        """Detects 'if I recall' pattern."""
        checker = HedgingLanguageChecker()
        findings = checker.check("If I recall correctly, the API uses JSON.")
        assert len(findings) == 1
        assert findings[0].checker_id == "hedging_language"
        assert findings[0].category == "memory_guessing"

    def test_detects_iirc(self) -> None:
        """Detects 'IIRC' pattern."""
        checker = HedgingLanguageChecker()
        findings = checker.check("IIRC the config file is in /etc/.")
        assert len(findings) == 1
        assert findings[0].category == "memory_guessing"

    def test_detects_uncertainty_hedging(self) -> None:
        """Detects 'probably' pattern."""
        checker = HedgingLanguageChecker()
        findings = checker.check("This probably needs a database migration.")
        assert len(findings) == 1
        assert findings[0].category == "uncertainty"

    def test_detects_i_believe(self) -> None:
        """Detects 'I believe' pattern."""
        checker = HedgingLanguageChecker()
        findings = checker.check("I believe the function is in utils.py.")
        assert len(findings) == 1
        assert findings[0].category == "uncertainty"

    def test_detects_weak_confidence(self) -> None:
        """Detects 'might be' pattern."""
        checker = HedgingLanguageChecker()
        findings = checker.check("The issue might be in the parser module.")
        assert len(findings) == 1
        assert findings[0].category == "weak_confidence"

    def test_detects_im_not_sure(self) -> None:
        """Detects 'I'm not sure but' pattern."""
        checker = HedgingLanguageChecker()
        findings = checker.check("I'm not sure but it could be a race condition.")
        assert len(findings) >= 1

    def test_multiple_findings(self) -> None:
        """Returns multiple findings for text with multiple patterns."""
        checker = HedgingLanguageChecker()
        text = "I believe the config probably needs updating."
        findings = checker.check(text)
        assert len(findings) >= 2

    def test_case_insensitive(self) -> None:
        """Pattern matching is case-insensitive."""
        checker = HedgingLanguageChecker()
        findings = checker.check("IF I RECALL correctly, it uses REST.")
        assert len(findings) == 1

    def test_finding_has_matched_pattern(self) -> None:
        """Each finding includes the matched pattern."""
        checker = HedgingLanguageChecker()
        findings = checker.check("I believe the issue is in main.py.")
        assert len(findings) == 1
        assert findings[0].matched_pattern != ""
