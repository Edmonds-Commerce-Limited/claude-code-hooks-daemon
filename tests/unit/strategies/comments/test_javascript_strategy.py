"""Tests for JavaScript/TypeScript comment strategy."""

from claude_code_hooks_daemon.strategies.comments.javascript_strategy import (
    JavaScriptCommentStrategy,
)
from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.syntax import SLASH_DOC_SYNTAX


def test_implements_protocol() -> None:
    assert isinstance(JavaScriptCommentStrategy(), CommentStrategy)


def test_language_name() -> None:
    assert JavaScriptCommentStrategy().language_name == "JavaScript/TypeScript"


def test_extensions() -> None:
    assert JavaScriptCommentStrategy().extensions == (".js", ".jsx", ".ts", ".tsx")


def test_syntax_is_slash_doc_syntax() -> None:
    assert JavaScriptCommentStrategy().syntax is SLASH_DOC_SYNTAX


def test_skip_directories_nonempty() -> None:
    assert len(JavaScriptCommentStrategy().skip_directories) > 0


def test_get_acceptance_tests_returns_at_least_one() -> None:
    assert len(JavaScriptCommentStrategy().get_acceptance_tests()) >= 1
