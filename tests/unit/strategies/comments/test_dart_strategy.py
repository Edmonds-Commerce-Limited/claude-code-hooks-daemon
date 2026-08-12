"""Tests for Dart comment strategy."""

from claude_code_hooks_daemon.strategies.comments.dart_strategy import DartCommentStrategy
from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.syntax import SLASH_SYNTAX


def test_implements_protocol() -> None:
    assert isinstance(DartCommentStrategy(), CommentStrategy)


def test_language_name() -> None:
    assert DartCommentStrategy().language_name == "Dart"


def test_extensions() -> None:
    assert DartCommentStrategy().extensions == (".dart",)


def test_syntax_is_slash_syntax() -> None:
    assert DartCommentStrategy().syntax is SLASH_SYNTAX


def test_skip_directories_nonempty() -> None:
    assert len(DartCommentStrategy().skip_directories) > 0


def test_get_acceptance_tests_returns_at_least_one() -> None:
    assert len(DartCommentStrategy().get_acceptance_tests()) >= 1
