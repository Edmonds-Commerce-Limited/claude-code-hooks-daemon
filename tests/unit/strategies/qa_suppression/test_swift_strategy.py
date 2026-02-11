"""Tests for Swift QA suppression strategy."""

import re

from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.swift_strategy import (
    SwiftQaSuppressionStrategy,
)


def _swiftlint_disable_text() -> str:
    return "// swiftlint" + ":disable"


def test_implements_protocol() -> None:
    """SwiftQaSuppressionStrategy should implement protocol."""
    strategy = SwiftQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_language_name() -> None:
    """Language name should be 'Swift'."""
    strategy = SwiftQaSuppressionStrategy()
    assert strategy.language_name == "Swift"


def test_extensions() -> None:
    """Extensions should be ('.swift',)."""
    strategy = SwiftQaSuppressionStrategy()
    assert strategy.extensions == (".swift",)


def test_forbidden_patterns_not_empty() -> None:
    """Should have forbidden patterns defined."""
    strategy = SwiftQaSuppressionStrategy()
    assert len(strategy.forbidden_patterns) > 0


def test_forbidden_patterns_are_valid_regex() -> None:
    """All forbidden patterns should be valid regex."""
    strategy = SwiftQaSuppressionStrategy()
    for pattern in strategy.forbidden_patterns:
        re.compile(pattern)


def test_matches_swiftlint_disable() -> None:
    """Should match swiftlint:disable comments."""
    strategy = SwiftQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"{_swiftlint_disable_text()} force_cast"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_skip_directories_not_empty() -> None:
    """Should have skip directories defined."""
    strategy = SwiftQaSuppressionStrategy()
    assert len(strategy.skip_directories) > 0


def test_tool_names_not_empty() -> None:
    """Should have tool names defined."""
    strategy = SwiftQaSuppressionStrategy()
    assert len(strategy.tool_names) > 0


def test_tool_docs_urls_not_empty() -> None:
    """Should have tool docs URLs defined."""
    strategy = SwiftQaSuppressionStrategy()
    assert len(strategy.tool_docs_urls) > 0


def test_acceptance_tests_provided() -> None:
    """Should provide at least one acceptance test."""
    strategy = SwiftQaSuppressionStrategy()
    tests = strategy.get_acceptance_tests()
    assert len(tests) > 0
