"""Shared comment-extraction engine (Plan 00208).

ONE algorithm, driven entirely by :class:`CommentSyntax` data, walks source
text and turns it into :class:`CommentSpan` objects. Every ``CommentStrategy``
supplies only syntax data (line prefixes, block/doc delimiters); this module
is the single place that knows how to read it -- mirroring how
``qa_suppression``'s regex-scanning logic lives once in the handler while
each language strategy supplies only ``forbidden_patterns``.

This is regex/line-based text scanning, not a real tokenizer -- the same
precision level as ``qa_suppression``/``security_antipattern`` elsewhere in
this codebase. A comment marker inside a string literal (e.g. ``"a # b"`` in
Python) can be misread as opening a comment; this is a documented, accepted
limitation, not a defect to silently "fix" with a full parser per language.
"""

from dataclasses import dataclass

from claude_code_hooks_daemon.strategies.comments.syntax import CommentSyntax


@dataclass(frozen=True)
class CommentSpan:
    """One contiguous comment region: a line-comment run, a trailing inline
    comment, or a block/doc delimited comment.

    Attributes:
        text: Raw comment text, markers included, code excluded. Multi-line
            spans join lines with ``\\n``.
        start_line: 0-indexed line number where the span begins.
        end_line: 0-indexed line number where the span ends (inclusive).
        is_doc: True for spans matched via ``syntax.doc_delimiters``
            (docstrings, JSDoc/Javadoc/KDoc/PHPDoc) -- exempt from
            ``comment_size``, still subject to ``comment_changelog``.
    """

    text: str
    start_line: int
    end_line: int
    is_doc: bool

    @property
    def line_count(self) -> int:
        """Number of physical lines this span occupies."""
        return self.end_line - self.start_line + 1

    @property
    def max_line_length(self) -> int:
        """Length, in characters, of the longest single line in this span."""
        return max((len(line) for line in self.text.split("\n")), default=0)


def extract_comment_spans(content: str, syntax: CommentSyntax) -> list[CommentSpan]:
    """Extract every comment span from ``content`` per ``syntax``.

    Single left-to-right pass over lines. On each line, the EARLIEST of a
    block/doc delimiter start or a line-comment marker wins; ties favour the
    delimiter (a delimiter and a line marker can only tie when one contains
    the other as a prefix, e.g. ``/**`` vs a hypothetical ``/`` marker, which
    none of the registered syntaxes do).

    Args:
        content: Full source text to scan.
        syntax: Comment syntax describing this language.

    Returns:
        Comment spans in the order they appear in ``content``.
    """
    # splitlines() (not split("\n")): a trailing "\n" must NOT produce a
    # spurious empty final "line" that shifts every subsequent line number.
    lines = content.splitlines()
    spans: list[CommentSpan] = []
    delimiters = syntax.doc_delimiters + syntax.block_delimiters
    doc_starts = {start for start, _ in syntax.doc_delimiters}

    index = 0
    line_total = len(lines)
    while index < line_total:
        line = lines[index]
        delimiter_hit = _find_first_delimiter(line, delimiters)
        marker_hit = _find_first_marker(line, syntax.line_prefixes)

        if delimiter_hit is not None and (
            marker_hit is None or delimiter_hit.position <= marker_hit.position
        ):
            is_doc = delimiter_hit.start in doc_starts
            if is_doc and syntax.doc_requires_line_start and line[: delimiter_hit.position].strip():
                # A doc delimiter mid-line (e.g. `query = """...`) does not
                # open a doc span for a syntax that requires line-start —
                # fall through to marker handling on this same line instead.
                pass
            else:
                span, index = _consume_delimited(lines, index, delimiter_hit, is_doc)
                spans.append(span)
                continue

        if marker_hit is not None:
            prefix = line[: marker_hit.position]
            if prefix.strip() == "":
                run_end = _extend_comment_run(lines, index, syntax)
                spans.append(_build_line_span(lines, index, run_end, syntax))
                index = run_end + 1
            else:
                spans.append(_build_line_span(lines, index, index, syntax))
                index += 1
            continue

        index += 1

    return spans


