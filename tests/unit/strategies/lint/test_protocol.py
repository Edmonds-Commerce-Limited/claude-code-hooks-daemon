"""Tests for Lint Strategy Protocol conformance."""

from typing import Any

import pytest

from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy


class _ValidLintStrategy:
    """A minimal valid lint strategy for protocol conformance testing."""

    @property
    def language_name(self) -> str:
        return "TestLang"

    @property
    def extensions(self) -> tuple[str, ...]:
        return (".tst",)

    @property
    def default_lint_command(self) -> str:
        return "testlint {file}"

    @property
    def extended_lint_command(self) -> str | None:
        return "testlint-ext {file}"

    @property
    def skip_paths(self) -> tuple[str, ...]:
        return ("vendor/",)

    def get_acceptance_tests(self) -> list[Any]:
        return []


class _InvalidLintStrategy:
    """Missing required methods."""

    @property
    def language_name(self) -> str:
        return "Bad"


class TestProtocolConformance:
    def test_valid_strategy_satisfies_protocol(self) -> None:
        strategy = _ValidLintStrategy()
        assert isinstance(strategy, LintStrategy)

    def test_invalid_strategy_does_not_satisfy_protocol(self) -> None:
        strategy = _InvalidLintStrategy()
        assert not isinstance(strategy, LintStrategy)

    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(LintStrategy, "__protocol_attrs__") or hasattr(
            LintStrategy, "__abstractmethods__"
        )


class TestValidStrategyProperties:
    @pytest.fixture()
    def strategy(self) -> _ValidLintStrategy:
        return _ValidLintStrategy()

    def test_language_name(self, strategy: _ValidLintStrategy) -> None:
        assert strategy.language_name == "TestLang"

    def test_extensions(self, strategy: _ValidLintStrategy) -> None:
        assert strategy.extensions == (".tst",)

    def test_default_lint_command(self, strategy: _ValidLintStrategy) -> None:
        assert strategy.default_lint_command == "testlint {file}"

    def test_extended_lint_command(self, strategy: _ValidLintStrategy) -> None:
        assert strategy.extended_lint_command == "testlint-ext {file}"

    def test_skip_paths(self, strategy: _ValidLintStrategy) -> None:
        assert strategy.skip_paths == ("vendor/",)

    def test_get_acceptance_tests(self, strategy: _ValidLintStrategy) -> None:
        assert strategy.get_acceptance_tests() == []
