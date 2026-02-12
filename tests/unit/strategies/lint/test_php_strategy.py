"""Tests for PHP lint strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy
from claude_code_hooks_daemon.strategies.lint.php_strategy import PhpLintStrategy


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
