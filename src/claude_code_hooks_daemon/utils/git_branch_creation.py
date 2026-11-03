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

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

from claude_code_hooks_daemon.utils.git_commit_parsing import (
    GitInvocation,
    git_invocations,
    is_shell_resolved,
)

ROUTE_SWITCH: Final[str] = "switch"
ROUTE_CHECKOUT: Final[str] = "checkout"
ROUTE_BRANCH: Final[str] = "branch"
ROUTE_WORKTREE: Final[str] = "worktree"

_SWITCH_CREATE: Final[frozenset[str]] = frozenset(
    {"-c", "-C", "--create", "--force-create", "--orphan"}
)
_SWITCH_SHORT: Final[tuple[str, ...]] = ("-c", "-C")
_CHECKOUT_CREATE: Final[frozenset[str]] = frozenset({"-b", "-B", "--orphan"})
_CHECKOUT_SHORT: Final[tuple[str, ...]] = ("-b", "-B")
_WORKTREE_CREATE: Final[frozenset[str]] = frozenset({"-b", "-B"})
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


def created_branches(command: str) -> list[Creation]:
    """Every branch ``command`` would create, in the order its git runs appear."""
    return [c for c in (_creation(run) for run in git_invocations(command)) if c is not None]
