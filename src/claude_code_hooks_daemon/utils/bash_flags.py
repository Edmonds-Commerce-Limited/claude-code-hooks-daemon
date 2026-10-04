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
from claude_code_hooks_daemon.utils.heredoc_operators import scan_heredocs
from claude_code_hooks_daemon.utils.shell_segmentation import (
    iter_shell_words,
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

#: Reserved words in front of a ``set`` that still run it unconditionally in
#: the current shell (Plan 00422 N25): ``{ set -e; ...; }`` sets errexit for
#: everything after it. ``then``/``do``/``else`` are absent on purpose, because
#: a ``set`` behind them runs only if a condition holds, and crediting it would
#: stand the safety checks down for a command that may never have run it. ``(``
#: is absent too: a subshell's ``set`` ends with the subshell.
_UNCONDITIONAL_PREFIX: Final = r"(?:(?:time\s+-p|time|!|\{)\s+)*"

#: A ``set`` builtin at the head of a statement, capturing its arguments.
_SET_STATEMENT: Final[re.Pattern[str]] = re.compile(
    rf"^\s*{_UNCONDITIONAL_PREFIX}set\s+(?P<args>\S.*)$"
)

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

#: End-of-options marker: everything after a bare ``--`` is a positional
#: operand (``set -- -e foo`` sets ``$1=-e``), never a flag.
_END_OF_OPTIONS: Final = "--"


def _drop_heredoc_bodies(command: str) -> str:
    """``command`` with each heredoc's body and terminator line removed.

    The opener line stays, so the heredoc counts once; the line break that
    ended it is kept and leaves an empty statement that the caller drops.
    """
    pieces: list[str] = []
    copied_to = 0
    for heredoc in sorted(scan_heredocs(command).heredocs, key=lambda item: item.body_start):
        pieces.append(command[copied_to : heredoc.body_start])
        copied_to = heredoc.closer_end
    pieces.append(command[copied_to:])
    return "".join(pieces)


def split_statements(command: str, *, heredoc_bodies_executable: bool = False) -> list[str]:
    """Split ``command`` into stripped, non-empty sequenced statements.

    Line continuations are joined first. By default every heredoc (the opener
    line, its body and its terminator) is ONE statement: the body is input to
    the receiving command, never a sequence of outer-shell statements, so a
    ``;`` or newline inside it never manufactures a boundary, whether the
    delimiter is quoted or not. An interpreter's body (``bash <<'EOF'``) is
    likewise one outer statement, because the outer shell's ``set -e`` does
    not govern the inner shell's lines.

    Pass ``heredoc_bodies_executable=True`` to keep the old reading for a
    caller that must SEE a command inside a body that is executed: sink-fed
    quoted bodies are still blanked, but any other body stays as its lines.
    """
    normalised = normalise_line_continuations(command)
    if heredoc_bodies_executable:
        normalised = strip_quoted_heredoc_bodies(normalised)
    else:
        normalised = _drop_heredoc_bodies(normalised)
    return [
        statement.strip()
        for statement in split_unquoted(normalised, STATEMENT_SEPARATORS)
        if statement.strip()
    ]


#: Compound-command openers and the word that closes each. `for`/`select` are
#: followed by a word list, `case` by a subject, so neither starts a command.
_CLOSER_FOR_OPENER: Final[dict[str, str]] = {
    "{": "}",
    "if": "fi",
    "while": "done",
    "until": "done",
    "for": "done",
    "select": "done",
    "case": "esac",
}
_CLOSERS: Final[frozenset[str]] = frozenset(_CLOSER_FOR_OPENER.values())

#: Words that continue the construct a `;` or newline just ended: they run
#: inside it, so the break before them is grammar, not sequencing.
_CONTINUATIONS: Final[frozenset[str]] = frozenset({"do", "then", "else", "elif"})

#: A bare opener keyword: the statement after it is the body it introduces.
_BARE_OPENERS: Final[frozenset[str]] = frozenset({"do", "then", "else", "{"})

#: Words after which the next word is again a command.
_COMMAND_POSITION_AFTER: Final[frozenset[str]] = frozenset(
    {"&&", "||", "|", "|&", "!", "{", "then", "do", "else", "elif", "if", "while", "until", "time"}
)

#: `a)`, `a|b)`, `*)` at the start of a case clause.
_CASE_CLAUSE: Final[re.Pattern[str]] = re.compile(r"^\(?[^\s()]+\)(?:\s|$)")


def _opened_constructs(words: list[str]) -> list[str]:
    """Closing words for each compound command opened by ``words``, in order."""
    opened: list[str] = []
    command_position = True
    for word in words:
        if command_position and word in _CLOSER_FOR_OPENER:
            opened.append(_CLOSER_FOR_OPENER[word])
            command_position = word in _COMMAND_POSITION_AFTER
        else:
            command_position = word in _COMMAND_POSITION_AFTER
    return opened


def sequenced_statements(command: str) -> list[str]:
    """The statements of ``command`` that are genuinely sequenced (N339).

    :func:`split_statements` cuts at every ``;`` and newline, but inside
    ``{ …; }``, ``for … ; do …; done``, ``if …; then …; fi`` and ``case``
    some of those are the construct's own grammar. Counting them reports a
    fully ``&&``/``||``-gated group as ungated sequencing. This folds each
    grammar break into the statement it belongs to: the closer (``}``,
    ``done``, ``fi``, ``esac``), the continuation (``do``, ``then``,
    ``else``, ``elif``), the first statement after a bare opener, and a case
    clause start. A real ``a; b`` INSIDE a body stays two statements.

    Fails closed: anything it cannot place with certainty (a word hidden by
    a substitution, a closer that matches no open construct, a construct
    left open) returns the plain :func:`split_statements` result, so the
    answer can only err toward reporting more sequencing, never less.
    """
    statements = split_statements(command)
    stack: list[str] = []
    counted: list[str] = []
    after_bare_opener = False
    for statement in statements:
        plain: list[str] = []
        for word in iter_shell_words(statement):
            if word is None:
                return statements
            plain.append(word)
        first = plain[0] if plain else ""
        if first in _CLOSERS:
            if not stack or stack[-1] != first:
                return statements
            stack.pop()
            after_bare_opener = False
            continue
        if first in _CONTINUATIONS and not stack:
            return statements
        in_case = bool(stack) and stack[-1] == "esac"
        is_clause = in_case and _CASE_CLAUSE.match(statement) is not None
        if not (first in _CONTINUATIONS or after_bare_opener or is_clause):
            counted.append(statement)
        stack.extend(_opened_constructs(plain))
        after_bare_opener = len(plain) == 1 and plain[0] in _BARE_OPENERS
    return counted if not stack else statements


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
            if token == _END_OF_OPTIONS:
                # `set -- -e foo` assigns positional parameters; anything
                # after `--` is an operand, never a flag. Reading on would
                # report errexit that was never enabled — and stand down
                # verification_result_gate on a genuinely ungated command.
                break
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
