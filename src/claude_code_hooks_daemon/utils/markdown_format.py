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
import yaml

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


#: The lenient frontmatter fallback's line shapes: an UNINDENTED
#: ``key: rest-of-line`` (the rest taken literally, colons and all), and an
#: indented ``- item`` under a key whose own value was empty.
_LENIENT_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$")
_LENIENT_LIST_ITEM_RE: Final[re.Pattern[str]] = re.compile(r"^\s+-\s+(.*)$")
#: The shortest string that can be a quoted value: the two quotes alone.
_QUOTED_MIN_LENGTH: Final[int] = 2


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


def parse_frontmatter_yaml(content: str) -> dict[str, Any] | None:
    """Parse ``content``'s leading YAML frontmatter into a dict, or None.

    Public because more than one caller needs a frontmatter MAPPING rather
    than the raw block :func:`split_frontmatter` returns — Plan 00460's
    subagent tool resolver reads a `.claude/agents/*.md` file's `tools`/
    `disallowedTools` fields this way. Reuses :func:`split_frontmatter` (the
    project's one splitter) rather than adding a second one.

    Returns None whenever there is nothing safe to act on: no frontmatter
    block, invalid YAML, or YAML that parses to something other than a
    mapping (a list, a scalar). A caller that cannot tell "absent" from
    "malformed" apart from None would have to guess; every caller here wants
    the same fail-safe answer for both.
    """
    block, _body = split_frontmatter(content)
    if not block:
        return None
    inner = block.split("\n", 1)[1].rsplit("---", 1)[0]
    try:
        loaded = yaml.safe_load(inner)
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


def parse_frontmatter_lenient(content: str) -> dict[str, Any] | None:
    """Parse frontmatter as YAML, else by top-level ``key: rest-of-line`` lines.

    Claude Code loads agent and skill files that strict YAML rejects: a
    description holding ``: `` is enough (``mapping values are not allowed
    here``). Plan 00468 audit P6 found this repository's own
    ``code-reviewer.md`` invisible to the daemon for exactly that reason. So
    valid YAML is parsed exactly as :func:`parse_frontmatter_yaml` does, and
    only a failure falls back to reading each unindented ``key: value`` line
    with the value taken literally to the end of the line.

    The fallback also collects an indented ``- item`` list under an empty
    key, folds any other indented line into the value above it, strips one
    pair of matching quotes, and maps an empty value to None, as YAML does.

    Returns None when there is no frontmatter block, or when the block holds
    no key line at all.
    """
    strict = parse_frontmatter_yaml(content)
    if strict is not None:
        return strict
    block, _body = split_frontmatter(content)
    if not block:
        return None
    inner = block.split("\n", 1)[1].rsplit("---", 1)[0]

    parsed: dict[str, Any] = {}
    current: str | None = None
    for line in inner.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key_match = _LENIENT_KEY_RE.match(line)
        if key_match is not None:
            key = str(key_match.group(1))
            parsed[key] = _unquote(key_match.group(2).strip()) or None
            current = key
            continue
        if current is None or line[:1] not in (" ", "\t"):
            continue
        item_match = _LENIENT_LIST_ITEM_RE.match(line)
        existing = parsed[current]
        if item_match is not None and (existing is None or isinstance(existing, list)):
            parsed[current] = [*(existing or []), _unquote(item_match.group(1).strip())]
        elif isinstance(existing, str):
            parsed[current] = f"{existing} {stripped}"
    return parsed or None


def _unquote(value: str) -> str:
    """``value`` without one pair of matching surrounding quotes."""
    if len(value) >= _QUOTED_MIN_LENGTH and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


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
