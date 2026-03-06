"""Tests for RubySecurityStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.security.ruby_strategy import (
    RubySecurityStrategy,
)


class TestRubySecurityStrategy:
    """Test suite for RubySecurityStrategy."""

    @pytest.fixture
    def strategy(self):
        return RubySecurityStrategy()

    # ── Properties ────────────────────────────────────────────────────

    def test_language_name(self, strategy):
        assert strategy.language_name == "Ruby"

    def test_extensions(self, strategy):
        assert strategy.extensions == (".rb",)

    def test_patterns_not_empty(self, strategy):
        assert len(strategy.patterns) > 0

    def test_all_patterns_have_a03_owasp(self, strategy):
        for pattern in strategy.patterns:
            assert pattern.owasp == "A03"

    # ── Pattern Matching ──────────────────────────────────────────────

    def test_matches_eval(self, strategy):
        content = "eval(user_input)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_system(self, strategy):
        content = "system('ls -la')"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_exec(self, strategy):
        content = "exec('whoami')"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_instance_eval(self, strategy):
        content = "obj.instance_eval { dangerous_code }"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_class_eval(self, strategy):
        content = "MyClass.class_eval { dangerous_code }"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_marshal_load(self, strategy):
        content = "obj = Marshal.load(data)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_io_popen(self, strategy):
        content = "IO.popen(cmd) { |f| f.read }"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_no_match_clean_ruby(self, strategy):
        content = 'puts "Hello, World!"'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    def test_no_match_open3(self, strategy):
        content = "Open3.capture3('ls', '-la')"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    # ── Acceptance Tests ──────────────────────────────────────────────

    def test_acceptance_tests_not_empty(self, strategy):
        tests = strategy.get_acceptance_tests()
        assert len(tests) > 0
