"""Tests for JavaScript/TypeScript QA suppression strategy."""

import re

from claude_code_hooks_daemon.strategies.qa_suppression.javascript_strategy import (
    JavaScriptQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)


def _eslint_disable_text() -> str:
    return "// eslint" + "-disable"


def _ts_ignore_text() -> str:
    return "// @ts" + "-ignore"


def test_implements_protocol() -> None:
    """JavaScriptQaSuppressionStrategy should implement protocol."""
    strategy = JavaScriptQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_language_name() -> None:
    """Language name should be 'JavaScript/TypeScript'."""
    strategy = JavaScriptQaSuppressionStrategy()
    assert strategy.language_name == "JavaScript/TypeScript"


def test_extensions() -> None:
    """Extensions should include JS and TS variants."""
    strategy = JavaScriptQaSuppressionStrategy()
    assert strategy.extensions == (".js", ".jsx", ".ts", ".tsx")


def test_forbidden_patterns_not_empty() -> None:
    """Should have forbidden patterns defined."""
    strategy = JavaScriptQaSuppressionStrategy()
    assert len(strategy.forbidden_patterns) > 0


def test_forbidden_patterns_are_valid_regex() -> None:
    """All forbidden patterns should be valid regex."""
    strategy = JavaScriptQaSuppressionStrategy()
    for pattern in strategy.forbidden_patterns:
        re.compile(pattern)


def test_matches_eslint_disable() -> None:
    """Should match eslint-disable comments."""
    strategy = JavaScriptQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"x = 1; {_eslint_disable_text()}-next-line no-console"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_matches_ts_ignore() -> None:
    """Should match ts-ignore comments."""
    strategy = JavaScriptQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"const x = 1; {_ts_ignore_text()}"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_skip_directories_not_empty() -> None:
    """Should have skip directories defined."""
    strategy = JavaScriptQaSuppressionStrategy()
    assert len(strategy.skip_directories) > 0


def test_skip_directories_include_node_modules() -> None:
    """Skip directories should include node_modules/."""
    strategy = JavaScriptQaSuppressionStrategy()
    assert "node_modules/" in strategy.skip_directories


def test_tool_names_not_empty() -> None:
    """Should have tool names defined."""
    strategy = JavaScriptQaSuppressionStrategy()
    assert len(strategy.tool_names) > 0


def test_tool_names_include_eslint() -> None:
    """Tool names should include ESLint."""
    strategy = JavaScriptQaSuppressionStrategy()
    assert "ESLint" in strategy.tool_names


def test_tool_docs_urls_not_empty() -> None:
    """Should have tool docs URLs defined."""
    strategy = JavaScriptQaSuppressionStrategy()
    assert len(strategy.tool_docs_urls) > 0


def test_acceptance_tests_provided() -> None:
    """Should provide at least one acceptance test."""
    strategy = JavaScriptQaSuppressionStrategy()
    tests = strategy.get_acceptance_tests()
    assert len(tests) > 0
