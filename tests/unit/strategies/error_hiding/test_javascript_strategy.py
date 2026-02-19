"""Tests for JavaScriptErrorHidingStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.error_hiding.javascript_strategy import (
    JavaScriptErrorHidingStrategy,
)


@pytest.fixture
def strategy() -> JavaScriptErrorHidingStrategy:
    return JavaScriptErrorHidingStrategy()


class TestJavaScriptStrategyProperties:
    def test_language_name(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        assert strategy.language_name == "JavaScript/TypeScript"

    def test_extensions_is_tuple(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        assert isinstance(strategy.extensions, tuple)

    def test_extensions_includes_js(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        assert ".js" in strategy.extensions

    def test_extensions_includes_ts(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        assert ".ts" in strategy.extensions

    def test_extensions_includes_jsx(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        assert ".jsx" in strategy.extensions

    def test_extensions_includes_tsx(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        assert ".tsx" in strategy.extensions

    def test_extensions_includes_mjs(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        assert ".mjs" in strategy.extensions

    def test_extensions_includes_cjs(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        assert ".cjs" in strategy.extensions

    def test_patterns_is_tuple(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        assert isinstance(strategy.patterns, tuple)

    def test_patterns_non_empty(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        assert len(strategy.patterns) > 0


class TestJavaScriptStrategyPatternContent:
    def test_all_patterns_have_name(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.name

    def test_all_patterns_have_regex(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.regex

    def test_all_patterns_have_example(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.example

    def test_all_patterns_have_suggestion(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.suggestion

    def test_all_patterns_valid_regex(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            re.compile(p.regex)

    def test_contains_empty_catch_block(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "empty catch block" in names

    def test_contains_empty_promise_catch(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "empty promise .catch" in names


class TestJavaScriptStrategyPatternMatching:
    def test_empty_catch_block_matches(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty catch block")
        assert re.search(pattern.regex, "catch (e) {}")

    def test_empty_catch_block_with_spaces(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty catch block")
        assert re.search(pattern.regex, "catch (err) {  }")

    def test_empty_promise_catch_arrow_matches(
        self, strategy: JavaScriptErrorHidingStrategy
    ) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty promise .catch")
        assert re.search(pattern.regex, ".catch(() => {})")

    def test_empty_promise_catch_named_param_matches(
        self, strategy: JavaScriptErrorHidingStrategy
    ) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty promise .catch")
        assert re.search(pattern.regex, ".catch(e => {})")

    def test_catch_with_body_does_not_match(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty catch block")
        assert not re.search(pattern.regex, "catch (e) { console.error(e); }")

    def test_promise_catch_with_body_does_not_match(
        self, strategy: JavaScriptErrorHidingStrategy
    ) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "empty promise .catch")
        assert not re.search(pattern.regex, ".catch(e => { console.error(e); })")


class TestJavaScriptStrategyAcceptanceTests:
    def test_returns_list(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) >= 2

    def test_has_blocking_test(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        from claude_code_hooks_daemon.core import TestType

        tests = strategy.get_acceptance_tests()
        assert any(t.test_type == TestType.BLOCKING for t in tests)

    def test_has_allow_test(self, strategy: JavaScriptErrorHidingStrategy) -> None:
        from claude_code_hooks_daemon.core import TestType

        tests = strategy.get_acceptance_tests()
        assert any(t.test_type == TestType.ADVISORY for t in tests)
