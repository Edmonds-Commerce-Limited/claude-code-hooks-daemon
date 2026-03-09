"""Tests for NitpickChecker protocol, NitpickFinding, and NitpickState."""

import pytest

from claude_code_hooks_daemon.nitpick.protocol import (
    NitpickChecker,
    NitpickFinding,
    NitpickState,
)


class TestNitpickFinding:
    """Tests for NitpickFinding frozen dataclass."""

    def test_finding_fields(self) -> None:
        """NitpickFinding stores checker_id, category, message, matched_pattern."""
        finding = NitpickFinding(
            checker_id="dismissive_language",
            category="deflection",
            message="Detected dismissive language",
            matched_pattern=r"no issues with",
        )
        assert finding.checker_id == "dismissive_language"
        assert finding.category == "deflection"
        assert finding.message == "Detected dismissive language"
        assert finding.matched_pattern == r"no issues with"

    def test_finding_is_frozen(self) -> None:
        """NitpickFinding is immutable (frozen dataclass)."""
        finding = NitpickFinding(
            checker_id="test",
            category="test",
            message="test",
            matched_pattern="test",
        )
        with pytest.raises((AttributeError, TypeError)):
            finding.checker_id = "modified"


class TestNitpickState:
    """Tests for NitpickState mutable dataclass."""

    def test_state_defaults(self) -> None:
        """NitpickState has sensible defaults."""
        state = NitpickState()
        assert state.last_byte_offset == 0
        assert state.last_audited_uuid is None
        assert state.findings_count == 0

    def test_state_custom_values(self) -> None:
        """NitpickState accepts custom values."""
        state = NitpickState(
            last_byte_offset=1024,
            last_audited_uuid="abc-123",
            findings_count=5,
        )
        assert state.last_byte_offset == 1024
        assert state.last_audited_uuid == "abc-123"
        assert state.findings_count == 5

    def test_state_is_mutable(self) -> None:
        """NitpickState fields can be updated (mutable dataclass)."""
        state = NitpickState()
        state.last_byte_offset = 2048
        state.last_audited_uuid = "new-uuid"
        state.findings_count = 3
        assert state.last_byte_offset == 2048
        assert state.last_audited_uuid == "new-uuid"
        assert state.findings_count == 3


class TestNitpickCheckerProtocol:
    """Tests for NitpickChecker protocol compliance."""

    def test_checker_protocol_requires_checker_id(self) -> None:
        """NitpickChecker implementations must have checker_id."""

        class ValidChecker:
            checker_id = "test_checker"

            def check(self, text: str) -> list[NitpickFinding]:
                return []

        checker: NitpickChecker = ValidChecker()
        assert checker.checker_id == "test_checker"

    def test_checker_protocol_check_returns_findings(self) -> None:
        """NitpickChecker.check() returns list of NitpickFinding."""

        class FindingChecker:
            checker_id = "finding_checker"

            def check(self, text: str) -> list[NitpickFinding]:
                if "bad" in text:
                    return [
                        NitpickFinding(
                            checker_id=self.checker_id,
                            category="quality",
                            message="Found bad pattern",
                            matched_pattern="bad",
                        )
                    ]
                return []

        checker: NitpickChecker = FindingChecker()
        assert checker.check("good text") == []
        findings = checker.check("this is bad text")
        assert len(findings) == 1
        assert findings[0].checker_id == "finding_checker"
        assert findings[0].matched_pattern == "bad"

    def test_checker_protocol_check_empty_text(self) -> None:
        """NitpickChecker.check() handles empty text."""

        class EmptyChecker:
            checker_id = "empty_checker"

            def check(self, text: str) -> list[NitpickFinding]:
                return []

        checker: NitpickChecker = EmptyChecker()
        assert checker.check("") == []
