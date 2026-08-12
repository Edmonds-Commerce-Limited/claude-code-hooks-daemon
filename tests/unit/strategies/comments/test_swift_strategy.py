"""Tests for Swift comment strategy."""

from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.swift_strategy import (
    SwiftCommentStrategy,
)
from claude_code_hooks_daemon.strategies.comments.syntax import SLASH_SYNTAX


def test_implements_protocol() -> None:
    assert isinstance(SwiftCommentStrategy(), CommentStrategy)


def test_language_name() -> None:
    assert SwiftCommentStrategy().language_name == "Swift"


def test_extensions() -> None:
    assert SwiftCommentStrategy().extensions == (".swift",)


def test_syntax_is_slash_syntax() -> None:
    assert SwiftCommentStrategy().syntax is SLASH_SYNTAX


def test_skip_directories_nonempty() -> None:
    assert len(SwiftCommentStrategy().skip_directories) > 0


def test_get_acceptance_tests_returns_at_least_one() -> None:
    assert len(SwiftCommentStrategy().get_acceptance_tests()) >= 1
