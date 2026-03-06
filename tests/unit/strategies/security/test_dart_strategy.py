"""Tests for DartSecurityStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.security.dart_strategy import (
    DartSecurityStrategy,
)


class TestDartSecurityStrategy:
    """Test suite for DartSecurityStrategy."""

    @pytest.fixture
    def strategy(self):
        return DartSecurityStrategy()

    # ── Properties ────────────────────────────────────────────────────

    def test_language_name(self, strategy):
        assert strategy.language_name == "Dart"

    def test_extensions(self, strategy):
        assert strategy.extensions == (".dart",)

    def test_patterns_not_empty(self, strategy):
        assert len(strategy.patterns) > 0

    def test_all_patterns_have_a03_owasp(self, strategy):
        for pattern in strategy.patterns:
            assert pattern.owasp == "A03"

    # ── Pattern Matching ──────────────────────────────────────────────

    def test_matches_process_run(self, strategy):
        content = "await Process.run('ls', ['-la']);"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_process_start(self, strategy):
        content = "final process = await Process.start('cmd', args);"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_inner_html(self, strategy):
        content = "element.innerHTML = userInput;"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_no_match_clean_dart(self, strategy):
        content = "print('Hello, World!');"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    # ── Acceptance Tests ──────────────────────────────────────────────

    def test_acceptance_tests_not_empty(self, strategy):
        tests = strategy.get_acceptance_tests()
        assert len(tests) > 0
