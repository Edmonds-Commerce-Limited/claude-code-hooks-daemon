"""Tests for PHP comment strategy."""

from claude_code_hooks_daemon.strategies.comments.php_strategy import PhpCommentStrategy
from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.syntax import PHP_SYNTAX


def test_implements_protocol() -> None:
    assert isinstance(PhpCommentStrategy(), CommentStrategy)


def test_language_name() -> None:
    assert PhpCommentStrategy().language_name == "PHP"


def test_extensions() -> None:
    assert PhpCommentStrategy().extensions == (".php",)


def test_syntax_is_php_syntax() -> None:
    assert PhpCommentStrategy().syntax is PHP_SYNTAX


def test_skip_directories_nonempty() -> None:
    assert len(PhpCommentStrategy().skip_directories) > 0


def test_get_acceptance_tests_returns_at_least_one() -> None:
    assert len(PhpCommentStrategy().get_acceptance_tests()) >= 1
