"""Tests for extract_comment_spans() - the shared comment-extraction engine.

Every CommentStrategy supplies only DATA (CommentSyntax); this module's
algorithm is the ONE place that walks source text and turns it into
CommentSpan objects, for both comment_size and comment_changelog to scan.
"""

from claude_code_hooks_daemon.strategies.comments.extractor import (
    CommentSpan,
    extract_comment_spans,
)
from claude_code_hooks_daemon.strategies.comments.syntax import (
    PHP_SYNTAX,
    PYTHON_SYNTAX,
    SLASH_DOC_SYNTAX,
    SLASH_SYNTAX,
    CommentSyntax,
)

HASH = CommentSyntax(line_prefixes=("#",))


class TestCommentSpanProperties:
    """CommentSpan derives line_count / max_line_length from its text."""

    def test_single_line_span(self) -> None:
        span = CommentSpan(text="# hello", start_line=0, end_line=0, is_doc=False)
        assert span.line_count == 1
        assert span.max_line_length == len("# hello")

    def test_multi_line_span(self) -> None:
        span = CommentSpan(text="# one\n# two-longer", start_line=0, end_line=1, is_doc=False)
        assert span.line_count == 2
        assert span.max_line_length == len("# two-longer")


class TestEmptyAndNoComments:
    def test_empty_content_returns_no_spans(self) -> None:
        assert extract_comment_spans("", HASH) == []

    def test_content_with_no_comments_returns_no_spans(self) -> None:
        content = "x = 1\ny = 2\n"
        assert extract_comment_spans(content, HASH) == []


class TestLineCommentRuns:
    def test_single_full_line_comment(self) -> None:
        spans = extract_comment_spans("# a comment\nx = 1\n", HASH)
        assert len(spans) == 1
        assert spans[0].text == "# a comment"
        assert spans[0].start_line == 0
        assert spans[0].end_line == 0
        assert spans[0].is_doc is False

    def test_contiguous_comment_lines_merge_into_one_span(self) -> None:
        content = "# line one\n# line two\n# line three\nx = 1\n"
        spans = extract_comment_spans(content, HASH)
        assert len(spans) == 1
        assert spans[0].start_line == 0
        assert spans[0].end_line == 2
        assert spans[0].text == "# line one\n# line two\n# line three"

    def test_blank_line_breaks_the_run(self) -> None:
        content = "# first\n\n# second\n"
        spans = extract_comment_spans(content, HASH)
        assert len(spans) == 2
        assert spans[0].text == "# first"
        assert spans[1].text == "# second"

    def test_code_line_breaks_the_run(self) -> None:
        content = "# first\nx = 1\n# second\n"
        spans = extract_comment_spans(content, HASH)
        assert len(spans) == 2

    def test_indented_comment_only_line_still_counts_as_comment_only(self) -> None:
        content = "    # indented\n    # also indented\n"
        spans = extract_comment_spans(content, HASH)
        assert len(spans) == 1
        assert spans[0].start_line == 0
        assert spans[0].end_line == 1


class TestTrailingInlineComments:
    """The field report's real shape: CODE followed by a trailing comment."""

    def test_trailing_comment_is_its_own_single_line_span(self) -> None:
        content = 'CCY_VERSION="3.27.1"  # Patch: released\n'
        spans = extract_comment_spans(content, HASH)
        assert len(spans) == 1
        assert spans[0].text == "# Patch: released"
        assert spans[0].line_count == 1

    def test_trailing_comment_does_not_include_the_code_prefix(self) -> None:
        content = "x = compute_something(1, 2, 3)  # explain the magic numbers\n"
        spans = extract_comment_spans(content, HASH)
        assert len(spans) == 1
        assert "compute_something" not in spans[0].text
        assert spans[0].text.startswith("#")

    def test_trailing_comment_followed_by_full_line_comment_is_two_spans(self) -> None:
        content = "x = 1  # trailing\n# standalone\n"
        spans = extract_comment_spans(content, HASH)
        assert len(spans) == 2
        assert spans[0].text == "# trailing"
        assert spans[1].text == "# standalone"


