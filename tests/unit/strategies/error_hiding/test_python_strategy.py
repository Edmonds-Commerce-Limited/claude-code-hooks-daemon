"""Tests for PythonErrorHidingStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.error_hiding.python_strategy import (
    PythonErrorHidingStrategy,
)


@pytest.fixture
def strategy() -> PythonErrorHidingStrategy:
    return PythonErrorHidingStrategy()


class TestPythonStrategyProperties:
    def test_language_name(self, strategy: PythonErrorHidingStrategy) -> None:
        assert strategy.language_name == "Python"

    def test_extensions_is_tuple(self, strategy: PythonErrorHidingStrategy) -> None:
        assert isinstance(strategy.extensions, tuple)

    def test_extensions_includes_py(self, strategy: PythonErrorHidingStrategy) -> None:
        assert ".py" in strategy.extensions

    def test_patterns_is_tuple(self, strategy: PythonErrorHidingStrategy) -> None:
        assert isinstance(strategy.patterns, tuple)

    def test_patterns_non_empty(self, strategy: PythonErrorHidingStrategy) -> None:
        assert len(strategy.patterns) > 0


class TestPythonStrategyPatternContent:
    def test_all_patterns_have_name(self, strategy: PythonErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.name

    def test_all_patterns_have_regex(self, strategy: PythonErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.regex

    def test_all_patterns_have_example(self, strategy: PythonErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.example

    def test_all_patterns_have_suggestion(self, strategy: PythonErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            assert p.suggestion

    def test_all_patterns_valid_regex(self, strategy: PythonErrorHidingStrategy) -> None:
        for p in strategy.patterns:
            re.compile(p.regex, re.MULTILINE)

    def test_contains_bare_except_pass(self, strategy: PythonErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "bare except: pass" in names

    def test_contains_except_exception_pass(self, strategy: PythonErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "except Exception: pass" in names

    def test_contains_bare_except_ellipsis(self, strategy: PythonErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "bare except: ..." in names

    def test_contains_except_exception_ellipsis(self, strategy: PythonErrorHidingStrategy) -> None:
        names = {p.name for p in strategy.patterns}
        assert "except Exception: ..." in names


class TestPythonStrategyPatternMatching:
    def test_bare_except_pass_matches(self, strategy: PythonErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "bare except: pass")
        content = "except:\n    pass\n"
        assert re.search(pattern.regex, content, re.MULTILINE)

    def test_except_exception_pass_matches(self, strategy: PythonErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "except Exception: pass")
        content = "except Exception:\n    pass\n"
        assert re.search(pattern.regex, content, re.MULTILINE)

    def test_except_valueerror_pass_matches(self, strategy: PythonErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "except Exception: pass")
        content = "except ValueError:\n    pass\n"
        assert re.search(pattern.regex, content, re.MULTILINE)

    def test_bare_except_ellipsis_matches(self, strategy: PythonErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "bare except: ...")
        content = "except:\n    ...\n"
        assert re.search(pattern.regex, content, re.MULTILINE)

    def test_except_exception_ellipsis_matches(self, strategy: PythonErrorHidingStrategy) -> None:
        pattern = next(p for p in strategy.patterns if p.name == "except Exception: ...")
        content = "except Exception:\n    ...\n"
        assert re.search(pattern.regex, content, re.MULTILINE)

    def test_proper_except_does_not_match_bare_pass(
        self, strategy: PythonErrorHidingStrategy
    ) -> None:
        # A proper handler with actual body should not match bare except: pass
        pattern = next(p for p in strategy.patterns if p.name == "bare except: pass")
        content = "except:\n    logger.error('failed')\n"
        assert not re.search(pattern.regex, content, re.MULTILINE)


class TestPythonStrategyAcceptanceTests:
    def test_returns_list(self, strategy: PythonErrorHidingStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: PythonErrorHidingStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) >= 2

    def test_has_blocking_test(self, strategy: PythonErrorHidingStrategy) -> None:
        from claude_code_hooks_daemon.core import TestType

        tests = strategy.get_acceptance_tests()
        assert any(t.test_type == TestType.BLOCKING for t in tests)

    def test_has_allow_test(self, strategy: PythonErrorHidingStrategy) -> None:
        from claude_code_hooks_daemon.core import TestType

        tests = strategy.get_acceptance_tests()
        assert any(t.test_type == TestType.ADVISORY for t in tests)
