"""Tests for Kotlin comment strategy."""

from claude_code_hooks_daemon.strategies.comments.kotlin_strategy import (
    KotlinCommentStrategy,
)
from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.syntax import SLASH_DOC_SYNTAX


def test_implements_protocol() -> None:
    assert isinstance(KotlinCommentStrategy(), CommentStrategy)


def test_language_name() -> None:
    assert KotlinCommentStrategy().language_name == "Kotlin"


def test_extensions() -> None:
    assert KotlinCommentStrategy().extensions == (".kt", ".kts")


def test_syntax_is_slash_doc_syntax() -> None:
    assert KotlinCommentStrategy().syntax is SLASH_DOC_SYNTAX


def test_skip_directories_nonempty() -> None:
    assert len(KotlinCommentStrategy().skip_directories) > 0


def test_get_acceptance_tests_returns_at_least_one() -> None:
    assert len(KotlinCommentStrategy().get_acceptance_tests()) >= 1
