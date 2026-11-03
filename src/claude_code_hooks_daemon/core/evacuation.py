"""Evacuate then destroy: one command that copies work out and destroys it (Plan 00558).

DESIGN section 13. A command that writes a worktree's or branch's work to a
file nothing tracks (``git diff``, ``format-patch``, ``stash show -p``,
``show``, landing by redirect, ``tee`` or ``-o``) and then destroys that same
worktree or branch (``worktree remove``, ``branch -d/-D``, ``update-ref -d``,
``rm -r`` of the worktree) has turned reviewed history into an unreviewed
patch file. The right move is a commit or a push on the lane's branch.

What cannot be placed is judged as matching: the check fails closed.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_commit_parsing import (
    GitInvocation,
    SimpleCommand,
    simple_commands,
)
from claude_code_hooks_daemon.utils.git_invocation_directory import (
    invocation_directory,
    placed_moves,
    placement_problem,
)
from claude_code_hooks_daemon.utils.git_repo import HEADS_PREFIX, run_git

#: Options that make ``diff``/``show`` print a summary, not the work itself.
_SUMMARY_ONLY: Final[frozenset[str]] = frozenset(
    {
        "--stat",
        "--shortstat",
        "--numstat",
        "--name-only",
        "--name-status",
        "--summary",
        "--dirstat",
        "--raw",
        "--no-patch",
        "-s",
    }
)
_PATCH_OPTIONS: Final[frozenset[str]] = frozenset({"-p", "--patch", "-u"})
_OUTPUT_DIRECTORY_OPTIONS: Final[frozenset[str]] = frozenset({"-o", "--output-directory"})
_RANGE_SEPARATOR: Final[re.Pattern[str]] = re.compile(r"\.\.\.?")
_REVISION_SUFFIX: Final[re.Pattern[str]] = re.compile(r"[~^].*$")
_DEVICE_PREFIX: Final[str] = "/dev/"


@dataclass(frozen=True)
class EvacuationMatch:
    """An evacuation and the destruction of the same work, both in one command."""

    evacuation: str
    landing: str
    destruction: str


@dataclass(frozen=True)
class _Evacuation:
    text: str
    landing: str
    #: The worktree the work comes from; None when it cannot be placed.
    toplevel: Path | None
    branches: frozenset[str]


@dataclass(frozen=True)
class _Destruction:
    text: str
    #: The directory removed; None for a branch delete or an unplaceable path.
    path: Path | None
    branches: frozenset[str]
    placed: bool


def _git_line(directory: Path, *args: str) -> str | None:
    result = run_git(directory, *args, timeout=Timeout.GIT_CONTEXT)
    line = result.stdout.strip()
    return line if result.returncode == 0 and line else None


def _branch_of(directory: Path) -> frozenset[str]:
    branch = _git_line(directory, "symbolic-ref", "--short", "-q", "HEAD")
    return frozenset({branch}) if branch else frozenset()


def _shell_directory(step: SimpleCommand, cwd: Path) -> Path | None:
    """Where the shell is when ``step`` runs, or None when a ``cd`` cannot be placed."""
    steps, problem = placed_moves(step.directory, cwd)
    if problem is not None:
        return None
    directory = cwd
    for move in steps:
        if move is None:
            return None
        directory = directory / move
    return directory


def _git_directory(run: GitInvocation, cwd: Path) -> Path | None:
    if placement_problem(run, cwd) is not None:
        return None
    return invocation_directory(run, cwd)


def _operands(arguments: tuple[str, ...]) -> list[str]:
    return [argument for argument in arguments if not argument.startswith("-")]


def _evacuates(run: GitInvocation) -> bool:
    """Whether ``run`` prints or writes the work itself, not a summary of it."""
    arguments = set(run.arguments)
    if run.subcommand in {"diff", "show"}:
        return not arguments & _SUMMARY_ONLY
    if run.subcommand == "stash":
        return run.arguments[:1] == ("show",) and bool(arguments & _PATCH_OPTIONS)
    return run.subcommand == "format-patch"


def _output_directory(arguments: tuple[str, ...]) -> str | None:
    for index, argument in enumerate(arguments):
        if argument in _OUTPUT_DIRECTORY_OPTIONS and index + 1 < len(arguments):
            return arguments[index + 1]
        if argument.startswith("--output-directory="):
            return argument.split("=", 1)[1]
    return None


def _raw_landings(steps: list[SimpleCommand], index: int) -> list[str]:
    """What ``steps[index]`` writes to: its file redirects, a piped ``tee``, a ``-o``."""
    step = steps[index]
    landings = [
        target
        for operator, target in step.redirects
        if ">" in operator and not target.startswith(("&", _DEVICE_PREFIX))
    ]
    if index + 1 < len(steps):
        following = steps[index + 1]
        if following.operator == "|" and following.words[:1] == ("tee",):
            landings.extend(_operands(following.words[1:]))
    if step.git is not None and step.git.subcommand == "format-patch":
        directory = _output_directory(step.git.arguments)
        if directory is not None:
            landings.append(directory)
    return landings


def _tracked(landing: Path) -> bool:
    """Whether ``landing`` is a file (or a directory of files) some repository tracks."""
    result = run_git(
        landing.parent,
        "ls-files",
        "--error-unmatch",
        "--",
        landing.name,
        timeout=Timeout.GIT_CONTEXT,
    )
    return result.returncode == 0


def _named_branches(arguments: tuple[str, ...]) -> set[str]:
    names: set[str] = set()
    for operand in _operands(arguments):
        for part in _RANGE_SEPARATOR.split(operand):
            name = _REVISION_SUFFIX.sub("", part)
            if name:
                names.add(name)
    return names


def _evacuation(steps: list[SimpleCommand], index: int, cwd: Path) -> _Evacuation | None:
    step = steps[index]
    run = step.git
    if run is None or not _evacuates(run):
        return None
    base = _shell_directory(step, cwd)
    landing: str | None = None
    for raw in _raw_landings(steps, index):
        if Path(raw).is_absolute():
            placed: Path | None = Path(raw)
        else:
            placed = base / raw if base is not None else None
        if placed is None or not _tracked(placed.resolve()):
            landing = str(placed) if placed is not None else raw
            break
    if landing is None:
        return None
    directory = _git_directory(run, cwd)
    toplevel_line = _git_line(directory, "rev-parse", "--show-toplevel") if directory else None
    toplevel = Path(toplevel_line).resolve() if toplevel_line else None
    branches = set(_named_branches(run.arguments))
    if toplevel is not None:
        branches |= _branch_of(toplevel)
    return _Evacuation(
        text=" ".join(("git", run.subcommand, *run.arguments)),
        landing=landing,
        toplevel=toplevel,
        branches=frozenset(branches),
    )


def _deleted_branch_names(run: GitInvocation) -> frozenset[str]:
    if run.subcommand == "branch":
        deleting = any(
            argument == "--delete"
            or (
                argument.startswith("-")
                and not argument.startswith("--")
                and bool(set(argument[1:]) & {"d", "D"})
            )
            for argument in run.arguments
        )
        return frozenset(_operands(run.arguments)) if deleting else frozenset()
    if run.subcommand == "update-ref" and "-d" in run.arguments:
        return frozenset(
            operand.removeprefix(HEADS_PREFIX)
            for operand in _operands(run.arguments)[:1]
            if operand.startswith(HEADS_PREFIX)
        )
    return frozenset()


def _recursive_rm(step: SimpleCommand) -> bool:
    if step.words[:1] != ("rm",):
        return False
    return any(
        option == "--recursive"
        or (
            option.startswith("-")
            and not option.startswith("--")
            and bool(set(option[1:]) & {"r", "R"})
        )
        for option in step.words[1:]
    )


def _destroys(step: SimpleCommand) -> bool:
    """Whether ``step`` has the shape of a destruction, read without running git."""
    run = step.git
    if run is None:
        return _recursive_rm(step)
    if run.subcommand == "worktree":
        return run.arguments[:1] == ("remove",)
    return bool(_deleted_branch_names(run))


def _removed_path(base: Path | None, raw: str) -> Path | None:
    if Path(raw).expanduser().is_absolute():
        return Path(raw).expanduser().resolve()
    return (base / raw).resolve() if base is not None else None


def _destructions(step: SimpleCommand, cwd: Path) -> list[_Destruction]:
    text = " ".join(step.words)
    run = step.git
    if run is not None:
        if run.subcommand == "worktree" and run.arguments[:1] == ("remove",):
            directory = _git_directory(run, cwd)
            removed = [_removed_path(directory, raw) for raw in _operands(run.arguments[1:])]
            return [
                _Destruction(
                    text=text,
                    path=path,
                    branches=_branch_of(path) if path is not None else frozenset(),
                    placed=path is not None,
                )
                for path in removed
            ]
        names = _deleted_branch_names(run)
        if names:
            return [_Destruction(text=text, path=None, branches=names, placed=True)]
        return []
    if not _recursive_rm(step):
        return []
    base = _shell_directory(step, cwd)
    return [
        _Destruction(text=text, path=path, branches=frozenset(), placed=path is not None)
        for path in (_removed_path(base, raw) for raw in _operands(step.words[1:]))
    ]


def _same_work(evacuation: _Evacuation, destruction: _Destruction) -> bool:
    if evacuation.toplevel is None or not destruction.placed:
        return True
    if evacuation.branches & destruction.branches:
        return True
    path = destruction.path
    return path is not None and evacuation.toplevel.is_relative_to(path)


def evacuate_then_destroy(command: str, cwd: Path) -> EvacuationMatch | None:
    """The first evacuation in ``command`` that a later step of it destroys the source of.

    Args:
        command: The Bash command line.
        cwd: The directory it starts in.

    Returns:
        The match, or None when the command does not have the shape.
    """
    steps = simple_commands(command)
    # Only a command carrying both shapes is worth a git call.
    if not any(step.git is not None and _evacuates(step.git) for step in steps):
        return None
    if not any(_destroys(step) for step in steps):
        return None
    evacuations: list[_Evacuation] = []
    for index, step in enumerate(steps):
        for destruction in _destructions(step, cwd):
            for evacuation in evacuations:
                if _same_work(evacuation, destruction):
                    return EvacuationMatch(
                        evacuation=evacuation.text,
                        landing=evacuation.landing,
                        destruction=destruction.text,
                    )
        found = _evacuation(steps, index, cwd)
        if found is not None:
            evacuations.append(found)
    return None
