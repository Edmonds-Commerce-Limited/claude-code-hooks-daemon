"""Tests for Go QA suppression strategy."""

import re

from claude_code_hooks_daemon.strategies.qa_suppression.go_strategy import (
    GoQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)


def _nolint_text() -> str:
    return "// no" + "lint"


def _lint_ignore_text() -> str:
    return "// lint" + ":ignore"


def test_implements_protocol() -> None:
    """GoQaSuppressionStrategy should implement QaSuppressionStrategy protocol."""
    strategy = GoQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_language_name() -> None:
    """Language name should be 'Go'."""
    strategy = GoQaSuppressionStrategy()
    assert strategy.language_name == "Go"


def test_extensions() -> None:
    """Extensions should be ('.go',)."""
    strategy = GoQaSuppressionStrategy()
    assert strategy.extensions == (".go",)


def test_forbidden_patterns_not_empty() -> None:
    """Should have forbidden patterns defined."""
    strategy = GoQaSuppressionStrategy()
    assert len(strategy.forbidden_patterns) > 0


def test_forbidden_patterns_are_valid_regex() -> None:
    """All forbidden patterns should be valid regex."""
    strategy = GoQaSuppressionStrategy()
    for pattern in strategy.forbidden_patterns:
        re.compile(pattern)


def test_matches_nolint() -> None:
    """Should match nolint comments."""
    strategy = GoQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"func foo() {{ {_nolint_text()}"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_matches_lint_ignore() -> None:
    """Should match lint:ignore comments."""
    strategy = GoQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"func foo() {{ {_lint_ignore_text()}"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_skip_directories_not_empty() -> None:
    """Should have skip directories defined."""
    strategy = GoQaSuppressionStrategy()
    assert len(strategy.skip_directories) > 0


def test_skip_directories_include_vendor() -> None:
    """Skip directories should include vendor/."""
    strategy = GoQaSuppressionStrategy()
    assert "vendor/" in strategy.skip_directories


def test_tool_names_not_empty() -> None:
    """Should have tool names defined."""
    strategy = GoQaSuppressionStrategy()
    assert len(strategy.tool_names) > 0


def test_tool_docs_urls_not_empty() -> None:
    """Should have tool docs URLs defined."""
    strategy = GoQaSuppressionStrategy()
    assert len(strategy.tool_docs_urls) > 0


def test_acceptance_tests_provided() -> None:
    """Should provide at least one acceptance test."""
    strategy = GoQaSuppressionStrategy()
    tests = strategy.get_acceptance_tests()
    assert len(tests) > 0
