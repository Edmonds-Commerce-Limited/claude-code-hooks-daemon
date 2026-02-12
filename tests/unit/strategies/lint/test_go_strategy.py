"""Tests for Go lint strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lint.go_strategy import GoLintStrategy
from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy


@pytest.fixture()
def strategy() -> GoLintStrategy:
    return GoLintStrategy()


class TestProtocolConformance:
    def test_implements_protocol(self, strategy: GoLintStrategy) -> None:
        assert isinstance(strategy, LintStrategy)


class TestProperties:
    def test_language_name(self, strategy: GoLintStrategy) -> None:
        assert strategy.language_name == "Go"

    def test_extensions(self, strategy: GoLintStrategy) -> None:
        assert strategy.extensions == (".go",)

    def test_default_lint_command(self, strategy: GoLintStrategy) -> None:
        assert strategy.default_lint_command == "go vet {file}"

    def test_extended_lint_command(self, strategy: GoLintStrategy) -> None:
        assert strategy.extended_lint_command == "golangci-lint run {file}"

    def test_skip_paths_is_tuple(self, strategy: GoLintStrategy) -> None:
        assert isinstance(strategy.skip_paths, tuple)


class TestAcceptanceTests:
    def test_returns_list(self, strategy: GoLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, strategy: GoLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1