@dataclass(frozen=True)
class _MarkerHit:
    position: int
    marker: str


@dataclass(frozen=True)
class _DelimiterHit:
    position: int
    start: str
    end: str


def _find_first_marker(line: str, markers: tuple[str, ...]) -> _MarkerHit | None:
    """Return the EARLIEST occurrence of any line-comment marker on ``line``."""
    best: _MarkerHit | None = None
    for marker in markers:
        position = line.find(marker)
        if position == -1:
            continue
        if best is None or position < best.position:
            best = _MarkerHit(position=position, marker=marker)
    return best


def _find_first_delimiter(
    line: str, delimiters: tuple[tuple[str, str], ...]
) -> _DelimiterHit | None:
    """Return the EARLIEST occurrence of any block/doc delimiter START on ``line``."""
    best: _DelimiterHit | None = None
    for start, end in delimiters:
        position = line.find(start)
        if position == -1:
            continue
        if best is None or position < best.position:
            best = _DelimiterHit(position=position, start=start, end=end)
    return best


def _consume_delimited(
    lines: list[str], start_index: int, hit: _DelimiterHit, is_doc: bool
) -> tuple[CommentSpan, int]:
    """Consume a block/doc comment opening at ``lines[start_index][hit.position:]``.

    Returns the built span and the index of the NEXT line to resume from.
    An unterminated comment (no closing delimiter before EOF) closes at the
    last line of the file.
    """
    first_line = lines[start_index]
    search_from = hit.position + len(hit.start)
    end_on_first_line = first_line.find(hit.end, search_from)
    if end_on_first_line != -1:
        text = first_line[hit.position : end_on_first_line + len(hit.end)]
        span = CommentSpan(text=text, start_line=start_index, end_line=start_index, is_doc=is_doc)
        return span, start_index + 1

    collected = [first_line[hit.position :]]
    line_total = len(lines)
    cursor = start_index + 1
    while cursor < line_total:
        end_position = lines[cursor].find(hit.end)
        if end_position != -1:
            collected.append(lines[cursor][: end_position + len(hit.end)])
            span = CommentSpan(
                text="\n".join(collected), start_line=start_index, end_line=cursor, is_doc=is_doc
            )
            return span, cursor + 1
        collected.append(lines[cursor])
        cursor += 1

    # Unterminated: runs to EOF.
    span = CommentSpan(
        text="\n".join(collected), start_line=start_index, end_line=line_total - 1, is_doc=is_doc
    )
    return span, line_total


def _extend_comment_run(lines: list[str], start_index: int, syntax: CommentSyntax) -> int:
    """Return the index of the LAST line in the comment-only run starting at ``start_index``.

    A run continues while subsequent lines are ALSO comment-only (nothing but
    whitespace before the marker). A line that opens a block/doc comment
    instead has no line-comment marker before it (delimiter start tokens are
    never whitespace), so it always fails the marker check below and stops
    the run there -- the OUTER loop then reprocesses that line fresh and
    correctly opens the delimited span.
    """
    line_total = len(lines)
    run_end = start_index
    cursor = start_index + 1
    while cursor < line_total:
        line = lines[cursor]
        marker_hit = _find_first_marker(line, syntax.line_prefixes)
        if marker_hit is None or line[: marker_hit.position].strip() != "":
            break
        run_end = cursor
        cursor += 1
    return run_end


def _build_line_span(
    lines: list[str], start_index: int, end_index: int, syntax: CommentSyntax
) -> CommentSpan:
    """Build a line-comment span from ``start_index`` to ``end_index`` inclusive.

    Each line's text starts at ITS OWN marker position (dropping any leading
    code, so a trailing inline comment never carries the code before it).
    """
    parts: list[str] = []
    for line_index in range(start_index, end_index + 1):
        line = lines[line_index]
        marker_hit = _find_first_marker(line, syntax.line_prefixes)
        parts.append(line[marker_hit.position :] if marker_hit is not None else line)
    return CommentSpan(
        text="\n".join(parts), start_line=start_index, end_line=end_index, is_doc=False
    )
