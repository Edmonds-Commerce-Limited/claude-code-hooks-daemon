"""Shared markdown formatting transform (mdformat + mdformat-gfm).

Single source of truth for the canonical markdown reformat used by:

- the ``markdown_table_formatter`` PostToolUse handler (after Write/Edit of .md),
- the ``format-markdown`` CLI command, and
- the CLAUDE.md injector (after writing the ``<hooksdaemon>`` block).

Extracting the transform here keeps the frontmatter-preserving,
thematic-break-restoring reformat byte-for-byte identical across all three
call sites, so a file formatted by one is already canonical for the others
(no churn diff when a later Write/Edit triggers the PostToolUse formatter).
"""

import re
from typing import Any, Final

import mdformat

# mdformat extensions: enable GFM tables, strikethrough, task lists, autolinks.
_MDFORMAT_EXTENSIONS: Final[set[str]] = {"gfm"}

# Preserve consecutive ordered-list numbering (1. 2. 3.) instead of the
# default which renumbers every item to 1.
_MDFORMAT_OPTIONS: Final[dict[str, Any]] = {"number": True}

# mdformat hardcodes thematic breaks as 70 underscores. Post-process back to
# the more common ``---`` form.
_THEMATIC_BREAK_UNDERSCORES: Final[str] = "_" * 70
_THEMATIC_BREAK_DASHES: Final[str] = "---"

# YAML frontmatter: ``---`` on line 1, YAML body, then a closing ``---`` on
# its own line. mdformat does not understand frontmatter and would mangle it
# into a thematic break + heading, so we strip it before formatting and
# re-attach it byte-for-byte afterwards. Non-greedy body so nested ``---``
# thematic breaks in the document are never swallowed.
_FRONTMATTER_RE: Final[re.Pattern[str]] = re.compile(
    r"\A(---\r?\n.*?\r?\n---\r?\n)(.*)\Z",
    re.DOTALL,
)


def _restore_thematic_breaks(content: str) -> str:
    """Replace mdformat's 70-underscore thematic break with ``---``."""
    return "\n".join(
        _THEMATIC_BREAK_DASHES if line == _THEMATIC_BREAK_UNDERSCORES else line
        for line in content.split("\n")
    )


def split_frontmatter(content: str) -> tuple[str, str]:
    """Split leading YAML frontmatter from the document body.

    Public because it is the project's single frontmatter splitter: Plan
    00326's remote-docs provenance parser reuses it rather than adding a
    second, subtly different one.

    Returns ``("", content)`` when there is no frontmatter, otherwise
    ``(frontmatter_block, body)`` where ``frontmatter_block`` includes both
    ``---`` delimiters and the trailing newline so it can be concatenated
    with the formatted body directly.
    """
    match = _FRONTMATTER_RE.match(content)
    if match is None:
        return "", content
    return match.group(1), match.group(2)


def format_markdown_text(content: str) -> str:
    """Return ``content`` reformatted via mdformat+gfm, preserving frontmatter.

    The transform is: split off any YAML frontmatter, run mdformat (GFM tables,
    consecutive ordered-list numbering) on the body, restore ``---`` thematic
    breaks, then re-attach the frontmatter.

    May raise: mdformat can raise parser/IO/unicode errors. Callers decide how
    to handle — the handler and injector fail safe (allow/skip), the CLI
    reports the error per file.
    """
    frontmatter, body = split_frontmatter(content)
    formatted_body = mdformat.text(
        body,
        extensions=_MDFORMAT_EXTENSIONS,
        options=_MDFORMAT_OPTIONS,
    )
    formatted_body = _restore_thematic_breaks(formatted_body)
    # Ensure a blank line separates frontmatter from body — mdformat strips
    # leading whitespace, so without this the closing ``---`` delimiter would
    # butt directly against the first body line.
    if frontmatter and formatted_body and not formatted_body.startswith("\n"):
        formatted_body = "\n" + formatted_body
    return frontmatter + formatted_body
