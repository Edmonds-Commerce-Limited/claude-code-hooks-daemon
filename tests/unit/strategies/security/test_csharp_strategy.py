"""Tests for CSharpSecurityStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.security.csharp_strategy import (
    CSharpSecurityStrategy,
)


class TestCSharpSecurityStrategy:
    """Test suite for CSharpSecurityStrategy."""

    @pytest.fixture
    def strategy(self):
        return CSharpSecurityStrategy()

    # ── Properties ────────────────────────────────────────────────────

    def test_language_name(self, strategy):
        assert strategy.language_name == "C#"

    def test_extensions(self, strategy):
        assert strategy.extensions == (".cs",)

    def test_patterns_not_empty(self, strategy):
        assert len(strategy.patterns) > 0

    def test_all_patterns_have_a03_owasp(self, strategy):
        for pattern in strategy.patterns:
            assert pattern.owasp == "A03"

    # ── Pattern Matching ──────────────────────────────────────────────

    def test_matches_process_start(self, strategy):
        content = 'Process.Start("cmd.exe", "/c " + userInput);'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_binary_formatter(self, strategy):
        content = "BinaryFormatter formatter = new BinaryFormatter();"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_los_formatter(self, strategy):
        content = "LosFormatter losFormatter = new LosFormatter();"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_object_state_formatter(self, strategy):
        content = "ObjectStateFormatter stateFormatter = new ObjectStateFormatter();"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_no_match_clean_csharp(self, strategy):
        content = 'Console.WriteLine("Hello World");'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    def test_no_match_json_serializer(self, strategy):
        content = "var result = JsonSerializer.Deserialize<MyType>(json);"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    # ── Acceptance Tests ──────────────────────────────────────────────

    def test_acceptance_tests_not_empty(self, strategy):
        tests = strategy.get_acceptance_tests()
        assert len(tests) > 0
