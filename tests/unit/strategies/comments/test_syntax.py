"""Tests for CommentSyntax dataclass and shared syntax instances."""

from claude_code_hooks_daemon.strategies.comments.syntax import (
    HASH_SYNTAX,
    PHP_SYNTAX,
    PYTHON_SYNTAX,
    SLASH_DOC_SYNTAX,
    SLASH_SYNTAX,
    CommentSyntax,
)


class TestCommentSyntaxDataclass:
    """CommentSyntax is a frozen, defaults-only data holder."""

    def test_defaults_are_empty(self) -> None:
        syntax = CommentSyntax()
        assert syntax.line_prefixes == ()
        assert syntax.block_delimiters == ()
        assert syntax.doc_delimiters == ()
        assert syntax.doc_requires_line_start is False

    def test_custom_values_round_trip(self) -> None:
        syntax = CommentSyntax(
            line_prefixes=("//", "#"),
            block_delimiters=(("/*", "*/"),),
            doc_delimiters=(("/**", "*/"),),
            doc_requires_line_start=True,
        )
        assert syntax.line_prefixes == ("//", "#")
        assert syntax.block_delimiters == (("/*", "*/"),)
        assert syntax.doc_delimiters == (("/**", "*/"),)
        assert syntax.doc_requires_line_start is True


class TestSharedSyntaxInstances:
    """Shared syntax instances are the single source of truth per family."""

    def test_hash_syntax_is_line_only(self) -> None:
        assert HASH_SYNTAX.line_prefixes == ("#",)
        assert HASH_SYNTAX.block_delimiters == ()
        assert HASH_SYNTAX.doc_delimiters == ()

    def test_python_syntax_has_triple_quote_docstrings(self) -> None:
        assert PYTHON_SYNTAX.line_prefixes == ("#",)
        assert ('"""', '"""') in PYTHON_SYNTAX.doc_delimiters
        assert ("'''", "'''") in PYTHON_SYNTAX.doc_delimiters
        # Docstrings must start their own line, else `x = """value"""` would
        # be mistaken for a doc comment.
        assert PYTHON_SYNTAX.doc_requires_line_start is True

    def test_php_syntax_supports_hash_and_slash(self) -> None:
        assert "//" in PHP_SYNTAX.line_prefixes
        assert "#" in PHP_SYNTAX.line_prefixes
        assert ("/*", "*/") in PHP_SYNTAX.block_delimiters
        assert ("/**", "*/") in PHP_SYNTAX.doc_delimiters

    def test_slash_syntax_has_no_doc_delimiters(self) -> None:
        assert SLASH_SYNTAX.line_prefixes == ("//",)
        assert ("/*", "*/") in SLASH_SYNTAX.block_delimiters
        assert SLASH_SYNTAX.doc_delimiters == ()

    def test_slash_doc_syntax_adds_jsdoc(self) -> None:
        assert SLASH_DOC_SYNTAX.line_prefixes == ("//",)
        assert ("/*", "*/") in SLASH_DOC_SYNTAX.block_delimiters
        assert ("/**", "*/") in SLASH_DOC_SYNTAX.doc_delimiters
