"""Tests for GoErrorHidingStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.error_hiding.go_strategy import (
    GoErrorHidingStrategy,
)


@pytest.fixture
def strategy() -> GoErrorHidingStrategy:
    return GoErrorHidingStrategy()


class TestGoStrategyProperties:
    def test_language_name(self, strategy: GoErrorHidingStrategy) -> None:
        assert strategy.language_name == "Go"

    def test_extensions_is_tuple(self, strategy: GoErrorHidingStrategy) -> None:
        assert isinstance(strategy.extensions, tuple)

    def test_extensions_includes_go(self, strategy: GoErrorHidingStrategy) -> None:
        assert ".go" in strategy.extensions

    def test_patterns_is_tuple(self, strategy: GoErrorHidingStrategy) -> None:
        assert isinstance(strategy.patterns, tuple)

    def test_patterns_non_empty(self, strategy: GoErrorHidingStrategy) -> None:
        assert len(strategy.patterns) > 0


class TestGoStrategyPatternContent:
    def test_all_patterns_have_name(self, strategy: GoErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.name

    def test_all_patterns_have_regex(self, strategy: GoErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.regex

    def test_all_patterns_have_example(self, strategy: GoErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.example

    def test_all_patterns_have_suggestion(self, strategy: GoErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.suggestion

    def test_all_patterns_valid_regex(self, strategy: GoErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            re.compile(p.regex)

    def test_contains_empty_error_check(self, strategy: GoErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "empty error check" in names

    def test_contains_blank_identifier_discards_error(
        self, strategy: GoErrorHidingStrategy
    ) -> None:
        names = {p.name for p in strategy.patterns}
        assert "blank identifier discards error" in names


class TestGoStrategyPatternMatching:
    def test_empty_error_check_matches(self, strategy: GoErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty error check")
        assert re.search(pattern.regex, "if err != nil {}")

    def test_empty_error_check_with_spaces(self, strategy: GoErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty error check")
        assert re.search(pattern.regex, "if err != nil {  }")

    def test_blank_identifier_discards_error_matches(self, strategy: GoErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "blank identifier discards error")
        assert re.search(pattern.regex, "result, _ := riskyCall()")

    def test_error_check_with_body_does_not_match(self, strategy: GoErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty error check")
        assert not re.search(pattern.regex, "if err != nil { return err }")

    def test_blank_identifier_on_non_error_does_not_match(
        self, strategy: GoErrorHidingStrategy
    ) -> None:
        # Regular blank identifier on first value (not error) should not match
        # e.g. "_ = someFunc()" - no comma, no err
        pattern = next(p for p in strategy.patterns if p.name == "blank identifier discards error")
        # This specific pattern targets "_, err" or "err, _" patterns
        assert not re.search(pattern.regex, "_ = someFunc()")


class TestGoStrategyAcceptanceTests:
    def test_returns_list(self, strategy: GoErrorHidingStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: GoErrorHidingStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) >= 2

    def test_has_blocking_test(self, strategy: GoErrorHidingStrategy) -> None:
        from claude_code_hooks_daemon.core import TestType

        tests = strategy.get_acceptance_tests()
        assert any(t.test_type == TestType.BLOCKING for t in tests)

    def test_has_allow_test(self, strategy: GoErrorHidingStrategy) -> None:
        from claude_code_hooks_daemon.core import TestType

        tests = strategy.get_acceptance_tests()
        assert any(t.test_type == TestType.ADVISORY for t in tests)
