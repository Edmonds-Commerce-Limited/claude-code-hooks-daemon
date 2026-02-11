"""Tests for Java QA suppression strategy."""

import re

from claude_code_hooks_daemon.strategies.qa_suppression.java_strategy import (
    JavaQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)


def _suppress_warnings_text() -> str:
    return "@Suppress" + "Warnings"


def _checkstyle_off_text() -> str:
    return "// CHECKSTYLE" + ":OFF"


def test_implements_protocol() -> None:
    """JavaQaSuppressionStrategy should implement protocol."""
    strategy = JavaQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_language_name() -> None:
    """Language name should be 'Java'."""
    strategy = JavaQaSuppressionStrategy()
    assert strategy.language_name == "Java"


def test_extensions() -> None:
    """Extensions should be ('.java',)."""
    strategy = JavaQaSuppressionStrategy()
    assert strategy.extensions == (".java",)


def test_forbidden_patterns_not_empty() -> None:
    """Should have forbidden patterns defined."""
    strategy = JavaQaSuppressionStrategy()
    assert len(strategy.forbidden_patterns) > 0


def test_forbidden_patterns_are_valid_regex() -> None:
    """All forbidden patterns should be valid regex."""
    strategy = JavaQaSuppressionStrategy()
    for pattern in strategy.forbidden_patterns:
        re.compile(pattern)


def test_matches_suppress_warnings() -> None:
    """Should match SuppressWarnings annotation."""
    strategy = JavaQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f'{_suppress_warnings_text()}("unchecked")'
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_matches_checkstyle_off() -> None:
    """Should match CHECKSTYLE:OFF comment."""
    strategy = JavaQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = _checkstyle_off_text()
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_skip_directories_not_empty() -> None:
    """Should have skip directories defined."""
    strategy = JavaQaSuppressionStrategy()
    assert len(strategy.skip_directories) > 0


def test_tool_names_not_empty() -> None:
    """Should have tool names defined."""
    strategy = JavaQaSuppressionStrategy()
    assert len(strategy.tool_names) > 0


def test_tool_docs_urls_not_empty() -> None:
    """Should have tool docs URLs defined."""
    strategy = JavaQaSuppressionStrategy()
    assert len(strategy.tool_docs_urls) > 0


def test_acceptance_tests_provided() -> None:
    """Should provide at least one acceptance test."""
    strategy = JavaQaSuppressionStrategy()
    tests = strategy.get_acceptance_tests()
    assert len(tests) > 0
