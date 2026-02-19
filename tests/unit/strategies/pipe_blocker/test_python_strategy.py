"""Tests for PythonPipeBlockerStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.pipe_blocker.python_strategy import (
    PythonPipeBlockerStrategy,
)


@pytest.fixture
def strategy() -> PythonPipeBlockerStrategy:
    return PythonPipeBlockerStrategy()


class TestPythonStrategyProperties:
    def test_language_name(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert strategy.language_name == "Python"

    def test_blacklist_patterns_is_tuple(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert isinstance(strategy.blacklist_patterns, tuple)

    def test_blacklist_patterns_non_empty(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert len(strategy.blacklist_patterns) > 0


class TestPythonStrategyBlacklistPatterns:
    def test_contains_pytest(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert r"^pytest\b" in strategy.blacklist_patterns

    def test_contains_mypy(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert r"^mypy\b" in strategy.blacklist_patterns

    def test_contains_ruff_check(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert r"^ruff\s+check\b" in strategy.blacklist_patterns

    def test_contains_black(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert r"^black\b" in strategy.blacklist_patterns

    def test_contains_bandit(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert r"^bandit\b" in strategy.blacklist_patterns

    def test_contains_coverage(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert r"^coverage\b" in strategy.blacklist_patterns

    def test_contains_tox(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert r"^tox\b" in strategy.blacklist_patterns

    def test_contains_pylint(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert r"^pylint\b" in strategy.blacklist_patterns

    def test_contains_flake8(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert r"^flake8\b" in strategy.blacklist_patterns

    def test_pytest_pattern_matches(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert re.search(r"^pytest\b", "pytest tests/ -v", re.IGNORECASE)

    def test_mypy_pattern_matches(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert re.search(r"^mypy\b", "mypy src/", re.IGNORECASE)

    def test_ruff_check_matches(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert re.search(r"^ruff\s+check\b", "ruff check src/", re.IGNORECASE)

    def test_all_patterns_valid_regex(self, strategy: PythonPipeBlockerStrategy) -> None:
        for pattern in strategy.blacklist_patterns:
            re.compile(pattern, re.IGNORECASE)


class TestPythonStrategyAcceptanceTests:
    def test_returns_list(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: PythonPipeBlockerStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) > 0
