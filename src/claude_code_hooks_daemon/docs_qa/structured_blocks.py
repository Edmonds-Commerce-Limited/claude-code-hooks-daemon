"""Structured-block extraction for check ``duplicate-block`` (Plan 00284).

R4 names three CONTENT CLASSES that drift harmfully when copied — fenced
code/command blocks, tables, and enumerated lists (numbered or bulleted).
This module extracts every such block from a document's markdown text and
reduces it to a normalised hash, so :mod:`docs_qa.corpus` can index them and
:mod:`docs_qa.checks.duplicate_block` can find the SAME block hash appearing
in two different documents — cheap set-membership, no pairwise text diffing.

Two exclusions apply before scanning, both deliberate:

- **``ssot-quote`` bodies are stripped first** (R4b): a tracked verbatim
  quote is deliberate, checked repetition with its own drift check
  (``quote-drift``); it is not general duplication and must never also
  surface here. The strip is marker-to-marker, not fence-aware — the same
  simplification :mod:`docs_qa.checks.module_doc_budget` already makes for
  its own line-count purpose, since precise fence-awareness only matters for
  VERIFICATION (``quotes.py``'s ``resolve_anchor_span``), not for excluding a
  span wholesale from a size/hash count.
- **A length floor** (:data:`MIN_BLOCK_LENGTH_CHARS`, applied to the
  NORMALISED block) drops tiny blocks outright. The design's own worked
  example is the two-line ``./bin/hooks-daemon restart`` /
  ``./bin/hooks-daemon status`` fence pair that recurs throughout this
  project's own docs — at ~54 raw characters it sits far below the floor,
  so it is never even considered a duplicate candidate. A short block also
  protects nothing even when genuinely repeated: near-identical short
  fences are common and mostly harmless, unlike a repeated multi-row table
  or a repeated multi-step procedure. 120 characters is comfortably above
  that pair (with fence markers) while still catching a real table (a
  header + delimiter + at least one data row) or a real fenced example.

Normalisation reuses :func:`docs_qa.quotes.normalise_markdown` — the SAME
mdformat-gfm pipeline ``quote-drift`` and ``markdown_table_formatter`` use —
so two syntactically-equivalent renderings of the same table (different
delimiter-row padding, for instance) hash identically rather than
false-drifting on formatter churn.
"""

import hashlib
import re
from typing import Final

from claude_code_hooks_daemon.docs_qa.quotes import normalise_markdown

# A one-line quote is a substring of almost anything (quotes.py's own
# rationale); a tiny structured block is the same story here -- see the
# module docstring for the worked example this floor is sized against.
MIN_BLOCK_LENGTH_CHARS: Final[int] = 120

# R4's "enumerated lists" -- a run this short is common, ordinary prose
# structure, not the kind of multi-step procedure that drifts harmfully
# when copied.
MIN_LIST_ITEMS: Final[int] = 3

# A GFM table needs at least a header row and a delimiter row to be real
# table syntax; a lone pipe-containing line is not a table.
_MIN_TABLE_ROWS: Final[int] = 2

_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(```|~~~)")
_TABLE_ROW_RE: Final[re.Pattern[str]] = re.compile(r"^\s*\|.*\|\s*$")
_ORDERED_ITEM_RE: Final[re.Pattern[str]] = re.compile(r"^\s{0,3}\d+[.)]\s+\S")
_UNORDERED_ITEM_RE: Final[re.Pattern[str]] = re.compile(r"^\s{0,3}[-*+]\s+\S")

# Marker-to-marker strip of ssot-quote block bodies -- not fence-aware, the
# same simplification module_doc_budget.py already makes for its own
# line-count purpose (see module docstring).
_QUOTE_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"<!--\s*ssot-quote:[^\n]+-->.*?<!--\s*/ssot-quote\s*-->",
    re.DOTALL,
)


def _strip_quote_blocks(text: str) -> str:
    return _QUOTE_BLOCK_RE.sub("", text)


def _is_list_item(line: str) -> bool:
    return bool(_ORDERED_ITEM_RE.match(line) or _UNORDERED_ITEM_RE.match(line))


def extract_structured_blocks(text: str) -> list[str]:
    """Every structured block (fence / table / list-run) in ``text``, raw text,
    in document order. ``ssot-quote`` bodies are excluded first (R4b).

    A run below its class's minimum (an unclosed fence, a single pipe line,
    a list run under :data:`MIN_LIST_ITEMS`) is skipped, not guessed at --
    the same "ignore rather than guess" discipline
    :func:`docs_qa.quotes.parse_quote_blocks` applies to an unclosed quote
    marker.
    """
    lines = _strip_quote_blocks(text).split("\n")
    line_count = len(lines)
    blocks: list[str] = []
    index = 0
    while index < line_count:
        line = lines[index]

        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            close_index = None
            for candidate in range(index + 1, line_count):
                candidate_match = _FENCE_RE.match(lines[candidate])
                if candidate_match and candidate_match.group(1) == marker:
                    close_index = candidate
                    break
            if close_index is None:
                break  # unclosed fence: nothing after it can be scanned safely
            blocks.append("\n".join(lines[index : close_index + 1]))
            index = close_index + 1
            continue

        if _TABLE_ROW_RE.match(line):
            end = index
            while end < line_count and _TABLE_ROW_RE.match(lines[end]):
                end += 1
            if end - index >= _MIN_TABLE_ROWS:
                blocks.append("\n".join(lines[index:end]))
            index = end
            continue

        if _is_list_item(line):
            end = index
            item_count = 0
            while end < line_count and _is_list_item(lines[end]):
                item_count += 1
                end += 1
            if item_count >= MIN_LIST_ITEMS:
                blocks.append("\n".join(lines[index:end]))
            index = end
            continue

        index += 1
    return blocks


def extract_structured_block_hashes(text: str) -> tuple[str, ...]:
    """Normalised sha256 hex digests of every over-floor structured block,
    in document order. May contain the same hash more than once if a
    document repeats a block internally -- callers that need a per-document
    SET should dedupe with ``set(...)`` themselves."""
    hashes: list[str] = []
    for raw_block in extract_structured_blocks(text):
        normalised = normalise_markdown(raw_block).strip()
        if len(normalised) < MIN_BLOCK_LENGTH_CHARS:
            continue
        hashes.append(hashlib.sha256(normalised.encode("utf-8")).hexdigest())
    return tuple(hashes)
