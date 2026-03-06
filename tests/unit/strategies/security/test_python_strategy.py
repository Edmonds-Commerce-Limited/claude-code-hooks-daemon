"""Tests for PythonSecurityStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.security.python_strategy import (
    PythonSecurityStrategy,
)


class TestPythonSecurityStrategy:
    """Test suite for PythonSecurityStrategy."""

    @pytest.fixture
    def strategy(self):
        return PythonSecurityStrategy()

    # ── Properties ────────────────────────────────────────────────────

    def test_language_name(self, strategy):
        assert strategy.language_name == "Python"

    def test_extensions(self, strategy):
        assert strategy.extensions == (".py",)

    def test_patterns_not_empty(self, strategy):
        assert len(strategy.patterns) > 0

    def test_all_patterns_have_a03_owasp(self, strategy):
        for pattern in strategy.patterns:
            assert pattern.owasp == "A03"

    # ── Pattern Matching ──────────────────────────────────────────────

    def test_matches_eval(self, strategy):
        content = "result = eval(user_input)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_exec(self, strategy):
        content = "exec(compiled_code)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_os_system(self, strategy):
        content = "os.system('ls -la')"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_subprocess_shell_true(self, strategy):
        content = "subprocess.run(cmd, shell=True)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_pickle_load(self, strategy):
        content = "obj = pickle.load(f)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_pickle_loads(self, strategy):
        content = "obj = pickle.loads(data)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_yaml_load(self, strategy):
        content = "config = yaml.load(stream)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_dunder_import(self, strategy):
        content = "mod = __import__(module_name)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_no_match_clean_python(self, strategy):
        content = "result = ast.literal_eval(user_input)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    def test_no_match_yaml_safe_load(self, strategy):
        content = "config = yaml.safe_load(stream)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    def test_no_match_subprocess_no_shell(self, strategy):
        content = "subprocess.run(['ls', '-la'], shell=False)"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    # ── Acceptance Tests ──────────────────────────────────────────────

    def test_acceptance_tests_not_empty(self, strategy):
        tests = strategy.get_acceptance_tests()
        assert len(tests) > 0
