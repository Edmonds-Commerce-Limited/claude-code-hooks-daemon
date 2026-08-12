"""Tests for Ruby comment strategy."""

from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.ruby_strategy import (
    RubyCommentStrategy,
)
from claude_code_hooks_daemon.strategies.comments.syntax import HASH_SYNTAX


def test_implements_protocol() -> None:
    assert isinstance(RubyCommentStrategy(), CommentStrategy)


def test_language_name() -> None:
    assert RubyCommentStrategy().language_name == "Ruby"


def test_extensions() -> None:
    assert RubyCommentStrategy().extensions == (".rb",)


def test_syntax_is_hash_syntax() -> None:
    assert RubyCommentStrategy().syntax is HASH_SYNTAX


def test_skip_directories_nonempty() -> None:
    assert len(RubyCommentStrategy().skip_directories) > 0


def test_get_acceptance_tests_returns_at_least_one() -> None:
    assert len(RubyCommentStrategy().get_acceptance_tests()) >= 1
