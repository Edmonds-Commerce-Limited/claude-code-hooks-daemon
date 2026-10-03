"""Journal entries a Bash command writes and stages before its own ``git commit``.

Ledger 00474 N317: ``mkplan.bash --journal 470 ... && git add <plan> && git commit``
records the day-file, but the commit gate runs BEFORE the command, so the
day-file does not exist yet and the staging simulation cannot see it.
:func:`command_journal_plans` reads the command itself: a plan counts when a
simple command appends a journal entry to it through the deployed
``mkplan.bash``, every command from there to the last ``git commit`` is joined
by ``&&`` (a failing ``mkplan.bash`` then stops the commit), a ``git add`` that
covers the plan's journal directory runs in between, and the commit does not
name paths that leave the journal out.

Directories are tracked by ``simple_commands`` and the ``git add`` runs come
from the commit reading's ``stagings``, so a ``cd`` or ``git -C`` is honoured as
it is for the staging simulation. Only a plan folder directly under the plan
directory is found: one already moved into an archive subdirectory is never
exempted, which fails safe (the advisory fires).
"""

import os
from collections.abc import Sequence
from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.common import plan_number_for_folder
from claude_code_hooks_daemon.plan_qa.model import MKPLAN_SCRIPT_NAME
from claude_code_hooks_daemon.utils.git_commit_parsing import (
    CommitReading,
    SimpleCommand,
    StagingRun,
    is_shell_resolved,
    simple_commands,
)
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to

_JOURNAL_FLAG = "--journal"
_COMMIT = "commit"
_AND = "&&"
_END_OF_OPTIONS = "--"
_INTERPRETERS = frozenset({"bash", "sh"})
_ADD_ALL_FLAGS = frozenset({"-A", "--all"})
#: ``git add`` options after which nothing new is staged: tracked files only,
#: a dry run, or an interactive/patch selection.
_NON_STAGING_FLAGS = frozenset(
    {"-u", "--update", "-n", "--dry-run", "-p", "--patch", "-i", "--interactive"}
)


def _resolve(start: Path, moves: Sequence[str | None], optional_moves: int) -> Path | None:
    """The directory a run ends in after ``moves`` from ``start``, or None when not statable."""
    if optional_moves or any(move is None or is_shell_resolved(move) for move in moves):
        return None
    where = start
    for move in moves:
        if move is not None:
            where = Path(os.path.normpath(where / move))
    return where


def _journal_plan_number(step: SimpleCommand, script: Path, start: Path) -> int | None:
    """The plan ``step`` appends a journal entry to through ``script``, else None."""
    words = step.words
    position = 0
    while position < len(words) and "=" in words[position] and not words[position].startswith("-"):
        position += 1
    if position < len(words) and words[position] in _INTERPRETERS:
        position += 1
    if len(words) < position + 3 or words[position + 1] != _JOURNAL_FLAG:
        return None
    named, number = words[position], words[position + 2]
    # A bare name is looked up on PATH, never in the working directory.
    if "/" not in named or is_shell_resolved(named) or not number.isdigit():
        return None
    where = _resolve(start, step.directory, 0 if step.moves_certain else len(step.directory))
    if where is None or Path(os.path.normpath(where / named)) != script:
        return None
    return int(number)


def _covers(target: Path, journal_dir: Path) -> bool:
    return path_is_relative_to(journal_dir, target)


def _names(where: Path, pathspecs: Sequence[str], journal_dir: Path) -> bool:
    """Whether any literal pathspec, taken from ``where``, is ``journal_dir`` or above it."""
    return any(
        not is_shell_resolved(pathspec)
        and _covers(Path(os.path.normpath(where / pathspec)), journal_dir)
        for pathspec in pathspecs
    )


def _add_covers(run: StagingRun, journal_dir: Path, start: Path) -> bool:
    """Whether the ``git add`` ``run`` stages ``journal_dir``'s new files."""
    where = _resolve(start, run.moves, run.optional_moves)
    if where is None:
        return False
    pathspecs: list[str] = []
    add_all = False
    options_ended = False
    for word in run.arguments:
        if not options_ended and word == _END_OF_OPTIONS:
            options_ended = True
        elif not options_ended and word.startswith("-"):
            if word in _NON_STAGING_FLAGS:
                return False
            add_all = add_all or word in _ADD_ALL_FLAGS
        else:
            pathspecs.append(word)
    if not pathspecs:
        return add_all
    return _names(where, pathspecs, journal_dir)


def _commits_journal(reading: CommitReading, journal_dir: Path, start: Path) -> bool:
    """Whether every commit that names paths (without ``-i``) names the journal directory."""
    for run in reading.runs:
        if not run.form.pathspecs or run.form.include:
            continue
        where = _resolve(start, run.moves, run.optional_moves)
        if where is None or not _names(where, run.form.pathspecs, journal_dir):
            return False
    return True


def _plan_folders(plan_dir: Path) -> dict[int, Path]:
    """The plan folders directly under ``plan_dir``, by plan number."""
    folders: dict[int, Path] = {}
    if plan_dir.is_dir():
        for entry in sorted(plan_dir.iterdir()):
            number = plan_number_for_folder(entry.name) if entry.is_dir() else None
            if number is not None:
                folders.setdefault(number, entry)
    return folders


def command_journal_plans(
    command: str,
    reading: CommitReading,
    cwd: str | Path | None,
    project_root: Path,
    plan_dir_rel: str,
    journal_dir_name: str,
) -> frozenset[int]:
    """Plan numbers ``command`` journals and stages before its last ``git commit``."""
    steps = simple_commands(command)
    last_commit = max(
        (step.position for step in steps if step.git and step.git.subcommand == _COMMIT),
        default=-1,
    )
    if last_commit < 0 or any(run.form.pathspec_from_file for run in reading.runs):
        return frozenset()
    start = Path(cwd) if cwd else project_root
    plan_dir = project_root / plan_dir_rel
    script = Path(os.path.normpath(plan_dir / MKPLAN_SCRIPT_NAME))
    journalled: dict[int, int] = {}
    for step in steps[:last_commit]:
        number = _journal_plan_number(step, script, start)
        chained = all(
            later.operator == _AND for later in steps[step.position + 1 : last_commit + 1]
        )
        if number is not None and chained:
            journalled.setdefault(number, step.position)
    if not journalled:
        return frozenset()
    folders = _plan_folders(plan_dir)
    covered: set[int] = set()
    for number, written_at in journalled.items():
        folder = folders.get(number)
        if folder is None:
            continue
        journal_dir = Path(os.path.normpath(folder / journal_dir_name))
        if _commits_journal(reading, journal_dir, start) and any(
            staging.position > written_at and _add_covers(staging, journal_dir, start)
            for staging in reading.stagings
        ):
            covered.add(number)
    return frozenset(covered)
