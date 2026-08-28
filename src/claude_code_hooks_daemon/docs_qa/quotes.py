"""``ssot-quote`` mechanism: anchors, span extraction, quote parsing, verification.

R4b — "A small verbatim excerpt MAY repeat anywhere IF wrapped in metadata
naming its source":

```markdown
<!-- ssot-quote: CLAUDE/SomeDoc.md#some-anchor -->
(verbatim excerpt)
<!-- /ssot-quote -->
```

Shared machinery consumed by ``checks.quote_drift`` and
``checks.quote_source_stale`` (DESIGN §2.4, hardened per the design
critique):

- :func:`slugify_heading` — ONE pinned heading-slug algorithm (GitHub-style
  approximation: lowercase, strip non-word/space/hyphen characters,
  collapse whitespace to hyphens). Headings carrying emoji or colons slug
  unpredictably across implementations, which is exactly why an explicit
  ``<!-- ssot-anchor: name -->`` marker is PREFERRED for anything
  non-trivial — :func:`resolve_anchor_span` tries the marker first.
- :func:`resolve_anchor_span` — fence-aware span extraction: a heading- or
  marker-looking line inside a fenced code block is never a boundary. The
  span runs from just after the anchor point to the next heading of
  same-or-higher level (or end of document) — the anchor's OWN heading
  line is excluded, since a quote excerpts the section's content, not its
  title.
- :func:`normalise_markdown` — delegates to
  :func:`claude_code_hooks_daemon.utils.markdown_format.format_markdown_text`,
  the SAME pipeline ``markdown_table_formatter`` uses, so two syntactically
  equivalent renderings of the same prose never register as drift.
- :func:`parse_quote_blocks` — fence-aware block extraction: an
  ``ssot-quote`` marker inside a fence is not a real marker, but a fence
  INSIDE a quote body (the quoted section legitimately contains a code
  snippet) is preserved verbatim.
- :func:`verify_quote` — the quote body, normalised, must be a CONTIGUOUS
  substring of the normalised source span, and at least
  :data:`MIN_QUOTE_LENGTH_CHARS` long. The length floor exists because a
  one-line quote is a substring of almost anything — it would verify
  trivially and protect nothing. The substring requirement is also what
  enforces the single-section constraint: verbatim text spanning two
  sections cannot be a contiguous substring of either section's span alone,
  so it fails by construction — callers should tell authors to split such
  a quote into two ``ssot-quote`` blocks against two anchors instead of
  trying to make one span cover both.
"""

import re
from dataclasses import dataclass
from typing import Final

from claude_code_hooks_daemon.utils.markdown_format import format_markdown_text

# A one-line quote is a substring of almost anything in ordinary prose, so it
# verifies trivially and protects nothing. 80 normalised characters is
# roughly one full sentence of the kind ssot-quote exists to protect (a
# short verification snippet or a one-sentence rule) -- short enough not to
# reject genuine short quotes, long enough that an accidental substring
# match is implausible.
MIN_QUOTE_LENGTH_CHARS: Final[int] = 80

