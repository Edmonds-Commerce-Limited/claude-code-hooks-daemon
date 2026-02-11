"""Tests for Rust QA suppression strategy."""

import re

from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.rust_strategy import (
    RustQaSuppressionStrategy,
)


def _allow_attr_text() -> str:
    return "#[" + "allow("


def test_implements_protocol() -> None:
    """RustQaSuppressionStrategy should implement protocol."""
    strategy = RustQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_language_name() -> None:
    """Language name should be 'Rust'."""
    strategy = RustQaSuppressionStrategy()
    assert strategy.language_name == "Rust"


def test_extensions() -> None:
    """Extensions should be ('.rs',)."""
    strategy = RustQaSuppressionStrategy()
    assert strategy.extensions == (".rs",)


def test_forbidden_patterns_not_empty() -> None:
    """Should have forbidden patterns defined."""
    strategy = RustQaSuppressionStrategy()
    assert len(strategy.forbidden_patterns) > 0


def test_forbidden_patterns_are_valid_regex() -> None:
    """All forbidden patterns should be valid regex."""
    strategy = RustQaSuppressionStrategy()
    for pattern in strategy.forbidden_patterns:
        re.compile(pattern)


def test_matches_allow_attribute() -> None:
    """Should match allow attribute."""
    strategy = RustQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"{_allow_attr_text()}unused_variables)]"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_skip_directories_not_empty() -> None:
    """Should have skip directories defined."""
    strategy = RustQaSuppressionStrategy()
    assert len(strategy.skip_directories) > 0


def test_tool_names_not_empty() -> None:
    """Should have tool names defined."""
    strategy = RustQaSuppressionStrategy()
    assert len(strategy.tool_names) > 0


def test_tool_docs_urls_not_empty() -> None:
    """Should have tool docs URLs defined."""
    strategy = RustQaSuppressionStrategy()
    assert len(strategy.tool_docs_urls) > 0


def test_acceptance_tests_provided() -> None:
    """Should provide at least one acceptance test."""
    strategy = RustQaSuppressionStrategy()
    tests = strategy.get_acceptance_tests()
    assert len(tests) > 0
