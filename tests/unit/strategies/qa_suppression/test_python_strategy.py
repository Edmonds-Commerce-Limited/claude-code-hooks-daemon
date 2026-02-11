"""Tests for Python QA suppression strategy."""

import re

from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.python_strategy import (
    PythonQaSuppressionStrategy,
)


# ── Build test strings dynamically to avoid hook detection ──
def _type_ignore_text() -> str:
    return "# type" + ": " + "ignore"


def _noqa_text() -> str:
    return "# no" + "qa"


def _pylint_disable_text() -> str:
    return "# pylint" + ": " + "disable"


def test_implements_protocol() -> None:
    """PythonQaSuppressionStrategy should implement QaSuppressionStrategy protocol."""
    strategy = PythonQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_language_name() -> None:
    """Language name should be 'Python'."""
    strategy = PythonQaSuppressionStrategy()
    assert strategy.language_name == "Python"


def test_extensions() -> None:
    """Extensions should be ('.py',)."""
    strategy = PythonQaSuppressionStrategy()
    assert strategy.extensions == (".py",)


def test_forbidden_patterns_not_empty() -> None:
    """Should have forbidden patterns defined."""
    strategy = PythonQaSuppressionStrategy()
    assert len(strategy.forbidden_patterns) > 0


def test_forbidden_patterns_are_valid_regex() -> None:
    """All forbidden patterns should be valid regex."""
    strategy = PythonQaSuppressionStrategy()
    for pattern in strategy.forbidden_patterns:
        re.compile(pattern)


def test_matches_type_ignore() -> None:
    """Should match type ignore comments."""
    strategy = PythonQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"x = 1  {_type_ignore_text()}"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_matches_noqa_comment() -> None:
    """Should match noqa comments."""
    strategy = PythonQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"x = 1  {_noqa_text()}"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_matches_pylint_disable() -> None:
    """Should match pylint disable comments."""
    strategy = PythonQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"x = 1  {_pylint_disable_text()}"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_skip_directories_not_empty() -> None:
    """Should have skip directories defined."""
    strategy = PythonQaSuppressionStrategy()
    assert len(strategy.skip_directories) > 0


def test_skip_directories_include_vendor() -> None:
    """Skip directories should include vendor/."""
    strategy = PythonQaSuppressionStrategy()
    assert "vendor/" in strategy.skip_directories


def test_skip_directories_include_venv() -> None:
    """Skip directories should include venv directories."""
    strategy = PythonQaSuppressionStrategy()
    skip = strategy.skip_directories
    assert ".venv/" in skip or "venv/" in skip


def test_tool_names_not_empty() -> None:
    """Should have tool names defined."""
    strategy = PythonQaSuppressionStrategy()
    assert len(strategy.tool_names) > 0


def test_tool_names_include_mypy() -> None:
    """Tool names should include MyPy."""
    strategy = PythonQaSuppressionStrategy()
    assert "MyPy" in strategy.tool_names


def test_tool_docs_urls_not_empty() -> None:
    """Should have tool docs URLs defined."""
    strategy = PythonQaSuppressionStrategy()
    assert len(strategy.tool_docs_urls) > 0


def test_acceptance_tests_provided() -> None:
    """Should provide at least one acceptance test."""
    strategy = PythonQaSuppressionStrategy()
    tests = strategy.get_acceptance_tests()
    assert len(tests) > 0
