"""Static reading of ``for NAME in WORDS; do ... done`` loops.

The shell word scanner collapses every ``$VAR`` it cannot resolve to a lone
``*``, which the secret guard then expands against the working directory
(ledger 00474 N350: ``for d in repos/*; do git -C "$d" ls-files; done`` was
denied because ``"$d"`` became ``*`` and the directory holds a protected file).

A ``for`` variable is the one variable whose value a static reader CAN know:
inside the loop body it is one of the listed words. This module finds those
loops and reports, per loop, the variable, the raw listed words and the span
of the body. It reads with certainty or not at all: a command with any shape
that could change the variable another way, or that this reader cannot place
(heredocs, ``$'...'``, command substitutions in the list, a name assigned
anywhere), binds nothing, and the caller keeps its fail-closed ``*``.
"""

import re
from dataclasses import dataclass
from typing import Final

#: Characters that end an unquoted shell word (mirrors the word scanner's own).
_SEPARATORS: Final[str] = " \t\n;|&<>()"
_BLANKS: Final[str] = " \t"
_LIST_END_SEPARATORS: Final[frozenset[str]] = frozenset(";\n")
_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

#: Words whose presence means the variable might be changed in a way the
#: reader does not follow, so no loop in the command is bound.
_VARIABLE_CHANGING_WORDS: Final[frozenset[str]] = frozenset(
    {
        "read",
        "declare",
        "typeset",
        "local",
        "readonly",
        "export",
        "unset",
        "eval",
        "getopts",
        "mapfile",
        "readarray",
        "let",
        "source",
        ".",
        "-v",
    }
)

_UNREADABLE_MARKERS: Final[tuple[str, ...]] = ("<<", "$'")
_UNREADABLE_LIST_MARKERS: Final[tuple[str, ...]] = ("$(", "`", "<(", ">(")


@dataclass(frozen=True)
class LoopBinding:
    """One ``for`` loop: its variable, listed words and body span.

    ``body_start`` is just past the ``do`` keyword and ``body_end`` is the
    index of the matching ``done``; both index the command text.
    """

    name: str
    raw_values: tuple[str, ...]
    body_start: int
    body_end: int


@dataclass(frozen=True)
class _Token:
    raw: str
    start: int
    end: int
    separators_before: str


def _scan_quoted(text: str, index: int) -> int:
    """Index just past the quoted span or escape that begins at ``text[index]``."""
    n = len(text)
    char = text[index]
    if char == "\\":
        return min(index + 2, n)
    quote = char
    index += 1
    while index < n and text[index] != quote:
        index += 2 if quote == '"' and text[index] == "\\" else 1
    return min(index + 1, n)


def _tokenise(text: str) -> list[_Token]:
    """The unquoted words of ``text`` with the separators that precede each."""
    tokens: list[_Token] = []
    n = len(text)
    i = 0
    separators = ""
    while i < n:
        char = text[i]
        if char in _SEPARATORS:
            separators += char
            i += 1
            continue
        if char == "#":
            comment_end = text.find("\n", i)
            i = n if comment_end == -1 else comment_end
            continue
        start = i
        while i < n and text[i] not in _SEPARATORS:
            i = _scan_quoted(text, i) if text[i] in "'\"\\" else i + 1
        tokens.append(_Token(text[start:i], start, i, separators))
        separators = ""
    return tokens


def _list_end(tokens: list[_Token], after_in: int) -> int | None:
    """Index of the ``do`` token ending a word list that starts at ``after_in``."""
    for index in range(after_in, len(tokens)):
        token = tokens[index]
        gap = token.separators_before.strip(_BLANKS)
        if token.raw == "do" and gap and set(gap) <= _LIST_END_SEPARATORS:
            return index
        if gap or any(marker in token.raw for marker in _UNREADABLE_LIST_MARKERS):
            return None
    return None


def _matching_done(tokens: list[_Token], after_do: int) -> int | None:
    """Index of the ``done`` closing the loop whose ``do`` precedes ``after_do``."""
    depth = 1
    for index in range(after_do, len(tokens)):
        if tokens[index].raw == "do":
            depth += 1
        elif tokens[index].raw == "done":
            depth -= 1
            if depth == 0:
                return index
    return None


def _assignment_pattern(name: str) -> re.Pattern[str]:
    escaped = re.escape(name)
    return re.compile(rf"(?<![\w$]){escaped}(?:\s*(?:\+\+|--)|\s*[-+*/%&|^:]?=(?!=))")


def find_for_loop_bindings(command: str) -> tuple[LoopBinding, ...]:
    """Every ``for`` loop of ``command`` whose variable can be read statically.

    A name that is the variable of more than one loop, or that is assigned,
    read into, declared or otherwise changeable anywhere in the command, is
    not bound (nor is anything in a command that holds a heredoc or ``$'..'``).
    """
    if "for" not in command or any(marker in command for marker in _UNREADABLE_MARKERS):
        return ()
    tokens = _tokenise(command)
    if any(token.raw in _VARIABLE_CHANGING_WORDS for token in tokens):
        return ()
    found: list[LoopBinding] = []
    for index, token in enumerate(tokens):
        if token.raw != "for" or index + 2 >= len(tokens):
            continue
        name, keyword = tokens[index + 1], tokens[index + 2]
        if keyword.raw != "in" or not _NAME_RE.match(name.raw):
            continue
        do_index = _list_end(tokens, index + 3)
        if do_index is None or do_index == index + 3:
            continue
        done_index = _matching_done(tokens, do_index + 1)
        if done_index is None:
            continue
        found.append(
            LoopBinding(
                name=name.raw,
                raw_values=tuple(t.raw for t in tokens[index + 3 : do_index]),
                body_start=tokens[do_index].end,
                body_end=tokens[done_index].start,
            )
        )
    names = [binding.name for binding in found]
    return tuple(
        binding
        for binding in found
        if names.count(binding.name) == 1 and not _assignment_pattern(binding.name).search(command)
    )


def active_bindings(
    bindings: tuple[LoopBinding, ...], index: int
) -> dict[str, tuple[str, ...]]:
    """Variable name to raw loop words, for the loops whose body holds ``index``."""
    return {
        binding.name: binding.raw_values
        for binding in bindings
        if binding.body_start <= index < binding.body_end
    }
