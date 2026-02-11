"""Tests for C# QA suppression strategy."""

import re

from claude_code_hooks_daemon.strategies.qa_suppression.csharp_strategy import (
    CSharpQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)


def _pragma_warning_disable_text() -> str:
    return "#pragma warning" + " disable"


def _suppress_message_text() -> str:
    return "[Suppress" + "Message("


def test_implements_protocol() -> None:
    """CSharpQaSuppressionStrategy should implement protocol."""
    strategy = CSharpQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_language_name() -> None:
    """Language name should be 'C#'."""
    strategy = CSharpQaSuppressionStrategy()
    assert strategy.language_name == "C#"


def test_extensions() -> None:
    """Extensions should be ('.cs',)."""
    strategy = CSharpQaSuppressionStrategy()
    assert strategy.extensions == (".cs",)


def test_forbidden_patterns_not_empty() -> None:
    """Should have forbidden patterns defined."""
    strategy = CSharpQaSuppressionStrategy()
    assert len(strategy.forbidden_patterns) > 0


def test_forbidden_patterns_are_valid_regex() -> None:
    """All forbidden patterns should be valid regex."""
    strategy = CSharpQaSuppressionStrategy()
    for pattern in strategy.forbidden_patterns:
        re.compile(pattern)


def test_matches_pragma_warning_disable() -> None:
    """Should match pragma warning disable."""
    strategy = CSharpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"{_pragma_warning_disable_text()} CS0168"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_matches_suppress_message() -> None:
    """Should match SuppressMessage attribute."""
    strategy = CSharpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f'{_suppress_message_text()}"Category", "CheckId")]'
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_skip_directories_not_empty() -> None:
    """Should have skip directories defined."""
    strategy = CSharpQaSuppressionStrategy()
    assert len(strategy.skip_directories) > 0


def test_tool_names_not_empty() -> None:
    """Should have tool names defined."""
    strategy = CSharpQaSuppressionStrategy()
    assert len(strategy.tool_names) > 0


def test_tool_docs_urls_not_empty() -> None:
    """Should have tool docs URLs defined."""
    strategy = CSharpQaSuppressionStrategy()
    assert len(strategy.tool_docs_urls) > 0


def test_acceptance_tests_provided() -> None:
    """Should provide at least one acceptance test."""
    strategy = CSharpQaSuppressionStrategy()
    tests = strategy.get_acceptance_tests()
    assert len(tests) > 0
