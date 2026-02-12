"""Tests for Python lint strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy
from claude_code_hooks_daemon.strategies.lint.python_strategy import PythonLintStrategy


@pytest.fixture()
def strategy() -> PythonLintStrategy:
    return PythonLintStrategy()


class TestProtocolConformance:
    def test_implements_protocol(self, strategy: PythonLintStrategy) -> None:
        assert isinstance(strategy, LintStrategy)


class TestProperties:
    def test_language_name(self, strategy: PythonLintStrategy) -> None:
        assert strategy.language_name == "Python"

    def test_extensions(self, strategy: PythonLintStrategy) -> None:
        assert strategy.extensions == (".py",)

    def test_default_lint_command(self, strategy: PythonLintStrategy) -> None:
        assert strategy.default_lint_command == "python3 -m py_compile {file}"

    def test_extended_lint_command(self, strategy: PythonLintStrategy) -> None:
        assert strategy.extended_lint_command == "ruff check {file}"

    def test_skip_paths_is_tuple(self, strategy: PythonLintStrategy) -> None:
        assert isinstance(strategy.skip_paths, tuple)

    def test_skip_paths_contains_venv(self, strategy: PythonLintStrategy) -> None:
        assert any("venv" in p for p in strategy.skip_paths)


class TestAcceptanceTests:
    def test_returns_list(self, strategy: PythonLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, strategy: PythonLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1
