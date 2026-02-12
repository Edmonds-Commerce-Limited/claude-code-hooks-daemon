"""Tests for Dart lint strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lint.dart_strategy import DartLintStrategy
from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy


@pytest.fixture()
def strategy() -> DartLintStrategy:
    return DartLintStrategy()


class TestProtocolConformance:
    def test_implements_protocol(self, strategy: DartLintStrategy) -> None:
        assert isinstance(strategy, LintStrategy)


class TestProperties:
    def test_language_name(self, strategy: DartLintStrategy) -> None:
        assert strategy.language_name == "Dart"

    def test_extensions(self, strategy: DartLintStrategy) -> None:
        assert strategy.extensions == (".dart",)

    def test_default_lint_command(self, strategy: DartLintStrategy) -> None:
        assert strategy.default_lint_command == "dart analyze {file}"

    def test_extended_lint_command_is_none(self, strategy: DartLintStrategy) -> None:
        assert strategy.extended_lint_command is None

    def test_skip_paths_is_tuple(self, strategy: DartLintStrategy) -> None:
        assert isinstance(strategy.skip_paths, tuple)


class TestAcceptanceTests:
    def test_returns_list(self, strategy: DartLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, strategy: DartLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1
