"""Reading the expression of a ``find`` command.

A leaf module: it imports nothing from the daemon, so the secret-file matcher
and the search-reach reader (which sit on opposite sides of an import cycle) can
both use the one reader instead of each keeping a copy.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

_FIND: Final[str] = "find"
#: The `find` actions that run another command on what they find.
FIND_EXEC_ACTIONS: Final[frozenset[str]] = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
#: The words that end such a command (`;` as the shell hands it over, or `+`).
FIND_EXEC_TERMINATORS: Final[frozenset[str]] = frozenset({";", "+"})
#: The `find` tests whose operand is a regular expression matched against the
#: whole path, never a path to open.
FIND_REGEX_TESTS: Final[frozenset[str]] = frozenset({"-regex", "-iregex"})
#: The `find` action that removes what it finds.
FIND_DELETE_ACTION: Final[str] = "-delete"


def find_exec_end(
    words: Sequence[str],
    start: int,
    terminators: frozenset[str] = FIND_EXEC_TERMINATORS,
) -> int | None:
    """Index of the terminator that ends the ``find`` action command starting at ``start``.

    ``start`` is the index of the first word after the ``-exec``-style action.
    None when no word from there on is a terminator (the command runs to the end).
    """
    return next((i for i in range(start, len(words)) if words[i] in terminators), None)


def find_regex_operand_indexes(words: Sequence[str]) -> list[int]:
    """Indexes of the regular-expression operands of a ``find`` command.

    ``words`` is the whole command, ``find`` first. Empty when it is not a
    ``find`` command, and also when it acts on what it finds: it runs another
    command (:data:`FIND_EXEC_ACTIONS`) or removes the files
    (:data:`FIND_DELETE_ACTION`). The expression then decides which files are
    touched, so its text is not inert.
    """
    if not words or words[0].rsplit("/", 1)[-1] != _FIND:
        return []
    if any(word in FIND_EXEC_ACTIONS or word == FIND_DELETE_ACTION for word in words):
        return []
    return [index + 1 for index, word in enumerate(words[:-1]) if word in FIND_REGEX_TESTS]
