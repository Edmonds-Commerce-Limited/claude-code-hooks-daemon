"""Tests for Swift lint strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy
from claude_code_hooks_daemon.strategies.lint.swift_strategy import SwiftLintStrategy


@pytest.fixture()
def strategy() -> SwiftLintStrategy:
    return SwiftLintStrategy()


class TestProtocolConformance:
    def test_implements_protocol(self, strategy: SwiftLintStrategy) -> None:
        assert isinstance(strategy, LintStrategy)


class TestProperties:
    def test_language_name(self, strategy: SwiftLintStrategy) -> None:
        assert strategy.language_name == "Swift"

    def test_extensions(self, strategy: SwiftLintStrategy) -> None:
        assert strategy.extensions == (".swift",)

    def test_default_lint_command(self, strategy: SwiftLintStrategy) -> None:
        assert strategy.default_lint_command == "swiftc -typecheck {file}"

    def test_extended_lint_command(self, strategy: SwiftLintStrategy) -> None:
        assert strategy.extended_lint_command == "swiftlint lint {file}"

    def test_skip_paths_is_tuple(self, strategy: SwiftLintStrategy) -> None:
        assert isinstance(strategy.skip_paths, tuple)


class TestAcceptanceTests:
    def test_returns_list(self, strategy: SwiftLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, strategy: SwiftLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1
