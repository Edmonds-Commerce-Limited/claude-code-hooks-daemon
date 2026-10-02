"""Journal entries a Bash command writes and stages before its own ``git commit``.

Ledger 00474 N317: ``mkplan.bash --journal 470 ... && git add <plan> && git commit``
records the day-file, but the commit gate runs BEFORE the command, so the
day-file does not exist yet and the staging simulation cannot see it.
:func:`command_journal_plans` reads the command itself: a plan counts when an
earlier statement appends a journal entry to it through the deployed
``mkplan.bash`` and a later statement, still before the last commit, is a
``git add`` that covers the plan's journal directory.
"""

import os
from collections.abc import Sequence
from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.common import plan_number_for_folder
from claude_code_hooks_daemon.plan_qa.model import MKPLAN_SCRIPT_NAME
from claude_code_hooks_daemon.utils.bash_flags import split_statements
from claude_code_hooks_daemon.utils.git_commit_parsing import (
    command_words,
    git_invocations,
    is_shell_resolved,
)
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

_JOURNAL_FLAG = "--journal"
_COMMIT = "commit"
_ADD = "add"
_END_OF_OPTIONS = "--"
_INTERPRETERS = frozenset({"bash", "sh"})
_LIST_OPERATORS = ("&&", "||")
_ADD_ALL_FLAGS = frozenset({"-A", "--all"})
#: ``git add -u`` stages only files git already tracks, never a new day-file.
_UPDATE_FLAGS = frozenset({"-u", "--update"})


def _journal_plan_number(words: Sequence[str], script: Path, cwd: Path) -> int | None:
    """The plan ``words`` appends a journal entry to through ``script``, else None."""
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
    if (cwd / named).resolve() != script.resolve():
        return None
    return int(number)


def _is_commit(statement: str) -> bool:
    return any(run.subcommand == _COMMIT for run in git_invocations(statement))


def _add_covers(statement: str, journal_dir: Path, cwd: Path) -> bool:
    """Whether ``statement`` is a plain ``git add`` that stages ``journal_dir``'s new files."""
    for run in git_invocations(statement):
        if run.subcommand != _ADD or run.directory or run.global_options or run.assignments:
            continue
        pathspecs: list[str] = []
        add_all = False
        update_only = False
        options_ended = False
        for word in run.arguments:
            if not options_ended and word == _END_OF_OPTIONS:
                options_ended = True
            elif not options_ended and word.startswith("-"):
                add_all = add_all or word in _ADD_ALL_FLAGS
                update_only = update_only or word in _UPDATE_FLAGS
            else:
                pathspecs.append(word)
        if update_only:
            continue
        if not pathspecs and add_all:
            return True
        for pathspec in pathspecs:
            if is_shell_resolved(pathspec):
                continue
            target = Path(os.path.normpath(cwd / pathspec))
            if journal_dir == target or target in journal_dir.parents:
                return True
    return False


def _plan_folder(plan_dir: Path, plan_number: int) -> Path | None:
    """The folder of plan ``plan_number`` directly under ``plan_dir``, else None."""
    if not plan_dir.is_dir():
        return None
    for entry in sorted(plan_dir.iterdir()):
        if entry.is_dir() and plan_number_for_folder(entry.name) == plan_number:
            return entry
    return None


def command_journal_plans(
    command: str,
    cwd: str | Path | None,
    project_root: Path,
    plan_dir_rel: str,
    journal_dir_name: str,
) -> frozenset[int]:
    """Plan numbers ``command`` journals and stages before its last ``git commit``."""
    statements = [
        part.strip()
        for statement in split_statements(command)
        for part in split_unquoted(statement, _LIST_OPERATORS)
        if part.strip()
    ]
    last_commit = max(
        (position for position, text in enumerate(statements) if _is_commit(text)), default=-1
    )
    start = Path(cwd) if cwd else project_root
    plan_dir = project_root / plan_dir_rel
    script = plan_dir / MKPLAN_SCRIPT_NAME
    journalled: dict[int, int] = {}
    covered: set[int] = set()
    for position, text in enumerate(statements[:last_commit]):
        plan_number = _journal_plan_number(command_words(text), script, start)
        if plan_number is not None:
            journalled.setdefault(plan_number, position)
            continue
        for number, written_at in journalled.items():
            folder = _plan_folder(plan_dir, number)
            if folder is None or written_at >= position:
                continue
            if _add_covers(text, Path(os.path.normpath(folder / journal_dir_name)), start):
                covered.add(number)
    return frozenset(covered)
