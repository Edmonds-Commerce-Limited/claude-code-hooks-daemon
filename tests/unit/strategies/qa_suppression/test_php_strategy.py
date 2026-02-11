"""Tests for PHP QA suppression strategy."""

import re

from claude_code_hooks_daemon.strategies.qa_suppression.php_strategy import (
    PhpQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)


def _phpstan_ignore_text() -> str:
    return "@phpstan-ignore" + "-next-line"


def _psalm_suppress_text() -> str:
    return "@psalm" + "-suppress"


def test_implements_protocol() -> None:
    """PhpQaSuppressionStrategy should implement QaSuppressionStrategy protocol."""
    strategy = PhpQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_language_name() -> None:
    """Language name should be 'PHP'."""
    strategy = PhpQaSuppressionStrategy()
    assert strategy.language_name == "PHP"


def test_extensions() -> None:
    """Extensions should be ('.php',)."""
    strategy = PhpQaSuppressionStrategy()
    assert strategy.extensions == (".php",)


def test_forbidden_patterns_not_empty() -> None:
    """Should have forbidden patterns defined."""
    strategy = PhpQaSuppressionStrategy()
    assert len(strategy.forbidden_patterns) > 0


def test_forbidden_patterns_are_valid_regex() -> None:
    """All forbidden patterns should be valid regex."""
    strategy = PhpQaSuppressionStrategy()
    for pattern in strategy.forbidden_patterns:
        re.compile(pattern)


def test_matches_phpstan_ignore() -> None:
    """Should match phpstan-ignore-next-line."""
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"/** {_phpstan_ignore_text()} */"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_matches_psalm_suppress() -> None:
    """Should match psalm-suppress."""
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"/** {_psalm_suppress_text()} InvalidArgument */"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_skip_directories_not_empty() -> None:
    """Should have skip directories defined."""
    strategy = PhpQaSuppressionStrategy()
    assert len(strategy.skip_directories) > 0


def test_skip_directories_include_vendor() -> None:
    """Skip directories should include vendor/."""
    strategy = PhpQaSuppressionStrategy()
    assert "vendor/" in strategy.skip_directories


def test_tool_names_not_empty() -> None:
    """Should have tool names defined."""
    strategy = PhpQaSuppressionStrategy()
    assert len(strategy.tool_names) > 0


def test_tool_docs_urls_not_empty() -> None:
    """Should have tool docs URLs defined."""
    strategy = PhpQaSuppressionStrategy()
    assert len(strategy.tool_docs_urls) > 0


def test_acceptance_tests_provided() -> None:
    """Should provide at least one acceptance test."""
    strategy = PhpQaSuppressionStrategy()
    tests = strategy.get_acceptance_tests()
    assert len(tests) > 0
