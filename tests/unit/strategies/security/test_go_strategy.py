"""Tests for GoSecurityStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.security.go_strategy import (
    GoSecurityStrategy,
)


class TestGoSecurityStrategy:
    """Test suite for GoSecurityStrategy."""

    @pytest.fixture
    def strategy(self):
        return GoSecurityStrategy()

    # ── Properties ────────────────────────────────────────────────────

    def test_language_name(self, strategy):
        assert strategy.language_name == "Go"

    def test_extensions(self, strategy):
        assert strategy.extensions == (".go",)

    def test_patterns_not_empty(self, strategy):
        assert len(strategy.patterns) > 0

    def test_all_patterns_have_a03_owasp(self, strategy):
        for pattern in strategy.patterns:
            assert pattern.owasp == "A03"

    # ── Pattern Matching ──────────────────────────────────────────────

    def test_matches_template_html(self, strategy):
        content = "safe := template.HTML(userInput)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_template_js(self, strategy):
        content = "safe := template.JS(userScript)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_template_url(self, strategy):
        content = "safe := template.URL(userURL)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_no_match_clean_go(self, strategy):
        content = 'fmt.Println("Hello, World!")'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    def test_no_match_regular_template(self, strategy):
        content = 't := template.New("page")'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    # ── Acceptance Tests ──────────────────────────────────────────────

    def test_acceptance_tests_not_empty(self, strategy):
        tests = strategy.get_acceptance_tests()
        assert len(tests) > 0
