"""Shared bash safety-flag detection and statement splitting.

ONE home for the analysis that ``verification_result_gate`` (Plan 00268) and
``bash_safe_mode`` (Plan 00270) both need: splitting a Bash invocation into
unconditionally-sequenced statements, and recognising which ``set`` safety
flags (errexit / pipefail / nounset) the invocation already declares. DRY
forbids each handler growing its own ``set`` parser — the two must agree on
what counts as a prelude, or one hand of the daemon would demand what the
other cannot see.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from claude_code_hooks_daemon.utils.command_evasion import normalise_line_continuations
from claude_code_hooks_daemon.utils.shell_segmentation import (
    split_unquoted,
    strip_quoted_heredoc_bodies,
)

#: Canonical flag names, as spelt by ``set -o``.
FLAG_ERREXIT: Final = "errexit"
FLAG_PIPEFAIL: Final = "pipefail"
FLAG_NOUNSET: Final = "nounset"

#: Every safety flag this module can detect.
SAFE_MODE_FLAGS: Final[tuple[str, ...]] = (FLAG_ERREXIT, FLAG_PIPEFAIL, FLAG_NOUNSET)

#: Statements run UNCONDITIONALLY with respect to each other. A newline is a
#: command terminator in shell exactly as ``;`` is.
STATEMENT_SEPARATORS: Final[tuple[str, ...]] = (";", "\n")

#: Within one statement, these separate the individual command spans.
#: Longest-first per ``split_unquoted``'s contract, so ``||`` is never read as
#: two ``|``.
SPAN_SEPARATORS: Final[tuple[str, ...]] = ("||", "&&", "|")

#: A ``set`` builtin at the head of a statement, capturing its arguments.
_SET_STATEMENT: Final[re.Pattern[str]] = re.compile(r"^\s*set\s+(?P<args>\S.*)$")

#: Single-letter cluster flags that map to a safety flag (``set -eu``).
_SHORT_FLAGS: Final[dict[str, str]] = {"e": FLAG_ERREXIT, "u": FLAG_NOUNSET}

#: Long option names accepted after ``-o`` (``set -o pipefail``).
_OPTION_NAMES: Final[dict[str, str]] = {
    FLAG_ERREXIT: FLAG_ERREXIT,
    FLAG_PIPEFAIL: FLAG_PIPEFAIL,
    FLAG_NOUNSET: FLAG_NOUNSET,
}

_DASH: Final = "-"
_OPTION_LETTER: Final = "o"


def split_statements(command: str) -> list[str]:
    """Split ``command`` into stripped, non-empty sequenced statements.

    Line continuations are joined first and quoted-delimiter heredoc bodies
    removed, so a ``;`` inside a literal heredoc never manufactures a
    statement boundary.
    """
    normalised = strip_quoted_heredoc_bodies(normalise_line_continuations(command))
    return [
        statement.strip()
        for statement in split_unquoted(normalised, STATEMENT_SEPARATORS)
        if statement.strip()
    ]


def detect_safe_mode_flags(statements: Iterable[str]) -> frozenset[str]:
    """The safety flags declared by ``set`` statements in ``statements``.

    Recognised spellings: short clusters (``set -e``, ``set -eu``), long
    options (``set -o errexit``), and the combined ``set -euo pipefail`` where
    an ``o`` in a cluster takes the FOLLOWING token as its option name. A
    ``set +e`` (disabling) or an unrelated flag detects nothing — this scanner
    answers "was the flag ever declared", the same question the Plan 00268
    errexit pattern answered.
    """
    found: set[str] = set()
    for statement in statements:
        match = _SET_STATEMENT.match(statement)
        if match is None:
            continue
        expect_option_name = False
        for token in match.group("args").split():
            if expect_option_name:
                flag = _OPTION_NAMES.get(token)
                if flag is not None:
                    found.add(flag)
                expect_option_name = False
                continue
            if not token.startswith(_DASH) or token.startswith(_DASH * 2):
                continue
            for letter in token[1:]:
                if letter == _OPTION_LETTER:
                    expect_option_name = True
                elif letter in _SHORT_FLAGS:
                    found.add(_SHORT_FLAGS[letter])
    return frozenset(found)


def has_errexit(statements: Iterable[str]) -> bool:
    """True when any statement declares errexit in any recognised spelling."""
    return FLAG_ERREXIT in detect_safe_mode_flags(statements)
