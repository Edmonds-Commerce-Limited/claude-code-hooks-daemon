"""Tests for Shell comment strategy."""

from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.shell_strategy import (
    ShellCommentStrategy,
)
from claude_code_hooks_daemon.strategies.comments.syntax import HASH_SYNTAX


def test_implements_protocol() -> None:
    assert isinstance(ShellCommentStrategy(), CommentStrategy)


def test_language_name() -> None:
    assert ShellCommentStrategy().language_name == "Shell"


def test_extensions() -> None:
    assert ShellCommentStrategy().extensions == (".sh", ".bash")


def test_syntax_is_hash_syntax() -> None:
    assert ShellCommentStrategy().syntax is HASH_SYNTAX


def test_skip_directories_nonempty() -> None:
    assert len(ShellCommentStrategy().skip_directories) > 0


def test_get_acceptance_tests_returns_at_least_one() -> None:
    assert len(ShellCommentStrategy().get_acceptance_tests()) >= 1