class TestBlockComments:
    def test_single_line_block_comment(self) -> None:
        content = "x = 1; /* explain */\n"
        spans = extract_comment_spans(content, SLASH_SYNTAX)
        assert len(spans) == 1
        assert spans[0].text == "/* explain */"
        assert spans[0].is_doc is False

    def test_multi_line_block_comment(self) -> None:
        content = "/*\n * line one\n * line two\n */\ncode();\n"
        spans = extract_comment_spans(content, SLASH_SYNTAX)
        assert len(spans) == 1
        assert spans[0].start_line == 0
        assert spans[0].end_line == 3
        assert spans[0].line_count == 4

    def test_unterminated_block_comment_closes_at_eof(self) -> None:
        content = "/* never closes\nmore text\n"
        spans = extract_comment_spans(content, SLASH_SYNTAX)
        assert len(spans) == 1
        assert spans[0].end_line == 1

    def test_line_comment_after_block_comment_is_separate(self) -> None:
        content = "/* block */\n// line\n"
        spans = extract_comment_spans(content, SLASH_SYNTAX)
        assert len(spans) == 2
        assert spans[0].is_doc is False
        assert spans[1].text == "// line"


class TestDocComments:
    def test_jsdoc_block_is_marked_is_doc(self) -> None:
        content = "/**\n * Documented function.\n */\nfunction f() {}\n"
        spans = extract_comment_spans(content, SLASH_DOC_SYNTAX)
        assert len(spans) == 1
        assert spans[0].is_doc is True

    def test_ordinary_block_comment_is_not_doc(self) -> None:
        content = "/* not a doc comment */\n"
        spans = extract_comment_spans(content, SLASH_DOC_SYNTAX)
        assert len(spans) == 1
        assert spans[0].is_doc is False

    def test_python_docstring_at_line_start_is_doc(self) -> None:
        content = '"""Module docstring."""\nimport os\n'
        spans = extract_comment_spans(content, PYTHON_SYNTAX)
        assert len(spans) == 1
        assert spans[0].is_doc is True

    def test_python_multiline_docstring_is_doc(self) -> None:
        content = '"""\nLine one.\nLine two.\n"""\nimport os\n'
        spans = extract_comment_spans(content, PYTHON_SYNTAX)
        assert len(spans) == 1
        assert spans[0].is_doc is True
        assert spans[0].start_line == 0
        assert spans[0].end_line == 3

    def test_python_inline_triple_quote_string_is_not_doc(self) -> None:
        # doc_requires_line_start=True: an assignment is NOT a docstring.
        content = 'query = """SELECT * FROM t"""\n'
        spans = extract_comment_spans(content, PYTHON_SYNTAX)
        assert spans == []

    def test_python_hash_comment_and_docstring_both_extracted(self) -> None:
        content = '# module note\n"""Docstring."""\n'
        spans = extract_comment_spans(content, PYTHON_SYNTAX)
        assert len(spans) == 2
        assert spans[0].is_doc is False
        assert spans[1].is_doc is True


class TestPhpDualLinePrefixes:
    def test_php_hash_and_slash_merge_into_one_contiguous_run(self) -> None:
        # Both markers are comment-only lines with nothing between them, so
        # they form ONE contiguous block regardless of which marker each
        # line uses -- matching plan-doc-size's "contiguous block" semantics.
        content = "# hash comment\n// slash comment\n"
        spans = extract_comment_spans(content, PHP_SYNTAX)
        assert len(spans) == 1
        assert spans[0].text == "# hash comment\n// slash comment"

    def test_php_hash_and_slash_separated_by_blank_line_stay_separate(self) -> None:
        content = "# hash comment\n\n// slash comment\n"
        spans = extract_comment_spans(content, PHP_SYNTAX)
        assert len(spans) == 2
        assert spans[0].text == "# hash comment"
        assert spans[1].text == "// slash comment"

    def test_php_phpdoc_block_is_doc(self) -> None:
        content = "/**\n * @param int $x\n */\n"
        spans = extract_comment_spans(content, PHP_SYNTAX)
        assert len(spans) == 1
        assert spans[0].is_doc is True


class TestMultipleSpansInOneFile:
    def test_realistic_mixed_file(self) -> None:
        content = (
            "#!/bin/bash\n"
            "# Header comment line one\n"
            "# Header comment line two\n"
            "\n"
            'VERSION="1.0.0"  # trailing note\n'
            "\n"
            "run_thing\n"
        )
        spans = extract_comment_spans(content, HASH)
        # The shebang is itself a comment-only line contiguous with the
        # header lines below it, so all three merge into one run.
        assert len(spans) == 2
        assert (
            spans[0].text
            == "#!/bin/bash\n# Header comment line one\n# Header comment line two"
        )
        assert spans[1].text == "# trailing note"
