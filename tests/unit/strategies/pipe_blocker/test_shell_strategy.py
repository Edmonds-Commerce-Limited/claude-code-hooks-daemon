"""Tests for ShellPipeBlockerStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.pipe_blocker.shell_strategy import (
    ShellPipeBlockerStrategy,
)


@pytest.fixture
def strategy() -> ShellPipeBlockerStrategy:
    return ShellPipeBlockerStrategy()


class TestShellStrategyProperties:
    def test_language_name(self, strategy: ShellPipeBlockerStrategy) -> None:
        assert strategy.language_name == "Shell"

    def test_blacklist_patterns_is_tuple(self, strategy: ShellPipeBlockerStrategy) -> None:
        assert isinstance(strategy.blacklist_patterns, tuple)

    def test_blacklist_patterns_non_empty(self, strategy: ShellPipeBlockerStrategy) -> None:
        assert len(strategy.blacklist_patterns) > 0


class TestShellStrategyBlacklistPatterns:
    def test_contains_shellcheck(self, strategy: ShellPipeBlockerStrategy) -> None:
        assert r"^shellcheck\b" in strategy.blacklist_patterns

    def test_shellcheck_matches(self, strategy: ShellPipeBlockerStrategy) -> None:
        assert re.search(r"^shellcheck\b", "shellcheck script.sh", re.IGNORECASE)

    def test_all_patterns_valid_regex(self, strategy: ShellPipeBlockerStrategy) -> None:
        for pattern in strategy.blacklist_patterns:
            re.compile(pattern, re.IGNORECASE)


class TestShellStrategyAcceptanceTests:
    def test_returns_list(self, strategy: ShellPipeBlockerStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: ShellPipeBlockerStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) > 0
