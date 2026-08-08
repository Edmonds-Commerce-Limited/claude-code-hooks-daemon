"""Split a Bash command string into top-level segments.

Handlers that decide *what command is actually being run* need to know where one
command ends and the next begins, and must treat a separator inside a quoted
argument as DATA rather than syntax. Getting that wrong in either direction is a
real defect:

- split too eagerly and a quoted ``;`` cuts the producer in half, so a
  legitimate command is denied because its resolved name is a fragment;
- split too lazily and a separator is missed, so the guarded command inherits
  the leading word of a harmless one and the handler is bypassed.

This module exists because two handlers grew their own scanner and each got the
opposite half of the escape rule, producing the same bypass from opposite causes
(Plan 00200 Task 3.7). One scanner, one set of rules, one place to fix.

Deliberately a scanner, not a shell parser. Command substitution, heredocs,
process substitution and arithmetic expansion are out of scope: callers only
need the boundaries between top-level segments.
"""

from __future__ import annotations

from collections.abc import Sequence

# Bash quoting characters. Inside single quotes NOTHING is special except the
# closing quote -- in particular a backslash is a literal backslash, which is
# the rule a scanner that escapes everywhere gets wrong.
_SINGLE_QUOTE = "'"
_DOUBLE_QUOTE = '"'

# A backslash escapes exactly the next character, everywhere EXCEPT inside
# single quotes. A scanner blind to it flips its quote state on an escaped quote
# and never leaves quoted mode.
_ESCAPE_CHAR = "\\"


def split_unquoted(text: str, separators: Sequence[str]) -> list[str]:
    """Split ``text`` on ``separators`` that appear outside quotes.

    Args:
        text: The raw command string.
        separators: Separator strings to split on. Multi-character separators
            (``&&``, ``||``) are matched whole, so order them longest-first when
            one is a prefix of another.

    Returns:
        The segments, quote characters and escapes preserved verbatim so callers
        can pattern-match them. Always at least one element; separators
        themselves are not included.

    Examples:
        >>> split_unquoted("cd x\\ngrep y", (";", "\\n"))
        ['cd x', 'grep y']
        >>> split_unquoted('grep -E "a;b"', (";",))
        ['grep -E "a;b"']
    """
    segments: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    index = 0

    while index < len(text):
        char = text[index]

        # Rule 1: inside single quotes a backslash is literal, so escape
        # handling is skipped entirely and only the closing quote matters.
        if char == _ESCAPE_CHAR and not in_single:
            current.append(char)
            index += 1
            if index < len(text):
                current.append(text[index])
                index += 1
            continue

        if char == _SINGLE_QUOTE and not in_double:
            in_single = not in_single
        elif char == _DOUBLE_QUOTE and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            matched = next((sep for sep in separators if text.startswith(sep, index)), None)
            if matched is not None:
                segments.append("".join(current))
                current = []
                index += len(matched)
                continue

        current.append(char)
        index += 1

    segments.append("".join(current))
    return segments
