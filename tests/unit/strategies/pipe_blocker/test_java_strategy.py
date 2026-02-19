"""Tests for JavaPipeBlockerStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.pipe_blocker.java_strategy import JavaPipeBlockerStrategy


@pytest.fixture
def strategy() -> JavaPipeBlockerStrategy:
    return JavaPipeBlockerStrategy()


class TestJavaStrategyProperties:
    def test_language_name(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert strategy.language_name == "Java"

    def test_blacklist_patterns_is_tuple(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert isinstance(strategy.blacklist_patterns, tuple)

    def test_blacklist_patterns_non_empty(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert len(strategy.blacklist_patterns) > 0


class TestJavaStrategyBlacklistPatterns:
    def test_contains_mvn(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert r"^mvn\b" in strategy.blacklist_patterns

    def test_contains_gradle(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert r"^gradle\b" in strategy.blacklist_patterns

    def test_contains_gradlew(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert r"^\./gradlew\b" in strategy.blacklist_patterns

    def test_contains_javac(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert r"^javac\b" in strategy.blacklist_patterns

    def test_mvn_matches(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert re.search(r"^mvn\b", "mvn test", re.IGNORECASE)

    def test_gradle_matches(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert re.search(r"^gradle\b", "gradle build", re.IGNORECASE)

    def test_gradlew_matches(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert re.search(r"^\./gradlew\b", "./gradlew test", re.IGNORECASE)

    def test_javac_matches(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert re.search(r"^javac\b", "javac Main.java", re.IGNORECASE)

    def test_all_patterns_valid_regex(self, strategy: JavaPipeBlockerStrategy) -> None:
        for pattern in strategy.blacklist_patterns:
            re.compile(pattern, re.IGNORECASE)


class TestJavaStrategyAcceptanceTests:
    def test_returns_list(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: JavaPipeBlockerStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) > 0
