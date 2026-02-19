"""Tests for JavaScriptPipeBlockerStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.pipe_blocker.javascript_strategy import (
    JavaScriptPipeBlockerStrategy,
)


@pytest.fixture
def strategy() -> JavaScriptPipeBlockerStrategy:
    return JavaScriptPipeBlockerStrategy()


class TestJavaScriptStrategyProperties:
    def test_language_name(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert strategy.language_name == "JavaScript"

    def test_blacklist_patterns_is_tuple(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert isinstance(strategy.blacklist_patterns, tuple)

    def test_blacklist_patterns_non_empty(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert len(strategy.blacklist_patterns) > 0


class TestJavaScriptStrategyBlacklistPatterns:
    def test_contains_npm_test(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert r"^npm\s+test\b" in strategy.blacklist_patterns

    def test_contains_npm_run(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert r"^npm\s+run\b" in strategy.blacklist_patterns

    def test_contains_npm_build(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert r"^npm\s+build\b" in strategy.blacklist_patterns

    def test_contains_npm_audit(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert r"^npm\s+audit\b" in strategy.blacklist_patterns

    def test_contains_jest(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert r"^jest\b" in strategy.blacklist_patterns

    def test_contains_vitest(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert r"^vitest\b" in strategy.blacklist_patterns

    def test_contains_eslint(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert r"^eslint\b" in strategy.blacklist_patterns

    def test_contains_tsc(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert r"^tsc\b" in strategy.blacklist_patterns

    def test_contains_webpack(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert r"^webpack\b" in strategy.blacklist_patterns

    def test_contains_yarn_test(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert r"^yarn\s+test\b" in strategy.blacklist_patterns

    def test_npm_test_matches(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert re.search(r"^npm\s+test\b", "npm test", re.IGNORECASE)

    def test_npm_run_matches(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert re.search(r"^npm\s+run\b", "npm run build", re.IGNORECASE)

    def test_jest_matches(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert re.search(r"^jest\b", "jest --coverage", re.IGNORECASE)

    def test_all_patterns_valid_regex(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        for pattern in strategy.blacklist_patterns:
            re.compile(pattern, re.IGNORECASE)


class TestJavaScriptStrategyAcceptanceTests:
    def test_returns_list(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: JavaScriptPipeBlockerStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) > 0
