"""Blank quoted spans so a MENTIONED phrase is not read as a USED one.

Plan 00225. Content-scanning advisories (dismissive language, hedging language)
match their trigger phrases by plain substring, which cannot separate:

- a phrase USED to deflect  -- "that is out of scope"
- a phrase MENTIONED        -- 'the hook flagged my "out of scope"'

The advisory those detectors emit asks the agent to acknowledge rather than
deflect, and naming the phrase is how one acknowledges — so complying with the
instruction re-triggered it.

The approach mirrors ``pipe_blocker._strip_message_bodies`` (Plan 00222): the
pattern lists are NOT touched. A copy of the text is scanned with the exempt
spans blanked, so a real trigger anywhere else in the same text is still found.
"""

from __future__ import annotations

import re
from typing import Final

# Only DOUBLE quotes and BACKTICKS mark a mention. Single quotes deliberately
# do NOT: an apostrophe inside an ordinary English word ("doesn't", "it's")
# reads as an opening quote, and pairing on those would blank arbitrary spans
# of real sentences. A blanked span is a span the detector can no longer see,
# so that failure mode is silence — strictly worse than the noise being fixed.
# `pipe_blocker` records the same constraint for the same reason.
#
# Each alternative requires a CLOSING delimiter, so an unterminated quote
# matches nothing and the text is scanned intact (fail open).
_QUOTED_SPAN_PATTERN = re.compile(r'"[^"\n]*"|`[^`\n]*`')

# Blanking preserves LENGTH rather than deleting, so character offsets into the
# scanned copy still line up with the original text.
_BLANK_CHARACTER = " "


def blank_quoted_spans(text: str) -> str:
    """Return ``text`` with the contents of quoted spans replaced by spaces.

    The delimiters are blanked along with their contents; only double-quoted
    and backticked spans are affected. Text outside them is returned verbatim,
    so a genuine trigger phrase sitting beside a quotation is still detected.

    Args:
        text: The message text to normalise before pattern matching.

    Returns:
        A same-length copy with quoted spans blanked out.
    """
    if not text:
        return text

    return _QUOTED_SPAN_PATTERN.sub(lambda m: _BLANK_CHARACTER * len(m.group(0)), text)


# Characters that begin a command substitution inside a DOUBLE-quoted shell
# span. Their presence means the span still runs a command, so blanking it
# would hide that command from the scanner rather than exempt a literal.
_SUBSTITUTION_MARKERS: Final[tuple[str, ...]] = ("$(", "`")

_SINGLE_QUOTE: Final[str] = "'"
_DOUBLE_QUOTE: Final[str] = '"'
_BACKSLASH: Final[str] = "\\"


def blank_shell_literal_spans(command: str) -> str:
    """Return ``command`` with non-executing quoted spans blanked out.

    Shell quoting is not prose quoting, so this is a SIBLING of
    :func:`blank_quoted_spans` rather than a reuse of it:

    - Single-quoted spans are fully literal in a shell — nothing expands inside
      them — so they are always blanked. (:func:`blank_quoted_spans` excludes
      single quotes because an apostrophe in "doesn't" reads as an opening
      quote; that hazard is a property of PROSE and does not apply here.)
    - Double-quoted spans are blanked ONLY when they contain no command
      substitution. Bash expands ``$(...)`` and backticks inside double quotes,
      so blanking such a span would conceal a command that really does run.
    - Backticked spans are never blanked, for the same reason.

    A single left-to-right pass tracks quote state rather than running two
    independent regex passes, because a regex pass over single quotes would
    mis-pair an apostrophe sitting inside a double-quoted span.

    An unterminated quote blanks nothing from the opening delimiter onward, so
    a malformed command is scanned intact (fail open — a missed exemption costs
    a false positive, a missed scan costs a false negative).

    Args:
        command: The raw Bash command string.

    Returns:
        A same-length copy with non-executing quoted spans blanked out.
    """
    if not command:
        return command

    characters = list(command)
    index = 0
    length = len(characters)

    while index < length:
        character = characters[index]

        if character == _BACKSLASH:
            # An escaped character cannot open or close a quote.
            index += 2
            continue

        if character not in (_SINGLE_QUOTE, _DOUBLE_QUOTE):
            index += 1
            continue

        closing = command.find(character, index + 1)
        if closing == -1:
            # Unterminated quote: leave the remainder intact.
            break

        span = command[index : closing + 1]
        executes = character == _DOUBLE_QUOTE and any(
            marker in span for marker in _SUBSTITUTION_MARKERS
        )
        if executes:
            # Step INTO the span rather than over it. The substitution runs a
            # real command, and that command has its own literals -- the single
            # quotes around a grep pattern in `"$(grep -E '...' f)"` still need
            # blanking. Skipping to the closing quote would leave them visible.
            index += 1
            continue

        for position in range(index, closing + 1):
            characters[position] = _BLANK_CHARACTER

        index = closing + 1

    return "".join(characters)
