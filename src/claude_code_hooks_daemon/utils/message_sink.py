"""The teamchat message-verb sink (Ledger 00474 N744 reopened, N760).

A teamchat message verb reads its text on stdin, so the text is posted, never
opened, expanded or run. :func:`message_sink_view` recognises the WHOLE command
as one plain message-verb statement fed by exactly one of:

* a quoted-delimiter heredoc (``<<'EOF'`` or ``<<"EOF"``) that is the last word
  of the first line, whose closing line is the last line of the command;
* a single-quoted here-string (``<<< '...'``) that ends the command;
* one ``printf`` or ``echo`` of literal quoted words only, piped in by a single
  ``|``.

It returns the command with the message removed, ``teamchat <verb> <words>``,
so the teamchat words (a member name, a ``--ref path:...``) are still judged by
the caller. Anything else returns None and relaxes nothing.

The grammar is closed by construction and does not reuse the general shell
readers: a teamchat word is a bare word of :data:`_BARE_WORD` or ONE whole
quoted word holding no expansion; words are separated by spaces only; any other
character, an unknown ``--flag``, a redirect, chain, extra pipe, substitution or
variable voids it. Residual risk (stated to the owner): a sink that echoes its
stdin to a file would not be covered; teamchat does not.
"""

from __future__ import annotations

import re
from typing import Final

#: The only command name the sink accepts; a path, wrapper or assignment voids it.
MESSAGE_SINK_HEAD: Final[str] = "teamchat"
#: The verbs whose text arrives on stdin (``teamchat help``).
MESSAGE_SINK_VERBS: Final[frozenset[str]] = frozenset(
    {"say", "reply", "report", "thread", "ask-human", "close", "retitle"}
)
#: Every flag the message verbs take; none opens a file. Any other option voids.
_SINK_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "--to",
        "--to-coordinator",
        "--wait-contact",
        "--team",
        "--verb",
        "--ref",
        "--for",
        "--re",
        "--remind-after",
        "--check",
        "--skeleton",
        "--note",
    }
)
_QUOTES: Final[str] = "'\""
_PRINTF: Final[str] = "printf"
_ECHO: Final[str] = "echo"
#: A word bash passes on unchanged: no glob, tilde, expansion, quote or operator.
_BARE_WORD: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_@%+=:,./-]+")
#: One whole single-quoted word on one line: bash expands nothing inside it.
_SINGLE_QUOTED_LINE: Final[re.Pattern[str]] = re.compile(r"'[^'\n]*'")
#: One whole double-quoted word with nothing bash would expand or escape inside.
_DOUBLE_QUOTED_LINE: Final[re.Pattern[str]] = re.compile(r'"[^"$`\\!\n]*"')
#: The literal words a producer prints: single quotes may span lines.
_PRODUCER_WORD: Final[re.Pattern[str]] = re.compile(r"'[^']*'|\"[^\"$`\\!]*\"")
#: A quoted heredoc operator ending the first line, and its delimiter.
_HEREDOC_TAIL: Final[re.Pattern[str]] = re.compile(
    r" +<<(?:'(?P<single>[A-Za-z_][A-Za-z0-9_]*)'|\"(?P<double>[A-Za-z_][A-Za-z0-9_]*)\")$"
)
#: A single-quoted here-string ending the command.
_HERE_STRING_TAIL: Final[re.Pattern[str]] = re.compile(r" +<<< *'[^']*'[ \t\n]*\Z")
#: What bash treats as blank around a statement; never Unicode whitespace.
_BASH_BLANKS: Final[str] = " \t\n"
#: The one pipe a producer may use: a lone ``|`` between spaces.
_PIPE: Final[re.Pattern[str]] = re.compile(r" +\| +")


def _teamchat_words(line: str) -> list[str] | None:
    """The words of ``teamchat <verb> ...`` when every one is plain, else None."""
    words = line.strip(" ").split(" ")
    words = [word for word in words if word]
    if len(words) < 2 or words[0] != MESSAGE_SINK_HEAD or words[1] not in MESSAGE_SINK_VERBS:
        return None
    for word in words[2:]:
        if not (
            _BARE_WORD.fullmatch(word)
            or _SINGLE_QUOTED_LINE.fullmatch(word)
            or _DOUBLE_QUOTED_LINE.fullmatch(word)
        ):
            return None
        if word[0] in _QUOTES and word[1:].startswith("-"):
            # A quoted option reaches teamchat as an option the list never saw.
            return None
        if word.startswith("-") and word.split("=", 1)[0] not in _SINK_FLAGS:
            return None
    return words


def _view(line: str) -> str | None:
    words = _teamchat_words(line)
    return None if words is None else " ".join(words)


def _heredoc_view(command: str) -> str | None:
    first, newline, rest = command.partition("\n")
    tail = _HEREDOC_TAIL.search(first)
    if tail is None or not newline:
        return None
    delimiter = tail.group("single") or tail.group("double")
    lines = rest.split("\n")
    if delimiter not in lines:
        return None
    after = lines[lines.index(delimiter) + 1 :]
    if any(line.strip(_BASH_BLANKS) for line in after):
        return None
    return _view(first[: tail.start()])


def _here_string_view(command: str) -> str | None:
    tail = _HERE_STRING_TAIL.search(command)
    if tail is None or "\n" in command[: tail.start()]:
        return None
    return _view(command[: tail.start()])


def _is_literal_producer(text: str) -> bool:
    """``printf``/``echo`` followed only by literal quoted words, none an option."""
    head, _, rest = text.strip(" ").partition(" ")
    if head not in (_PRINTF, _ECHO):
        return False
    remaining = rest.strip(" ")
    count = 0
    while remaining:
        word = _PRODUCER_WORD.match(remaining)
        if word is None:
            return False
        if word.group(0)[1:].startswith("-"):
            return False
        count += 1
        remaining = remaining[word.end() :]
        if remaining and not remaining.startswith(" "):
            return False
        remaining = remaining.lstrip(" ")
    return count > 0 or head == _ECHO


def _pipe_view(command: str) -> str | None:
    body = command.rstrip(_BASH_BLANKS)
    pipes = list(_PIPE.finditer(body))
    if not pipes:
        return None
    pipe = pipes[-1]
    sink = body[pipe.end() :]
    if "\n" in sink or not _is_literal_producer(body[: pipe.start()]):
        return None
    return _view(sink)


def message_sink_view(command: str) -> str | None:
    """``teamchat <verb> <words>`` when ``command`` is exactly one sink statement, else None.

    Args:
        command: The whole Bash tool command.

    Returns:
        The command with its stdin message removed, or None when it is any other
        shape (then nothing is relaxed and the caller judges it whole).
    """
    if MESSAGE_SINK_HEAD not in command:
        return None
    if "<<<" in command:
        found = _here_string_view(command)
        if found is not None:
            return found
    if "<<" in command.partition("\n")[0]:
        return _heredoc_view(command)
    return _pipe_view(command)
