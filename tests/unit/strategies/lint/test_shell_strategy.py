"""Tests for Shell lint strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy
from claude_code_hooks_daemon.strategies.lint.shell_strategy import ShellLintStrategy


@pytest.fixture()
def strategy() -> ShellLintStrategy:
    return ShellLintStrategy()


class TestProtocolConformance:
    def test_implements_protocol(self, strategy: ShellLintStrategy) -> None:
        assert isinstance(strategy, LintStrategy)


class TestProperties:
    def test_language_name(self, strategy: ShellLintStrategy) -> None:
        assert strategy.language_name == "Shell"

    def test_extensions(self, strategy: ShellLintStrategy) -> None:
        assert strategy.extensions == (".sh", ".bash")

    def test_default_lint_command(self, strategy: ShellLintStrategy) -> None:
        assert strategy.default_lint_command == "bash -n {file}"

    def test_extended_lint_command(self, strategy: ShellLintStrategy) -> None:
        assert strategy.extended_lint_command == "shellcheck -x {file}"

    def test_skip_paths_is_tuple(self, strategy: ShellLintStrategy) -> None:
        assert isinstance(strategy.skip_paths, tuple)

    def test_skip_paths_contains_node_modules(self, strategy: ShellLintStrategy) -> None:
        assert any("node_modules" in p for p in strategy.skip_paths)


class TestAcceptanceTests:
    def test_returns_list(self, strategy: ShellLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, strategy: ShellLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1

    def test_acceptance_test_has_title(self, strategy: ShellLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert tests[0].title is not None
