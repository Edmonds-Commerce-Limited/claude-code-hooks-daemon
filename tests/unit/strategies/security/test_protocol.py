"""Tests for security strategy protocol definitions."""

import pytest

from claude_code_hooks_daemon.strategies.security.protocol import (
    SecurityPattern,
)


class TestSecurityPattern:
    """Test SecurityPattern dataclass."""

    def test_create_pattern(self):
        pattern = SecurityPattern(
            name="Test Pattern",
            regex=r"\btest\b",
            owasp="A01",
            suggestion="Do not use test",
        )
        assert pattern.name == "Test Pattern"
        assert pattern.regex == r"\btest\b"
        assert pattern.owasp == "A01"
        assert pattern.suggestion == "Do not use test"

    def test_pattern_is_frozen(self):
        pattern = SecurityPattern(
            name="Test",
            regex=r"test",
            owasp="A01",
            suggestion="Fix it",
        )
        with pytest.raises(AttributeError):
            pattern.name = "Changed"

    def test_pattern_equality(self):
        p1 = SecurityPattern(name="A", regex=r"a", owasp="A01", suggestion="s")
        p2 = SecurityPattern(name="A", regex=r"a", owasp="A01", suggestion="s")
        assert p1 == p2

    def test_pattern_inequality(self):
        p1 = SecurityPattern(name="A", regex=r"a", owasp="A01", suggestion="s")
        p2 = SecurityPattern(name="B", regex=r"b", owasp="A02", suggestion="t")
        assert p1 != p2
