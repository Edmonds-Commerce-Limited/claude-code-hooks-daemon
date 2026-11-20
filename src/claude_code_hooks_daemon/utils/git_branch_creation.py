"""Which branch a git command would create, read from its argv.

The single parser the branch-creation guard (Plan 00558) and the creator record
share, so the two can never disagree on what counts as a creation. It reads the
command only: a name that already exists in ``refs/heads`` is a reset or a
checkout, not a creation, and that is decided by the caller against the
repository (``-B``, ``-C``, ``branch -f`` and the bare ``worktree add`` DWIM form
all collapse to that one rule).

A name built by shell expansion cannot be read statically and is skipped, so the
command is allowed: guessing a name would deny on text the shell never runs.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

from claude_code_hooks_daemon.utils.git_commit_parsing import (
    GitInvocation,
    SimpleCommand,
    is_assignment_word,
    is_shell_resolved,
    simple_commands,
)
from claude_code_hooks_daemon.utils.shell_segmentation import peel_command_wrappers

ROUTE_SWITCH: Final[str] = "switch"
ROUTE_CHECKOUT: Final[str] = "checkout"
ROUTE_BRANCH: Final[str] = "branch"
ROUTE_WORKTREE: Final[str] = "worktree"
#: ``scripts/setup_worktree.sh <name>``, which runs ``git worktree add -b`` itself.
ROUTE_SETUP_WORKTREE: Final[str] = "setup-worktree"

_SETUP_SCRIPT_NAME: Final[str] = "setup_worktree.sh"
_SETUP_SCRIPT_TAIL: Final[tuple[str, ...]] = ("scripts", _SETUP_SCRIPT_NAME)
_SCRIPTS_DIRECTORY: Final[str] = "scripts"
_PARENT: Final[str] = ".."
_SHELL_INTERPRETERS: Final[frozenset[str]] = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_OPTION_END: Final[str] = "--"
#: Interpreter short-option letters that stop the script running: ``-n`` only parses
#: it and ``-c`` takes the next word as the program text.
_NON_RUNNING_LETTERS: Final[frozenset[str]] = frozenset({"n", "c"})
#: Short-option letters (``-o``, ``-O``, ``+o``, ``+O``) and long options that take the next word.
_VALUE_LETTERS: Final[frozenset[str]] = frozenset({"o", "O"})
_VALUE_LONG_OPTIONS: Final[frozenset[str]] = frozenset({"--rcfile", "--init-file"})
_NON_RUNNING_LONG_OPTIONS: Final[frozenset[str]] = frozenset({"--noexec"})

_SWITCH_CREATE: Final[frozenset[str]] = frozenset(
    {"-c", "-C", "--create", "--force-create", "--orphan"}
)
_SWITCH_SHORT: Final[tuple[str, ...]] = ("-c", "-C")
_CHECKOUT_CREATE: Final[frozenset[str]] = frozenset({"-b", "-B", "--orphan"})
_CHECKOUT_SHORT: Final[tuple[str, ...]] = ("-b", "-B")
_WORKTREE_CREATE: Final[frozenset[str]] = frozenset({"-b", "-B"})
#: ``git worktree add`` options that consume the next word as their value.
_WORKTREE_VALUED: Final[frozenset[str]] = frozenset({"-b", "-B", "--reason"})
_WORKTREE_DETACH: Final[frozenset[str]] = frozenset({"-d", "--detach"})
_BRANCH_CREATE_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        "-f",
        "--force",
        "-t",
        "--track",
        "--no-track",
        "-q",
        "--quiet",
        "--create-reflog",
        "--recurse-submodules",
    }
)
_BRANCH_MAX_POSITIONALS: Final[int] = 2


@dataclass(frozen=True)
class Creation:
    """One branch a git run would create."""

    name: str
    route: str
    dwim: bool
    invocation: GitInvocation


def _option_value(
    arguments: tuple[str, ...], flags: frozenset[str], short: tuple[str, ...]
) -> str | None:
    """The value of the first creating flag: ``-c x``, ``--create=x`` or ``-cx``."""
    for index, word in enumerate(arguments):
        if word == "--":
            return None
        if word in flags:
            return arguments[index + 1] if index + 1 < len(arguments) else None
        if word.startswith("--") and word.split("=", 1)[0] in flags and "=" in word:
            return word.split("=", 1)[1]
        for flag in short:
            if word.startswith(flag) and len(word) > len(flag):
                return word[len(flag) :]
    return None


def _branch_name(arguments: tuple[str, ...]) -> str | None:
    """The created name of a ``git branch <n> [start]`` run, else ``None``."""
    positionals: list[str] = []
    for word in arguments:
        if word.startswith("-"):
            if word not in _BRANCH_CREATE_OPTIONS and not word.startswith("--track="):
                return None
            continue
        positionals.append(word)
    if not 1 <= len(positionals) <= _BRANCH_MAX_POSITIONALS:
        return None
    return positionals[0]


def _worktree_name(arguments: tuple[str, ...]) -> tuple[str, bool] | None:
    """The created name of a ``git worktree add`` run and whether it is DWIM."""
    if not arguments or arguments[0] != "add":
        return None
    rest = arguments[1:]
    named = _option_value(rest, _WORKTREE_CREATE, ())
    if named is not None:
        return named, False
    if any(word in _WORKTREE_DETACH for word in rest):
        return None
    positionals = [word for word in rest if not word.startswith("-")]
    if len(positionals) != 1:
        return None
    return PurePosixPath(positionals[0]).name, True


def _creation(run: GitInvocation) -> Creation | None:
    """The branch ``run`` would create, or ``None``."""
    found: tuple[str, bool] | None = None
    if run.subcommand == ROUTE_SWITCH:
        value = _option_value(run.arguments, _SWITCH_CREATE, _SWITCH_SHORT)
        found = (value, False) if value is not None else None
    elif run.subcommand == ROUTE_CHECKOUT:
        value = _option_value(run.arguments, _CHECKOUT_CREATE, _CHECKOUT_SHORT)
        found = (value, False) if value is not None else None
    elif run.subcommand == ROUTE_BRANCH:
        value = _branch_name(run.arguments)
        found = (value, False) if value is not None else None
    elif run.subcommand == ROUTE_WORKTREE:
        found = _worktree_name(run.arguments)
    if found is None:
        return None
    name, dwim = found
    if not name or name.startswith("-") or is_shell_resolved(name):
        return None
    return Creation(name=name, route=run.subcommand, dwim=dwim, invocation=run)


def _is_setup_script(word: str, directory: tuple[str | None, ...]) -> bool:
    """True when ``word`` is the repository's ``setup_worktree.sh``.

    Either a path ending ``scripts/setup_worktree.sh``, or the bare script name
    while the ``cd`` chain has ended in a ``scripts`` directory.
    """
    parts = PurePosixPath(word).parts
    if parts[-2:] == _SETUP_SCRIPT_TAIL:
        return True
    last = directory[-1] if directory else None
    return (
        parts == (_SETUP_SCRIPT_NAME,)
        and last is not None
        and PurePosixPath(last).name == _SCRIPTS_DIRECTORY
    )


def _interpreter_script(rest: Sequence[str]) -> int | None:
    """Index in ``rest`` of the script a shell interpreter runs, or ``None``.

    ``rest`` starts after the interpreter. Short clusters (``-xe``), long
    options (``--norc``) and the value taken by ``-o``/``-O``/``+o``/``--rcfile``
    are told apart, so only ``-n``, ``-c`` and ``--noexec`` mean the script does
    not run.
    """
    index = 0
    while index < len(rest):
        word = rest[index]
        if word == _OPTION_END:
            return index + 1 if index + 1 < len(rest) else None
        if word.startswith("--"):
            name = word.split("=", 1)[0]
            if name in _NON_RUNNING_LONG_OPTIONS:
                return None
            index += 2 if name in _VALUE_LONG_OPTIONS and "=" not in word else 1
        elif word.startswith(("-", "+")) and len(word) > 1:
            letters = word[1:]
            if word[0] == "-" and _NON_RUNNING_LETTERS & set(letters):
                return None
            index += 2 if letters[-1] in _VALUE_LETTERS else 1
        else:
            return index
    return None


def _script_and_arguments(
    step: SimpleCommand,
) -> tuple[str, tuple[str, ...], tuple[str, ...]] | None:
    """The setup script a simple command runs, its arguments and its leading assignments.

    Wrappers (``timeout``, ``env``, ``nohup``, ``sudo``...) are peeled with the
    grammar the git path uses. The script is then the command itself or the
    script word of a shell interpreter. ``cat``, ``echo`` and ``grep`` naming
    the path run nothing, and neither does ``bash -n``.
    """
    words = step.words
    assignments = tuple(itertools.takewhile(is_assignment_word, words))
    rest = words[len(assignments) :]
    _, start = peel_command_wrappers(rest)
    rest = rest[start:]
    wrapped = tuple(itertools.takewhile(is_assignment_word, rest))
    assignments += wrapped
    rest = rest[len(wrapped) :]
    if not rest:
        return None
    if _is_setup_script(rest[0], step.directory):
        return rest[0], tuple(rest[1:]), assignments
    if PurePosixPath(rest[0]).name not in _SHELL_INTERPRETERS:
        return None
    offset = _interpreter_script(rest[1:])
    if offset is None:
        return None
    script = rest[1 + offset]
    if not _is_setup_script(script, step.directory):
        return None
    return script, tuple(rest[2 + offset :]), assignments


def _script_root(script: str) -> str:
    """The repository root the script resolves, relative to the directory it is named from."""
    path = PurePosixPath(script)
    return _PARENT if path.parts == (_SETUP_SCRIPT_NAME,) else str(path.parent.parent)


def _setup_script_creation(step: SimpleCommand) -> Creation | None:
    """The branch a ``scripts/setup_worktree.sh <name>`` run creates, or ``None``.

    The script resolves its repository from its own location, so the run acts in
    the repository above the ``scripts`` directory rather than in the working
    directory.
    """
    found = _script_and_arguments(step)
    if found is None:
        return None
    script, arguments, assignments = found
    name = arguments[0] if arguments else ""
    if not name or name.startswith("-") or is_shell_resolved(name):
        return None
    run = GitInvocation(
        subcommand=ROUTE_SETUP_WORKTREE,
        global_options=(),
        arguments=arguments,
        assignments=assignments,
        directory=(*step.directory, _script_root(script)),
        moves_certain=step.moves_certain,
        position=step.position,
    )
    return Creation(name=name, route=ROUTE_SETUP_WORKTREE, dwim=False, invocation=run)


def created_branches(command: str) -> list[Creation]:
    """Every branch ``command`` would create, in the order its runs appear.

    A run is a git command or a ``scripts/setup_worktree.sh`` invocation.
    """
    creations: list[Creation] = []
    for step in simple_commands(command):
        found = _creation(step.git) if step.git is not None else _setup_script_creation(step)
        if found is not None:
            creations.append(found)
    return creations


def worktree_add_path(arguments: tuple[str, ...]) -> str | None:
    """The directory a ``git worktree add`` run creates, else ``None``.

    ``arguments`` are the words after ``worktree``. The path is the first
    positional once option values (``-b <name>``, ``--reason <text>``) are
    skipped; everything after ``--`` is positional.
    """
    if not arguments or arguments[0] != "add":
        return None
    skip = False
    after_separator = False
    for word in arguments[1:]:
        if skip:
            skip = False
        elif after_separator or not word.startswith("-"):
            return word
        elif word == "--":
            after_separator = True
        elif word in _WORKTREE_VALUED:
            skip = True
    return None