_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(```|~~~)")
_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_ATX_TRAILING_HASHES_RE: Final[re.Pattern[str]] = re.compile(r"\s+#+\s*$")
_ANCHOR_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"^<!--\s*ssot-anchor:\s*(\S+)\s*-->\s*$")
_QUOTE_OPEN_RE: Final[re.Pattern[str]] = re.compile(
    r"^<!--\s*ssot-quote:\s*([^#]+)#(\S+?)\s*-->\s*$"
)
_QUOTE_CLOSE_RE: Final[re.Pattern[str]] = re.compile(r"^<!--\s*/ssot-quote\s*-->\s*$")

# GitHub-style approximation: keep unicode word characters, whitespace and
# hyphens; drop everything else (punctuation, emoji, colons).
_SLUG_DROP_RE: Final[re.Pattern[str]] = re.compile(r"[^\w\s-]+", re.UNICODE)
_SLUG_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"[\s_]+")


def slugify_heading(text: str) -> str:
    """The pinned heading-slug algorithm (GitHub-style approximation)."""
    lowered = text.strip().lower()
    stripped = _SLUG_DROP_RE.sub("", lowered)
    hyphenated = _SLUG_WHITESPACE_RE.sub("-", stripped)
    return hyphenated.strip("-")


def _fence_mask(lines: list[str]) -> list[bool]:
    """``True`` at index ``i`` when ``lines[i]`` sits inside a fenced block.

    The delimiter lines themselves count as "inside" — a fence opener or
    closer is never a heading or a marker.
    """
    mask = [False] * len(lines)
    in_fence = False
    fence_marker: str | None = None
    for index, line in enumerate(lines):
        match = _FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = None
            mask[index] = True
            continue
        mask[index] = in_fence
    return mask


def resolve_anchor_span(text: str, anchor: str) -> str | None:
    """The raw (un-normalised) section text addressed by ``anchor``, or ``None``.

    Tries an explicit ``<!-- ssot-anchor: anchor -->`` marker first (outside
    fences); falls back to a heading whose :func:`slugify_heading` equals
    ``anchor``. On duplicate slugs, the FIRST matching heading wins.
    """
    lines = text.split("\n")
    mask = _fence_mask(lines)

    current_heading_level = 0
    marker_start: tuple[int, int] | None = None  # (line_after_marker, enclosing_level)
    heading_start: tuple[int, int] | None = None  # (line_after_heading, heading_level)

    for index, line in enumerate(lines):
        if mask[index]:
            continue
        marker_match = _ANCHOR_MARKER_RE.match(line)
        if marker_match and marker_match.group(1) == anchor and marker_start is None:
            marker_start = (index + 1, current_heading_level)
            continue
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            title = _ATX_TRAILING_HASHES_RE.sub("", heading_match.group(2))
            if heading_start is None and marker_start is None and slugify_heading(title) == anchor:
                heading_start = (index + 1, level)
            current_heading_level = level

    start = marker_start if marker_start is not None else heading_start
    if start is None:
        return None
    start_line, enclosing_level = start

    end_line = len(lines)
    for index in range(start_line, len(lines)):
        if mask[index]:
            continue
        heading_match = _HEADING_RE.match(lines[index])
        if heading_match and len(heading_match.group(1)) <= enclosing_level:
            end_line = index
            break

    return "\n".join(lines[start_line:end_line])


@dataclass(frozen=True)
class QuoteBlock:
    """One parsed ``ssot-quote`` block: its declared source and its body."""

    source_path: str
    anchor: str
    body: str


def parse_quote_blocks(text: str) -> list[QuoteBlock]:
    """Every ``ssot-quote`` block in ``text``, outside fenced code blocks.

    A quote's BODY may itself legitimately contain a fence (the quoted
    section had a code snippet); only the open/close MARKER lines are
    fence-excluded, never the content between them.
    """
    lines = text.split("\n")
    mask = _fence_mask(lines)

    blocks: list[QuoteBlock] = []
    index = 0
    while index < len(lines):
        if mask[index]:
            index += 1
            continue
        open_match = _QUOTE_OPEN_RE.match(lines[index])
        if not open_match:
            index += 1
            continue
        source_path = open_match.group(1).strip()
        anchor = open_match.group(2).strip()
        close_index = None
        for candidate in range(index + 1, len(lines)):
            if mask[candidate]:
                continue
            if _QUOTE_CLOSE_RE.match(lines[candidate]):
                close_index = candidate
                break
        if close_index is None:
            break  # unclosed block: ignore rather than guess
        body = "\n".join(lines[index + 1 : close_index])
        blocks.append(QuoteBlock(source_path=source_path, anchor=anchor, body=body))
        index = close_index + 1
    return blocks


def normalise_markdown(text: str) -> str:
    """Normalise ``text`` through the SAME pipeline ``markdown_table_formatter`` uses."""
    return format_markdown_text(text)


def verify_quote(quote_body: str, source_span: str) -> bool:
    """Whether ``quote_body`` verifies against ``source_span``.

    True iff the normalised quote is at least :data:`MIN_QUOTE_LENGTH_CHARS`
    long AND is a contiguous substring of the normalised span.
    """
    normalised_quote = normalise_markdown(quote_body).strip()
    if len(normalised_quote) < MIN_QUOTE_LENGTH_CHARS:
        return False
    normalised_span = normalise_markdown(source_span)
    return normalised_quote in normalised_span
