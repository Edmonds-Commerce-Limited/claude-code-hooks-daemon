"""Tests for PHP lint strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lint.php_strategy import PhpLintStrategy
from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy


@pytest.fixture()
def strategy() -> PhpLintStrategy:
    return PhpLintStrategy()


class TestProtocolConformance:
    def test_implements_protocol(self, strategy: PhpLintStrategy) -> None:
        assert isinstance(strategy, LintStrategy)


class TestProperties:
    def test_language_name(self, strategy: PhpLintStrategy) -> None:
        assert strategy.language_name == "PHP"

    def test_extensions(self, strategy: PhpLintStrategy) -> None:
        assert strategy.extensions == (".php",)

    def test_default_lint_command(self, strategy: PhpLintStrategy) -> None:
        assert strategy.default_lint_command == "php -l {file}"

    def test_extended_lint_command(self, strategy: PhpLintStrategy) -> None:
        assert strategy.extended_lint_command == "phpstan analyse {file}"

    def test_skip_paths_is_tuple(self, strategy: PhpLintStrategy) -> None:
        assert isinstance(strategy.skip_paths, tuple)


class TestAcceptanceTests:
    def test_returns_list(self, strategy: PhpLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, strategy: PhpLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1

    def test_invalid_test_uses_genuinely_invalid_php(self, strategy: PhpLintStrategy) -> None:
        """Regression test: invalid PHP content must actually fail php -l.

        Bug: '<?php echo 'hello' ?>' is valid PHP — php -l returns exit 0.
        The closing '?>' makes the missing semicolon acceptable in PHP.
        Fix: use content with missing semicolons between statements (e.g.
        two echo statements where the first is missing its semicolon).
        """
        from claude_code_hooks_daemon.core import Decision

        tests = strategy.get_acceptance_tests()
        blocking_tests = [t for t in tests if t.expected_decision == Decision.DENY]
        assert blocking_tests, "PHP strategy must have at least one blocking acceptance test"

        blocking_test = blocking_tests[0]
        # The invalid content must NOT use the '?>' ending trick — that makes
        # missing semicolons valid PHP. Must use content that genuinely fails.
        assert "?>" not in blocking_test.command, (
            "Invalid PHP test must not end with '?>' — that allows missing semicolons. "
            "Use multiple statements where a semicolon is required between them."
        )
