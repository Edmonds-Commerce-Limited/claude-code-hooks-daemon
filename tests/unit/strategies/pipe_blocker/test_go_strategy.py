"""Tests for GoPipeBlockerStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.pipe_blocker.go_strategy import GoPipeBlockerStrategy


@pytest.fixture
def strategy() -> GoPipeBlockerStrategy:
    return GoPipeBlockerStrategy()


class TestGoStrategyProperties:
    def test_language_name(self, strategy: GoPipeBlockerStrategy) -> None:
        assert strategy.language_name == "Go"

    def test_blacklist_patterns_is_tuple(self, strategy: GoPipeBlockerStrategy) -> None:
        assert isinstance(strategy.blacklist_patterns, tuple)

    def test_blacklist_patterns_non_empty(self, strategy: GoPipeBlockerStrategy) -> None:
        assert len(strategy.blacklist_patterns) > 0


class TestGoStrategyBlacklistPatterns:
    def test_contains_go_test(self, strategy: GoPipeBlockerStrategy) -> None:
        assert r"^go\s+test\b" in strategy.blacklist_patterns

    def test_contains_go_build(self, strategy: GoPipeBlockerStrategy) -> None:
        assert r"^go\s+build\b" in strategy.blacklist_patterns

    def test_contains_go_vet(self, strategy: GoPipeBlockerStrategy) -> None:
        assert r"^go\s+vet\b" in strategy.blacklist_patterns

    def test_go_test_matches(self, strategy: GoPipeBlockerStrategy) -> None:
        assert re.search(r"^go\s+test\b", "go test ./...", re.IGNORECASE)

    def test_go_build_matches(self, strategy: GoPipeBlockerStrategy) -> None:
        assert re.search(r"^go\s+build\b", "go build ./cmd/app", re.IGNORECASE)

    def test_go_vet_matches(self, strategy: GoPipeBlockerStrategy) -> None:
        assert re.search(r"^go\s+vet\b", "go vet ./...", re.IGNORECASE)

    def test_all_patterns_valid_regex(self, strategy: GoPipeBlockerStrategy) -> None:
        for pattern in strategy.blacklist_patterns:
            re.compile(pattern, re.IGNORECASE)


class TestGoStrategyAcceptanceTests:
    def test_returns_list(self, strategy: GoPipeBlockerStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: GoPipeBlockerStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) > 0
