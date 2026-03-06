"""Tests for PhpSecurityStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.security.php_strategy import (
    PhpSecurityStrategy,
)


class TestPhpSecurityStrategy:
    """Test suite for PhpSecurityStrategy."""

    @pytest.fixture
    def strategy(self):
        return PhpSecurityStrategy()

    # ── Properties ────────────────────────────────────────────────────

    def test_language_name(self, strategy):
        assert strategy.language_name == "PHP"

    def test_extensions(self, strategy):
        assert strategy.extensions == (".php",)

    def test_patterns_not_empty(self, strategy):
        assert len(strategy.patterns) > 0

    def test_all_patterns_have_a03_owasp(self, strategy):
        for pattern in strategy.patterns:
            assert pattern.owasp == "A03"

    # ── Pattern Matching ──────────────────────────────────────────────

    def test_matches_eval(self, strategy):
        content = "<?php eval($userInput);"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_exec(self, strategy):
        content = '<?php exec("ls -la");'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_shell_exec(self, strategy):
        content = '<?php shell_exec("whoami");'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_system(self, strategy):
        content = '<?php system("id");'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_passthru(self, strategy):
        content = '<?php passthru("cat /etc/passwd");'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_proc_open(self, strategy):
        content = "<?php proc_open($cmd, $desc, $pipes);"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_unserialize(self, strategy):
        content = "<?php unserialize($userData);"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_no_match_clean_php(self, strategy):
        content = '<?php echo "Hello World";'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    # ── Acceptance Tests ──────────────────────────────────────────────

    def test_acceptance_tests_not_empty(self, strategy):
        tests = strategy.get_acceptance_tests()
        assert len(tests) > 0
