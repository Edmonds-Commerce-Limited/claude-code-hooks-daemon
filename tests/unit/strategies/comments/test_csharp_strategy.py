"""Tests for C# comment strategy."""

from claude_code_hooks_daemon.strategies.comments.csharp_strategy import (
    CSharpCommentStrategy,
)
from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.syntax import SLASH_SYNTAX


def test_implements_protocol() -> None:
    assert isinstance(CSharpCommentStrategy(), CommentStrategy)


def test_language_name() -> None:
    assert CSharpCommentStrategy().language_name == "C#"


def test_extensions() -> None:
    assert CSharpCommentStrategy().extensions == (".cs",)


def test_syntax_is_slash_syntax() -> None:
    assert CSharpCommentStrategy().syntax is SLASH_SYNTAX


def test_skip_directories_nonempty() -> None:
    assert len(CSharpCommentStrategy().skip_directories) > 0


def test_get_acceptance_tests_returns_at_least_one() -> None:
    assert len(CSharpCommentStrategy().get_acceptance_tests()) >= 1
