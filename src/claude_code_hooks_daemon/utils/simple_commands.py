"""A Bash command read as simple commands (Plan 00499 Phase 1b).

``write_protected_paths`` must know WHICH command names a protected file, not
only whether a known destructive verb does. This module reads a command line
into the simple commands it runs and answers the questions that need:

* :func:`simple_commands` -- each command's verb, past environment
  assignments, an absolute command path (``/bin/rm``) and wrappers
  (``sudo``, ``flock``, ``chronic``, ``ionice``), with its quote-removed
  operands;
* :func:`nested_command_strings` -- the code a shell is handed
  (``bash -c '...'``, ``eval ...``, ``flock FILE -c '...'``);
* :func:`brace_variants` -- the command with its brace groups spelled out;
* :func:`unroll_for_loops` -- a ``for`` loop body written out once per word.

It is a reader for a careless agent's ordinary commands, not a shell: what it
cannot read it hands back as text for the caller to judge, never as nothing.
All of it is linear in the length of the command; the only multiplication is
bounded by named constants.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from claude_code_hooks_daemon.utils.command_evasion import (
    GIT_GLOBAL_OPTIONS_TAKING_SEPARATE_VALUE,
    strip_reserved_word_prefix,
)
from claude_code_hooks_daemon.utils.shell_expansion import (
    TooManyToEnumerateError,
    shell_word_spellings,
)
from claude_code_hooks_daemon.utils.shell_segmentation import (
    iter_shell_words,
    known_variables,
    segment_command_chain,
    shell_word_spans,
    split_unquoted,
    strip_quoted_heredoc_bodies,
    substitute_known_variables,
)

#: Where, inside one part run after another, one simple command ends and the next
#: begins: the commands of a part form a pipeline or a group.
_PIPELINE_SEPARATORS: tuple[str, ...] = ("|", "&", "(", ")", "`")
#: The separators that run one part after another (a loop's ``do`` and ``done``
#: are parts of their own).
_SEQUENCE_SEPARATORS: tuple[str, ...] = ("&&", "||", ";", "\n")

#: ``NAME=value`` in front of a command.
_ASSIGNMENT_WORD: re.Pattern[str] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
#: A redirection operator standing alone (its target is the next word).
_REDIRECT_OPERATOR: re.Pattern[str] = re.compile(r"^[0-9]*(?:<<<|<<-?|>>|>\||&>>?|>|<)$")
#: A redirection with its target glued on (``2>/dev/null``, ``<file``).
_REDIRECT_GLUED: re.Pattern[str] = re.compile(r"^[0-9]*(?:<<<|<<-?|>>|>\||&>>?|>&?|<&?)\S")

#: Interpreters whose ``-c`` argument is shell code.
SHELL_INTERPRETERS: frozenset[str] = frozenset({"bash", "sh", "dash", "zsh", "ksh", "ash", "rbash"})
#: Commands that take shell code after ``-c`` (or ``--command``) without being a shell.
_COMMAND_STRING_VERBS: frozenset[str] = frozenset({"su", "flock", "script", "runuser"})
#: Commands that run the command named by their later operands. ``chronic rm x``
#: and ``flock l rm x`` run ``rm``; since their option grammar is not modelled
#: here, the first later word that names a command the caller knows stands for it.
TRANSPARENT_WRAPPERS: frozenset[str] = frozenset(
    {
        "flock",
        "chronic",
        "ionice",
        "doas",
        "setsid",
        "stdbuf",
        "nohup",
        "nice",
        "timeout",
        "time",
        "taskset",
        "unbuffer",
        "sudo",
        "env",
        "command",
        "exec",
        "builtin",
        "runuser",
        "su",
        "chrt",
        "strace",
    }
)

#: Shell options that take the next word as their value (so it is not the code).
_SHELL_FLAGS_WITH_VALUE: frozenset[str] = frozenset(
    {"-o", "-O", "+o", "+O", "--rcfile", "--init-file"}
)
_COMMAND_LONG_FLAG = "--command"
_COMMAND_LONG_FLAG_GLUED = "--command="

#: How many words a ``for`` loop is unrolled over; past it the variable stands
#: for a wildcard, which a protected-path check reads as "anything here".
MAX_LOOP_WORDS: int = 32
_WILDCARD_WORD = "*"
_LOOP_HEADER: re.Pattern[str] = re.compile(
    r"^\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in(?:\s(.*))?$", re.DOTALL
)
_HEREDOC_OPERATOR = "<<"
_JOIN = " "


def unquote(word: str) -> str:
    """``word`` after quote and backslash removal; an expansion stays as written.

    ``"$X/y"`` is ``$X/y``: the caller judges what an unexpanded name could be.
    """
    out: list[str] = []
    index = 0
    length = len(word)
    while index < length:
        char = word[index]
        if char == "\\":
            out.append(word[index + 1 : index + 2])
            index += 2
        elif char == "'":
            end = word.find("'", index + 1)
            if end == -1:
                out.append(word[index + 1 :])
                break
            out.append(word[index + 1 : end])
            index = end + 1
        elif char == '"':
            index += 1
            while index < length and word[index] != '"':
                if word[index] == "\\" and word[index + 1 : index + 2] in {'"', "$", "`", "\\"}:
                    index += 1
                out.append(word[index])
                index += 1
            index += 1
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _basename(word: str) -> str:
    return unquote(word).rsplit("/", 1)[-1]


@dataclass(frozen=True)
class SimpleCommand:
    """One simple command: the verb it runs and the words after it.

    Attributes:
        verb: Basename of the command that runs, past assignments, an absolute
            path and wrappers.
        words: The verb's own word and the operands after it, as written.
        operands: ``words`` after the verb, quote-removed, known variables substituted.
        reread: The verb was found behind a path or a wrapper, so a scan that
            read the line as written may not have seen it.
    """

    verb: str
    words: tuple[str, ...]
    operands: tuple[str, ...]
    reread: bool
    group: int = 0

    @property
    def text(self) -> str:
        """The command from its verb on, the verb reduced to its basename."""
        return text_from(self.words, 0)

    @property
    def file_operands(self) -> tuple[str, ...]:
        """``operands`` without redirections and their targets."""
        kept: list[str] = []
        skip_next = False
        for operand, raw in zip(self.operands, self.words[1:], strict=True):
            if skip_next:
                skip_next = False
            elif _REDIRECT_OPERATOR.match(raw):
                skip_next = True
            elif not _REDIRECT_GLUED.match(raw):
                kept.append(operand)
        return tuple(kept)


def text_from(words: tuple[str, ...], start: int) -> str:
    """``words[start:]`` as a command, its first word reduced to the basename."""
    if start >= len(words):
        return ""
    return _JOIN.join([_basename(words[start]), *words[start + 1 :]])


def _words_of(segment: str) -> list[str]:
    """The words of ``segment`` up to the first whose extent a substitution hides."""
    words: list[str] = []
    for word in iter_shell_words(segment):
        if word is None:
            break
        words.append(word)
    return words


def _verb_index(words: list[str], known: frozenset[str]) -> int:
    """Where, among ``words``, the command the leading wrappers run sits."""
    chain = segment_command_chain(_JOIN.join(words))
    index = 0
    if chain:
        final = chain[-1].rsplit("/", 1)[-1]
        index = next(
            (i for i in range(len(chain) - 1, len(words)) if _basename(words[i]) == final), 0
        )
    verb = _basename(words[index])
    if verb in TRANSPARENT_WRAPPERS and verb not in known:
        later = next(
            (i for i in range(index + 1, len(words)) if _basename(words[i]) in known), None
        )
        if later is not None:
            return later
    return index


def simple_commands(command: str, *, known_verbs: frozenset[str]) -> list[SimpleCommand]:
    """Every simple command ``command`` runs.

    Args:
        command: The Bash command line.
        known_verbs: Commands the caller has a rule for. Behind a wrapper this
            module does not know the grammar of, the first later word naming one
            of them is taken to be the command the wrapper runs.

    Returns:
        The commands in order. A part that only sets variables runs nothing and
        is not returned. A quoted-delimiter heredoc body fed to a data sink is
        data, not commands; one fed to a shell is read as commands.
    """
    text = strip_quoted_heredoc_bodies(command)
    known = known_variables(command)
    found: list[SimpleCommand] = []
    segments = [
        (group, segment)
        for group, part in enumerate(split_unquoted(text, _SEQUENCE_SEPARATORS))
        for segment in split_unquoted(part, _PIPELINE_SEPARATORS)
    ]
    for group, segment in segments:
        words = _words_of(strip_reserved_word_prefix(segment))
        start = next((i for i, w in enumerate(words) if not _ASSIGNMENT_WORD.match(w)), len(words))
        if start == len(words):
            continue
        words = [_substituted(word, known) for word in words[start:]]
        index = _verb_index(words, known_verbs)
        verb = _basename(words[index])
        words = words[index:]
        found.append(
            SimpleCommand(
                verb=verb,
                words=tuple(words),
                operands=tuple(unquote(word) for word in words[1:]),
                reread=index > 0 or unquote(words[0]) != verb,
                group=group,
            )
        )
    return found


def _substituted(word: str, known: dict[str, str]) -> str:
    """``word`` with the variables the command sets spelled out, else as written."""
    if not known or "$" not in word:
        return word
    replaced = substitute_known_variables(word, known)
    return word if replaced is None else replaced


def _is_command_flag(operand: str) -> bool:
    """``-c``, a cluster holding it (``-lc``) or ``--command``."""
    if operand == _COMMAND_LONG_FLAG:
        return True
    return operand.startswith("-") and not operand.startswith("--") and "c" in operand[1:]


def _code_after_command_flag(operands: tuple[str, ...]) -> list[str]:
    """The code word after the first ``-c`` / ``--command`` among ``operands``."""
    for position, operand in enumerate(operands):
        if operand.startswith(_COMMAND_LONG_FLAG_GLUED):
            return [operand[len(_COMMAND_LONG_FLAG_GLUED) :]]
        if _is_command_flag(operand):
            return [operands[position + 1]] if position + 1 < len(operands) else []
    return []


def _shell_code(operands: tuple[str, ...]) -> list[str]:
    """The code a shell's own options lead up to (``bash -x -c CODE``); none when
    a script path or other operand comes first."""
    position = 0
    while position < len(operands):
        operand = operands[position]
        if operand in _SHELL_FLAGS_WITH_VALUE:
            position += 2
        elif operand.startswith(_COMMAND_LONG_FLAG_GLUED) or _is_command_flag(operand):
            return _code_after_command_flag(operands[position:])
        elif operand.startswith(("-", "+")) and operand != "-":
            position += 1
        else:
            return []
    return []


def nested_command_strings(command: SimpleCommand) -> list[str]:
    """The shell code ``command`` hands to a shell to run, if any.

    ``bash -c CODE``, ``sh -lc CODE``, ``eval ARGS...`` (joined by spaces, as
    ``eval`` does), and ``-c CODE`` after ``su``, ``flock`` and the like.
    """
    if command.verb == "eval":
        return [_JOIN.join(command.operands)] if command.operands else []
    if command.verb in SHELL_INTERPRETERS:
        return _shell_code(command.operands)
    if command.verb in _COMMAND_STRING_VERBS:
        return _code_after_command_flag(command.operands)
    return []


def git_subcommand(command: SimpleCommand) -> str | None:
    """The subcommand of a ``git`` command, past its global options."""
    operands = command.operands
    index = 0
    while index < len(operands):
        operand = operands[index]
        if operand in GIT_GLOBAL_OPTIONS_TAKING_SEPARATE_VALUE:
            index += 2
        elif operand.startswith("-"):
            index += 1
        else:
            return operand
    return None


# ----------------------------------------------------------------------
# Brace groups
# ----------------------------------------------------------------------

_Group = tuple[int, int, list[str]]
#: A brace holding a comma or a sequence: the shape that could be a group.
_MAYBE_GROUP: re.Pattern[str] = re.compile(r"\{[^{}]*(?:,|\.\.)")


def brace_variants(command: str) -> Iterator[str]:
    """``command`` with its brace groups spelled out.

    The first variant holds every spelling of every group as separate words, so
    a verb taking any number of operands (``rm a.{x,y}``) is seen with each.
    One more variant per spelling index puts the i-th spelling of every group in
    place, so a verb whose LAST operand is its destination (``cp s a.{x,y}``)
    is seen with each. A command with no group is its own only variant.

    Raises:
        TooManyToEnumerateError: A group has more spellings than the cap, nests
            deeper than it, or sits where the words cannot be told apart (after
            a substitution whose extent is hidden). The caller fails closed.
    """
    spans = shell_word_spans(command)
    covered = spans[-1][1] if spans else 0
    if _MAYBE_GROUP.search(command, covered):
        raise TooManyToEnumerateError("a brace group follows text whose words cannot be split")
    groups: list[_Group] = []
    for start, end in spans:
        word = command[start:end]
        if "{" not in word:
            continue
        spellings = list(dict.fromkeys(shell_word_spellings(word)))
        if spellings and spellings != [unquote(word)]:
            groups.append((start, end, spellings))
    if not groups:
        yield command
        return
    yield _respelled(command, groups, None)
    for index in range(max(len(spellings) for _start, _end, spellings in groups)):
        yield _respelled(command, groups, index)


def _respelled(command: str, groups: list[_Group], index: int | None) -> str:
    """``command`` with each group's word replaced by all its spellings
    (``index`` None) or by the one at ``index`` (the last, for a shorter group)."""
    pieces: list[str] = []
    copied_to = 0
    for start, end, spellings in groups:
        pieces.append(command[copied_to:start])
        pieces.append(
            _JOIN.join(spellings) if index is None else spellings[min(index, len(spellings) - 1)]
        )
        copied_to = end
    pieces.append(command[copied_to:])
    return "".join(pieces)


# ----------------------------------------------------------------------
# for loops
# ----------------------------------------------------------------------


def _loop_words(listing: str) -> list[str]:
    """The words a ``for`` loop runs over: at most :data:`MAX_LOOP_WORDS`, plus a
    wildcard when the list is longer or holds a substitution that cannot be read."""
    found = list(iter_shell_words(listing))
    unreadable = None in found
    words = [word for word in found if word is not None]
    if len(words) > MAX_LOOP_WORDS:
        words, unreadable = words[:MAX_LOOP_WORDS], True
    return [*words, _WILDCARD_WORD] if unreadable else words


def _unrolled(variable: str, words: list[str], body: list[str]) -> list[str]:
    reference = re.compile(rf'"?\$(?:\{{{variable}\}}|{variable}(?![A-Za-z0-9_]))"?')

    def spelled(part: str, word: str) -> str:
        return reference.sub(lambda _match: word, part)

    return [spelled(part, word) for word in words for part in body]


def unroll_for_loops(command: str) -> str:
    """``command`` with each ``for VAR in WORDS; do BODY; done`` written out per word.

    A command holding a heredoc is returned unchanged: its lines are not parts.
    A loop nested in a loop keeps its inner header as it is.
    """
    if "for" not in command or _HEREDOC_OPERATOR in command:
        return command
    parts = split_unquoted(command, _SEQUENCE_SEPARATORS)
    if not any(_LOOP_HEADER.match(part) for part in parts):
        return command
    out: list[str] = []
    variable = ""
    words: list[str] = []
    body: list[str] = []
    depth = 0
    in_loop = False
    for part in parts:
        stripped = part.strip()
        header = _LOOP_HEADER.match(stripped)
        if not in_loop:
            if header is None:
                out.append(part)
                continue
            variable, in_loop, body, depth = header.group(1), True, [], 0
            words = _loop_words(header.group(2) or "")
        elif header is not None:
            depth += 1
            body.append(part)
        elif stripped == "done" and depth > 0:
            depth -= 1
            body.append(part)
        elif stripped == "done":
            out.extend(_unrolled(variable, words, body))
            in_loop = False
        elif stripped != "do":
            body.append(strip_reserved_word_prefix(part))
    if in_loop:
        out.extend(_unrolled(variable, words, body))
    return "; ".join(part for part in out if part.strip())
