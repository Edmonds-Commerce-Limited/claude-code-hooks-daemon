"""Where a parsed ``git`` invocation runs, and when that cannot be stated.

Shared by every gate that must judge a git command in the repository it will
actually run in: the directory is the start, then each ``cd``/``pushd`` and each
``git -C`` in turn. A command whose repository or directory cannot be stated
statically (``cd -``, ``$VAR``, ``--git-dir``, ``GIT_DIR``) is reported by
:func:`placement_problem`, and a gate that cannot place a command must deny it
rather than judge the wrong repository.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.core.utils import expand_cwd_references
from claude_code_hooks_daemon.utils.git_commit_parsing import GitInvocation
from claude_code_hooks_daemon.utils.git_repo import RELOCATING_VARIABLES

_DASH_C: Final[str] = "-C"
_RELOCATING_OPTIONS: Final[frozenset[str]] = frozenset({"--git-dir", "--work-tree"})
_EXPANSION: Final[re.Pattern[str]] = re.compile(r"[$`*?\[]")
_HOME_PATH: Final[re.Pattern[str]] = re.compile(r"~(?:/|$)")


def dash_c_values(global_options: tuple[str, ...]) -> list[str]:
    """The ``-C`` directories among git's global options, in order."""
    return [
        global_options[index + 1]
        for index, option in enumerate(global_options[:-1])
        if option == _DASH_C
    ]


def _steps(run: GitInvocation, cwd: Path | None) -> list[str | None]:
    """The directory steps of ``run``: each ``cd`` target, then each ``-C`` value.

    With ``cwd`` given, a step spelled ``$PWD``, ``${PWD}``, ``$(pwd)`` or
    ``$(git rev-parse --show-toplevel)`` is read as the shell reads it: in the
    directory the earlier ``cd`` steps reached (the ``-C`` values are all read
    in the directory the last ``cd`` reached, since ``-C`` moves git and not the
    shell). That is the resolution path judgement applies to a write target
    (:func:`~claude_code_hooks_daemon.core.utils.expand_cwd_references`); any
    other expansion stays as written and is reported by :func:`placement_problem`.
    """
    steps: list[str | None] = []
    here = None if cwd is None or not cwd.is_absolute() else cwd
    for index, step in enumerate((*run.directory, *dash_c_values(run.global_options))):
        if step is not None and here is not None:
            step = expand_cwd_references(step, str(here))
        steps.append(step)
        in_cd_chain = index < len(run.directory)
        if in_cd_chain and here is not None:
            unplaced = step is None or _EXPANSION.search(step) is not None
            here = None if unplaced else here / Path(step).expanduser()
    return steps


def placement_problem(run: GitInvocation, cwd: Path | None = None) -> str | None:
    """Why the repository ``run`` acts on cannot be stated, else None.

    ``cwd`` is where the command starts; give it and a ``$PWD``, ``$(pwd)`` or
    ``$(git rev-parse --show-toplevel)`` directory is placed instead of reported.
    """
    for assignment in run.assignments:
        name = assignment.split("=", 1)[0]
        if name in RELOCATING_VARIABLES:
            return f"`{name}` moves the repository or index git reads"
    for option in run.global_options:
        if option.split("=", 1)[0] in _RELOCATING_OPTIONS:
            return f"`{option}` moves the repository git reads"
    for step in _steps(run, cwd):
        if step is None:
            return "a `cd -`, `popd` or multi-operand `cd` names no directory"
        if _EXPANSION.search(step) or (step.startswith("~") and not _HOME_PATH.match(step)):
            return f"the directory `{step}` needs an expansion the daemon cannot perform"
    return None


def invocation_directory(run: GitInvocation, cwd: Path) -> Path:
    """Where ``run`` executes: ``cwd``, then each ``cd`` and ``-C`` in turn.

    Only meaningful once :func:`placement_problem` returned None for the same
    ``cwd``.
    """
    directory = cwd
    for step in _steps(run, cwd):
        if step is None:
            raise ValueError("invocation_directory needs a placeable invocation")
        directory = directory / Path(step).expanduser()
    return directory
