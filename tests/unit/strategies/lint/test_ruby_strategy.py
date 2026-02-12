"""Tests for Ruby lint strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy
from claude_code_hooks_daemon.strategies.lint.ruby_strategy import RubyLintStrategy


@pytest.fixture()
def strategy() -> RubyLintStrategy:
    return RubyLintStrategy()


class TestProtocolConformance:
    def test_implements_protocol(self, strategy: RubyLintStrategy) -> None:
        assert isinstance(strategy, LintStrategy)


class TestProperties:
    def test_language_name(self, strategy: RubyLintStrategy) -> None:
        assert strategy.language_name == "Ruby"

    def test_extensions(self, strategy: RubyLintStrategy) -> None:
        assert strategy.extensions == (".rb",)

    def test_default_lint_command(self, strategy: RubyLintStrategy) -> None:
        assert strategy.default_lint_command == "ruby -c {file}"

    def test_extended_lint_command(self, strategy: RubyLintStrategy) -> None:
        assert strategy.extended_lint_command == "rubocop {file}"

    def test_skip_paths_is_tuple(self, strategy: RubyLintStrategy) -> None:
        assert isinstance(strategy.skip_paths, tuple)


class TestAcceptanceTests:
    def test_returns_list(self, strategy: RubyLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, strategy: RubyLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1
