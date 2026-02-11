"""Tests for Kotlin QA suppression strategy."""

import re

from claude_code_hooks_daemon.strategies.qa_suppression.kotlin_strategy import (
    KotlinQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)


def _suppress_text() -> str:
    return "@Suppress" + "("


def _suppress_warnings_text() -> str:
    return "@Suppress" + "Warnings"


def test_implements_protocol() -> None:
    """KotlinQaSuppressionStrategy should implement protocol."""
    strategy = KotlinQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_language_name() -> None:
    """Language name should be 'Kotlin'."""
    strategy = KotlinQaSuppressionStrategy()
    assert strategy.language_name == "Kotlin"


def test_extensions() -> None:
    """Extensions should be ('.kt',)."""
    strategy = KotlinQaSuppressionStrategy()
    assert strategy.extensions == (".kt",)


def test_forbidden_patterns_not_empty() -> None:
    """Should have forbidden patterns defined."""
    strategy = KotlinQaSuppressionStrategy()
    assert len(strategy.forbidden_patterns) > 0


def test_forbidden_patterns_are_valid_regex() -> None:
    """All forbidden patterns should be valid regex."""
    strategy = KotlinQaSuppressionStrategy()
    for pattern in strategy.forbidden_patterns:
        re.compile(pattern)


def test_matches_suppress_annotation() -> None:
    """Should match Suppress annotation."""
    strategy = KotlinQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f'{_suppress_text()}"UNCHECKED_CAST")'
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_matches_suppress_warnings() -> None:
    """Should match SuppressWarnings annotation."""
    strategy = KotlinQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f'{_suppress_warnings_text()}("unchecked")'
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_skip_directories_not_empty() -> None:
    """Should have skip directories defined."""
    strategy = KotlinQaSuppressionStrategy()
    assert len(strategy.skip_directories) > 0


def test_tool_names_not_empty() -> None:
    """Should have tool names defined."""
    strategy = KotlinQaSuppressionStrategy()
    assert len(strategy.tool_names) > 0


def test_tool_docs_urls_not_empty() -> None:
    """Should have tool docs URLs defined."""
    strategy = KotlinQaSuppressionStrategy()
    assert len(strategy.tool_docs_urls) > 0


def test_acceptance_tests_provided() -> None:
    """Should provide at least one acceptance test."""
    strategy = KotlinQaSuppressionStrategy()
    tests = strategy.get_acceptance_tests()
    assert len(tests) > 0
