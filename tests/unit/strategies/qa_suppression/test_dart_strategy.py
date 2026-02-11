"""Tests for Dart QA suppression strategy."""

import re

from claude_code_hooks_daemon.strategies.qa_suppression.dart_strategy import (
    DartQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)


def _ignore_text() -> str:
    return "// ignore" + ":"


def _ignore_for_file_text() -> str:
    return "// ignore" + "_for_file:"


def test_implements_protocol() -> None:
    """DartQaSuppressionStrategy should implement protocol."""
    strategy = DartQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_language_name() -> None:
    """Language name should be 'Dart'."""
    strategy = DartQaSuppressionStrategy()
    assert strategy.language_name == "Dart"


def test_extensions() -> None:
    """Extensions should be ('.dart',)."""
    strategy = DartQaSuppressionStrategy()
    assert strategy.extensions == (".dart",)


def test_forbidden_patterns_not_empty() -> None:
    """Should have forbidden patterns defined."""
    strategy = DartQaSuppressionStrategy()
    assert len(strategy.forbidden_patterns) > 0


def test_forbidden_patterns_are_valid_regex() -> None:
    """All forbidden patterns should be valid regex."""
    strategy = DartQaSuppressionStrategy()
    for pattern in strategy.forbidden_patterns:
        re.compile(pattern)


def test_matches_ignore_directive() -> None:
    """Should match ignore: directive."""
    strategy = DartQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"var x = 1; {_ignore_text()} unused_local_variable"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_matches_ignore_for_file() -> None:
    """Should match ignore_for_file: directive."""
    strategy = DartQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"{_ignore_for_file_text()} unused_import"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_skip_directories_not_empty() -> None:
    """Should have skip directories defined."""
    strategy = DartQaSuppressionStrategy()
    assert len(strategy.skip_directories) > 0


def test_tool_names_not_empty() -> None:
    """Should have tool names defined."""
    strategy = DartQaSuppressionStrategy()
    assert len(strategy.tool_names) > 0


def test_tool_docs_urls_not_empty() -> None:
    """Should have tool docs URLs defined."""
    strategy = DartQaSuppressionStrategy()
    assert len(strategy.tool_docs_urls) > 0


def test_acceptance_tests_provided() -> None:
    """Should provide at least one acceptance test."""
    strategy = DartQaSuppressionStrategy()
    tests = strategy.get_acceptance_tests()
    assert len(tests) > 0
