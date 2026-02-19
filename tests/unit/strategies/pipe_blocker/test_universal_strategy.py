"""Tests for UniversalPipeBlockerStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.pipe_blocker.universal_strategy import (
    UniversalPipeBlockerStrategy,
)


@pytest.fixture
def strategy() -> UniversalPipeBlockerStrategy:
    return UniversalPipeBlockerStrategy()


class TestUniversalStrategyProperties:
    def test_language_name(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert strategy.language_name == "Universal"

    def test_blacklist_patterns_is_tuple(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert isinstance(strategy.blacklist_patterns, tuple)

    def test_blacklist_patterns_non_empty(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert len(strategy.blacklist_patterns) > 0

    def test_all_patterns_are_strings(self, strategy: UniversalPipeBlockerStrategy) -> None:
        for p in strategy.blacklist_patterns:
            assert isinstance(p, str)


class TestUniversalStrategyBlacklistPatterns:
    def test_contains_make_pattern(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert r"^make\b" in strategy.blacklist_patterns

    def test_contains_cmake_pattern(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert r"^cmake\b" in strategy.blacklist_patterns

    def test_contains_docker_build_pattern(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert r"^docker\s+build\b" in strategy.blacklist_patterns

    def test_contains_kubectl_pattern(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert r"^kubectl\b" in strategy.blacklist_patterns

    def test_contains_terraform_pattern(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert r"^terraform\b" in strategy.blacklist_patterns

    def test_contains_helm_pattern(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert r"^helm\b" in strategy.blacklist_patterns

    def test_make_pattern_matches(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert re.search(r"^make\b", "make build", re.IGNORECASE)

    def test_cmake_pattern_matches(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert re.search(r"^cmake\b", "cmake ..", re.IGNORECASE)

    def test_docker_build_matches(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert re.search(r"^docker\s+build\b", "docker build -t myimage .", re.IGNORECASE)

    def test_kubectl_matches(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert re.search(r"^kubectl\b", "kubectl get pods", re.IGNORECASE)

    def test_all_patterns_valid_regex(self, strategy: UniversalPipeBlockerStrategy) -> None:
        for pattern in strategy.blacklist_patterns:
            re.compile(pattern, re.IGNORECASE)


class TestUniversalStrategyAcceptanceTests:
    def test_returns_list(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: UniversalPipeBlockerStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) > 0
