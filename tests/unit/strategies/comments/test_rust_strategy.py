"""Tests for Rust comment strategy."""

from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.rust_strategy import (
    RustCommentStrategy,
)
from claude_code_hooks_daemon.strategies.comments.syntax import SLASH_SYNTAX


def test_implements_protocol() -> None:
    assert isinstance(RustCommentStrategy(), CommentStrategy)


def test_language_name() -> None:
    assert RustCommentStrategy().language_name == "Rust"


def test_extensions() -> None:
    assert RustCommentStrategy().extensions == (".rs",)


def test_syntax_is_slash_syntax() -> None:
    assert RustCommentStrategy().syntax is SLASH_SYNTAX


def test_skip_directories_nonempty() -> None:
    assert len(RustCommentStrategy().skip_directories) > 0


def test_get_acceptance_tests_returns_at_least_one() -> None:
    assert len(RustCommentStrategy().get_acceptance_tests()) >= 1
