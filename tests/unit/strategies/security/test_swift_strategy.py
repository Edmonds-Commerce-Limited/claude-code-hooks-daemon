"""Tests for SwiftSecurityStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.security.swift_strategy import (
    SwiftSecurityStrategy,
)


class TestSwiftSecurityStrategy:
    """Test suite for SwiftSecurityStrategy."""

    @pytest.fixture
    def strategy(self):
        return SwiftSecurityStrategy()

    # ── Properties ────────────────────────────────────────────────────

    def test_language_name(self, strategy):
        assert strategy.language_name == "Swift"

    def test_extensions(self, strategy):
        assert strategy.extensions == (".swift",)

    def test_patterns_not_empty(self, strategy):
        assert len(strategy.patterns) > 0

    def test_all_patterns_have_a03_owasp(self, strategy):
        for pattern in strategy.patterns:
            assert pattern.owasp == "A03"

    # ── Pattern Matching ──────────────────────────────────────────────

    def test_matches_process(self, strategy):
        content = "let task = Process()"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_evaluate_javascript(self, strategy):
        content = 'webView.evaluateJavaScript("alert(1)")'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_nskeyedunarchiver_unarchive_object(self, strategy):
        content = "let obj = NSKeyedUnarchiver.unarchiveObject(with: data)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_no_match_clean_swift(self, strategy):
        content = 'print("Hello, World!")'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    # ── Acceptance Tests ──────────────────────────────────────────────

    def test_acceptance_tests_not_empty(self, strategy):
        tests = strategy.get_acceptance_tests()
        assert len(tests) > 0
