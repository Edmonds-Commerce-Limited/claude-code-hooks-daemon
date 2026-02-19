"""Tests for JavaErrorHidingStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.error_hiding.java_strategy import (
    JavaErrorHidingStrategy,
)


@pytest.fixture
def strategy() -> JavaErrorHidingStrategy:
    return JavaErrorHidingStrategy()


class TestJavaStrategyProperties:
    def test_language_name(self, strategy: JavaErrorHidingStrategy) -> None:
        assert strategy.language_name == "Java"

    def test_extensions_is_tuple(self, strategy: JavaErrorHidingStrategy) -> None:
        assert isinstance(strategy.extensions, tuple)

    def test_extensions_includes_java(self, strategy: JavaErrorHidingStrategy) -> None:
        assert ".java" in strategy.extensions

    def test_patterns_is_tuple(self, strategy: JavaErrorHidingStrategy) -> None:
        assert isinstance(strategy.patterns, tuple)

    def test_patterns_non_empty(self, strategy: JavaErrorHidingStrategy) -> None:
        assert len(strategy.patterns) > 0


class TestJavaStrategyPatternContent:
    def test_all_patterns_have_name(self, strategy: JavaErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.name

    def test_all_patterns_have_regex(self, strategy: JavaErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.regex

    def test_all_patterns_have_example(self, strategy: JavaErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.example

    def test_all_patterns_have_suggestion(self, strategy: JavaErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.suggestion

    def test_all_patterns_valid_regex(self, strategy: JavaErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            re.compile(p.regex)

    def test_contains_empty_catch_block(self, strategy: JavaErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "empty catch block" in names


class TestJavaStrategyPatternMatching:
    def test_empty_catch_block_matches(self, strategy: JavaErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty catch block")
        assert re.search(pattern.regex, "catch (Exception e) {}")

    def test_empty_catch_block_with_spaces(self, strategy: JavaErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty catch block")
        assert re.search(pattern.regex, "catch (IOException e) {  }")

    def test_catch_with_body_does_not_match(self, strategy: JavaErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty catch block")
        assert not re.search(pattern.regex, "catch (Exception e) { log.error(e.getMessage()); }")

    def test_catch_with_generic_type_matches(self, strategy: JavaErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty catch block")
        assert re.search(pattern.regex, "catch (RuntimeException ex) {}")


class TestJavaStrategyAcceptanceTests:
    def test_returns_list(self, strategy: JavaErrorHidingStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: JavaErrorHidingStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) >= 2

    def test_has_blocking_test(self, strategy: JavaErrorHidingStrategy) -> None:
        from claude_code_hooks_daemon.core import TestType

        tests = strategy.get_acceptance_tests()
        assert any(t.test_type == TestType.BLOCKING for t in tests)

    def test_has_allow_test(self, strategy: JavaErrorHidingStrategy) -> None:
        from claude_code_hooks_daemon.core import TestType

        tests = strategy.get_acceptance_tests()
        assert any(t.test_type == TestType.ADVISORY for t in tests)
