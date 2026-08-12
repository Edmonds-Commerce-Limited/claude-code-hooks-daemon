"""Comment syntax definitions shared across CommentStrategy implementations.

Comment SYNTAX (line prefixes, block delimiters, doc-comment delimiters) is
DATA, not behaviour -- the extraction algorithm in ``extractor.py`` is
identical for every language and only ever reads this data. Defining each
syntax family ONCE here and re-using it across the per-language strategy
files (Plan 00208) keeps every language's config a single source of truth
instead of duplicating the same tuples across eleven-plus files.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CommentSyntax:
    """One language's comment syntax, expressed as pure data.

    Attributes:
        line_prefixes: Markers that start a line (or trailing) comment, e.g.
            ``("#",)`` or ``("//", "#")``. The extractor searches for the
            EARLIEST occurrence of any prefix on a line.
        block_delimiters: ``(start, end)`` pairs for ordinary multi-line
            block comments, e.g. ``(("/*", "*/"),)``.
        doc_delimiters: ``(start, end)`` pairs for API-documentation block
            comments (Python docstrings, JSDoc/Javadoc/KDoc ``/** */``).
            Spans matched here are marked ``is_doc=True`` -- exempt from
            ``comment_size`` but still subject to ``comment_changelog``.
        doc_requires_line_start: When True, a ``doc_delimiters`` start token
            only opens a doc span if it is the first non-whitespace content
            on its line. Needed for Python triple-quote docstrings, where
            the same quote token also delimits an ordinary string value
            (e.g. an inline SQL literal assigned to a variable) -- without
            this guard every triple-quoted string literal would be misread
            as a docstring.
    """

    line_prefixes: tuple[str, ...] = ()
    block_delimiters: tuple[tuple[str, str], ...] = ()
    doc_delimiters: tuple[tuple[str, str], ...] = ()
    doc_requires_line_start: bool = False


# ── Shared syntax families (Plan 00208) ──────────────────────────────────
# One instance per DISTINCT comment syntax; many languages share one, which
# is exactly why this lives in its own module instead of being repeated
# inside each language's strategy file.

# Shell/Bash/Ruby/YAML: '#' line comments only, no block-comment syntax.
HASH_SYNTAX = CommentSyntax(line_prefixes=("#",))

# Python: '#' line comments; '"""'/"'''" triple-quoted strings used as
# docstrings. Treating every LINE-STARTING triple-quote span as doc-shaped
# is a conservative approximation -- worst case a non-docstring standalone
# triple-quoted statement is wrongly EXEMPTED from comment_size (which only
# ever loosens a size check, never tightens it); comment_changelog still
# scans it regardless.
PYTHON_SYNTAX = CommentSyntax(
    line_prefixes=("#",),
    doc_delimiters=(('"""', '"""'), ("'''", "'''")),
    doc_requires_line_start=True,
)

# PHP: both '#' and '//' line comments, '/* */' block, '/** */' PHPDoc.
PHP_SYNTAX = CommentSyntax(
    line_prefixes=("//", "#"),
    block_delimiters=(("/*", "*/"),),
    doc_delimiters=(("/**", "*/"),),
)

# C-family languages with no doc-block convention this extractor recognises
# (Go, Rust, C#, Swift, Dart): '//' line, '/* */' block. C#/Swift/Dart/Rust
# doc comments conventionally use a '///' triple-slash line-prefix instead
# of a block delimiter; '///' is still caught here as an ordinary '//' line
# comment -- a doc-exemption for triple-slash is deliberately out of scope
# (see PLAN 00208 Non-Goals).
SLASH_SYNTAX = CommentSyntax(
    line_prefixes=("//",),
    block_delimiters=(("/*", "*/"),),
)

# JS/TS, Java, Kotlin: '//' line, '/* */' block, '/** */' JSDoc/Javadoc/KDoc.
SLASH_DOC_SYNTAX = CommentSyntax(
    line_prefixes=("//",),
    block_delimiters=(("/*", "*/"),),
    doc_delimiters=(("/**", "*/"),),
)
