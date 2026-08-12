"""Tests for Go comment strategy."""

from claude_code_hooks_daemon.strategies.comments.go_strategy import GoCommentStrategy
from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.syntax import SLASH_SYNTAX


def test_implements_protocol() -> None:
    assert isinstance(GoCommentStrategy(), CommentStrategy)


def test_language_name() -> None:
    assert GoCommentStrategy().language_name == "Go"


def test_extensions() -> None:
    assert GoCommentStrategy().extensions == (".go",)


def test_syntax_is_slash_syntax() -> None:
    assert GoCommentStrategy().syntax is SLASH_SYNTAX


def test_skip_directories_nonempty() -> None:
    assert len(GoCommentStrategy().skip_directories) > 0


def test_get_acceptance_tests_returns_at_least_one() -> None:
    assert len(GoCommentStrategy().get_acceptance_tests()) >= 1
