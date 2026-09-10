"""LSP-noise strategy shared utilities (DRY across per-language strategies).

Only logic used by 3+ strategies belongs here, per the Strategy Pattern
archetype's rule (``CLAUDE/Code/StrategyPattern.md``) - everything else stays
in its own language's strategy file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: Prefix marking an any-depth glob entry, e.g. ``**/venv``.
_ANY_DEPTH_PREFIX = "**/"


@dataclass(frozen=True, slots=True)
class ConfigView:
    """What a strategy learnt about a project's JSON-with-``exclude`` config.

    Shared by ``python_strategy.py`` and ``typescript_strategy.py`` (both
    read a top-level ``exclude`` array). Defined here rather than in either
    strategy file so ``qa/strategy_pattern_checker.py``'s per-class
    acceptance-test check - which scans every class in a ``*_strategy.py``
    file - sees only the actual strategy class in each of those files.
    """

    path: Path | None
    where: str
    exclude: list[str] | None
    parse_error: str | None = None


@dataclass(frozen=True, slots=True)
class OverrideView:
    """What a strategy learnt about a discovered project-scope LSP override.

    Used by ``php_strategy.py``, whose language has no config file of its
    own to read - defined here for the same reason as :class:`ConfigView`.
    """

    path: Path | None
    exclude: list[str] | None


def entry_covers(entry: str, required: str) -> bool:
    """Whether one configured exclude entry keeps ``required`` out of analysis.

    A trailing slash is ignored. An entry covers a path it equals or is a
    parent of; a bare name covers its any-depth glob (``venv`` covers
    ``**/venv``), and the glob covers its bare name.
    """
    have = entry.rstrip("/")
    want = required.rstrip("/")
    if not have or not want:
        return False
    if have == want or want.startswith(have + "/"):
        return True
    have_name = have.removeprefix(_ANY_DEPTH_PREFIX)
    want_name = want.removeprefix(_ANY_DEPTH_PREFIX)
    return have_name == want_name


def json_list(entries: list[str]) -> list[str]:
    """Entries rendered one per line, quoted and comma-terminated for pasting."""
    return [f'  "{entry}",' for entry in entries]


def strip_jsonc_comments(text: str) -> str:
    """Strip ``//`` line and ``/* */`` block comments from JSONC text.

    A minimal, string-aware stripper - not a JSON5 parser. It tracks
    whether it is inside a double-quoted string (respecting ``\\"``
    escapes) so a literal ``//`` or ``/*`` inside a path string is never
    mistaken for a comment. Comment spans are replaced with a single space
    per character removed, so reported line/column positions in a
    subsequent parse error stay aligned with the original file.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    length = len(text)
    while i < length:
        char = text[i]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue
        if char == "/" and i + 1 < length and text[i + 1] == "/":
            while i < length and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if char == "/" and i + 1 < length and text[i + 1] == "*":
            out.append("  ")
            i += 2
            while i + 1 < length and not (text[i] == "*" and text[i + 1] == "/"):
                out.append(" " if text[i] != "\n" else "\n")
                i += 1
            out.append("  ")
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def tree_contains_extension(
    root: Path, relative_tree: str, extension: str, *, prune_names: frozenset[str]
) -> bool:
    """Whether ``root/relative_tree`` contains any ``extension`` file.

    Early-exits on the first match, and prunes any directory named in
    ``prune_names`` (the vendored/build names already covered by their own
    required-exclude entry, so a language server's own multi-gigabyte
    ``node_modules``-style dependency tree is never walked twice). A tree
    that does not exist reports False, never raises: this feeds a
    session-start advisory, not a decision path.
    """
    base = root / relative_tree
    if not base.exists():
        return False
    if base.is_file():
        return base.suffix == extension
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in prune_names]
        if any(name.endswith(extension) for name in filenames):
            return True
    return False
