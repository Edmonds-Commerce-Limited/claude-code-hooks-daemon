"""Bash's ANSI-C ``$'...'`` quoting (Plan 00466 N120).

One decoder for every shell reader. Read as a plain single quote,
``$'it\\'s'`` closes at the escaped quote, and every boundary after it moves:
the write-target tokeniser, the heredoc scanner and the segment splitter all
need to know where the string really ends.
"""

from __future__ import annotations

import re
from typing import Final

#: Escapes an ANSI-C ``$'...'`` string decodes to one character.
_ANSI_C_ESCAPES: Final[dict[str, str]] = {
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "E": "\x1b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "?": "?",
}
#: The numeric and control escapes: octal, ``\xHH``, ``\uHHHH``, ``\UHHHHHHHH``, ``\cX``.
_ANSI_C_NUMERIC_ESCAPE_RE: Final[re.Pattern[str]] = re.compile(
    r"[0-7]{1,3}|x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|U[0-9A-Fa-f]{1,8}|c."
)
_UNICODE_LIMIT: Final[int] = 0x10FFFF
_CONTROL_MASK: Final[int] = 0x1F
_BYTE_MASK: Final[int] = 0xFF
_NUL: Final[str] = "\0"
_QUOTE: Final[str] = "'"
_ESCAPE: Final[str] = "\\"


def ansi_c_string(text: str, index: int) -> tuple[str, int] | None:
    """The value of the ``$'...'`` body starting at ``index``, and the index past
    its closing quote; None if it never closes. Bash ends the value at a NUL."""
    parts: list[str] = []
    ended = False
    while index < len(text):
        char = text[index]
        if char == _QUOTE:
            return "".join(parts), index + 1
        if char == _ESCAPE and index + 1 < len(text):
            escape = text[index + 1]
            numeric = _ANSI_C_NUMERIC_ESCAPE_RE.match(text, index + 1)
            if escape in _ANSI_C_ESCAPES:
                decoded = _ANSI_C_ESCAPES[escape]
                index += 2
            elif numeric is not None:
                decoded = _ansi_c_numeric(numeric.group())
                index = numeric.end()
            else:
                decoded = char + escape
                index += 2
        else:
            decoded = char
            index += 1
        ended = ended or decoded == _NUL
        if not ended:
            parts.append(decoded)
    return None


def _ansi_c_numeric(escape: str) -> str:
    """One numeric or control ANSI-C escape, without its backslash."""
    kind = escape[0]
    if kind == "c":
        return chr(ord(escape[1]) & _CONTROL_MASK)
    if kind in "xuU":
        code = int(escape[1:], 16)
        return chr(code) if code <= _UNICODE_LIMIT else ""
    return chr(int(escape, 8) & _BYTE_MASK)
