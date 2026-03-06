"""Tests for JavaScriptSecurityStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.security.javascript_strategy import (
    JavaScriptSecurityStrategy,
)


class TestJavaScriptSecurityStrategy:
    """Test suite for JavaScriptSecurityStrategy."""

    @pytest.fixture
    def strategy(self):
        return JavaScriptSecurityStrategy()

    # ── Properties ────────────────────────────────────────────────────

    def test_language_name(self, strategy):
        assert strategy.language_name == "JavaScript"

    def test_extensions(self, strategy):
        assert ".ts" in strategy.extensions
        assert ".tsx" in strategy.extensions
        assert ".js" in strategy.extensions
        assert ".jsx" in strategy.extensions

    def test_patterns_not_empty(self, strategy):
        assert len(strategy.patterns) > 0

    def test_all_patterns_have_a03_owasp(self, strategy):
        for pattern in strategy.patterns:
            assert pattern.owasp == "A03"

    # ── Pattern Matching ──────────────────────────────────────────────

    def test_matches_eval(self, strategy):
        content = "const result = eval(userCode);"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_new_function(self, strategy):
        content = 'const fn = new Function("return " + userInput);'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_dangerously_set_inner_html(self, strategy):
        content = "<div dangerouslySetInnerHTML={{__html: userContent}} />"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_inner_html_assignment(self, strategy):
        content = "element.innerHTML = userContent;"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_document_write(self, strategy):
        content = "document.write(content);"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_no_match_clean_js(self, strategy):
        content = "const greeting = 'Hello World';"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    # ── Acceptance Tests ──────────────────────────────────────────────

    def test_acceptance_tests_not_empty(self, strategy):
        tests = strategy.get_acceptance_tests()
        assert len(tests) > 0
