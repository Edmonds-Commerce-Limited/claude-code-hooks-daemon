"""Tests for Python comment strategy."""

from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.python_strategy import (
    PythonCommentStrategy,
)
from claude_code_hooks_daemon.strategies.comments.syntax import PYTHON_SYNTAX


def test_implements_protocol() -> None:
    assert isinstance(PythonCommentStrategy(), CommentStrategy)


def test_language_name() -> None:
    assert PythonCommentStrategy().language_name == "Python"


def test_extensions() -> None:
    assert PythonCommentStrategy().extensions == (".py",)


def test_syntax_is_python_syntax() -> None:
    assert PythonCommentStrategy().syntax is PYTHON_SYNTAX


def test_skip_directories_nonempty() -> None:
    assert len(PythonCommentStrategy().skip_directories) > 0


def test_get_acceptance_tests_returns_at_least_one() -> None:
    tests = PythonCommentStrategy().get_acceptance_tests()
    assert len(tests) >= 1
