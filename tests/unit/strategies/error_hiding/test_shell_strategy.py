"""Tests for ShellErrorHidingStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.error_hiding.shell_strategy import (
    ShellErrorHidingStrategy,
)


@pytest.fixture
def strategy() -> ShellErrorHidingStrategy:
    return ShellErrorHidingStrategy()


class TestShellStrategyProperties:
    def test_language_name(self, strategy: ShellErrorHidingStrategy) -> None:
        assert strategy.language_name == "Shell"

    def test_extensions_is_tuple(self, strategy: ShellErrorHidingStrategy) -> None:
        assert isinstance(strategy.extensions, tuple)

    def test_extensions_includes_sh(self, strategy: ShellErrorHidingStrategy) -> None:
        assert ".sh" in strategy.extensions

    def test_extensions_includes_bash(self, strategy: ShellErrorHidingStrategy) -> None:
        assert ".bash" in strategy.extensions

    def test_patterns_is_tuple(self, strategy: ShellErrorHidingStrategy) -> None:
        assert isinstance(strategy.patterns, tuple)

    def test_patterns_non_empty(self, strategy: ShellErrorHidingStrategy) -> None:
        assert len(strategy.patterns) > 0


class TestShellStrategyPatternContent:
    def test_all_patterns_have_name(self, strategy: ShellErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.name, f"Pattern missing name: {p}"

    def test_all_patterns_have_regex(self, strategy: ShellErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.regex, f"Pattern missing regex: {p}"

    def test_all_patterns_have_example(self, strategy: ShellErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.example, f"Pattern missing example: {p}"

    def test_all_patterns_have_suggestion(self, strategy: ShellErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.suggestion, f"Pattern missing suggestion: {p}"

    def test_all_patterns_valid_regex(self, strategy: ShellErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            re.compile(p.regex)  # Should not raise

    def test_contains_or_true_pattern(self, strategy: ShellErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "|| true" in names

    def test_contains_or_colon_pattern(self, strategy: ShellErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "|| :" in names

    def test_contains_set_plus_e_pattern(self, strategy: ShellErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "set +e" in names

    def test_contains_ampersand_dev_null_pattern(self, strategy: ShellErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "&>/dev/null" in names

    def test_contains_redirect_dev_null_pattern(self, strategy: ShellErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert ">/dev/null 2>&1" in names

    def test_contains_trap_err_pattern(self, strategy: ShellErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "trap '' ERR" in names


class TestShellStrategyPatternMatching:
    def test_or_true_matches(self, strategy: ShellErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "|| true")
        assert re.search(pattern.regex, "some_command || true", re.MULTILINE)

    def test_or_true_matches_with_spaces(self, strategy: ShellErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "|| true")
        assert re.search(pattern.regex, "cmd ||   true", re.MULTILINE)

    def test_or_colon_matches(self, strategy: ShellErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "|| :")
        assert re.search(pattern.regex, "cmd || :\n", re.MULTILINE)

    def test_set_plus_e_matches(self, strategy: ShellErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "set +e")
        assert re.search(pattern.regex, "set +e", re.MULTILINE)

    def test_ampersand_dev_null_matches(self, strategy: ShellErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "&>/dev/null")
        assert re.search(pattern.regex, "cmd &>/dev/null", re.MULTILINE)

    def test_redirect_dev_null_matches(self, strategy: ShellErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == ">/dev/null 2>&1")
        assert re.search(pattern.regex, "cmd >/dev/null 2>&1", re.MULTILINE)

    def test_trap_err_matches(self, strategy: ShellErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "trap '' ERR")
        assert re.search(pattern.regex, "trap '' ERR", re.MULTILINE)

    def test_or_true_does_not_match_truefalse(self, strategy: ShellErrorHidingStrategy) -> None:
        # "|| truevalue" should NOT match because of \b
        pattern = next(p for p in strategy.patterns if p.name == "|| true")
        assert not re.search(pattern.regex, "cmd || truevalue", re.MULTILINE)


class TestShellStrategyAcceptanceTests:
    def test_returns_list(self, strategy: ShellErrorHidingStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: ShellErrorHidingStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) >= 2

    def test_has_blocking_test(self, strategy: ShellErrorHidingStrategy) -> None:
        from claude_code_hooks_daemon.core import TestType

        tests = strategy.get_acceptance_tests()
        assert any(t.test_type == TestType.BLOCKING for t in tests)

    def test_has_allow_test(self, strategy: ShellErrorHidingStrategy) -> None:
        from claude_code_hooks_daemon.core import TestType

        tests = strategy.get_acceptance_tests()
        assert any(t.test_type == TestType.ADVISORY for t in tests)
