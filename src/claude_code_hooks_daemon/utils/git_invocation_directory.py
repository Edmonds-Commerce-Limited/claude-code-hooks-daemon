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


def placement_problem(run: GitInvocation) -> str | None:
    """Why the repository ``run`` acts on cannot be stated, else None."""
    for assignment in run.assignments:
        name = assignment.split("=", 1)[0]
        if name in RELOCATING_VARIABLES:
            return f"`{name}` moves the repository or index git reads"
    for option in run.global_options:
        if option.split("=", 1)[0] in _RELOCATING_OPTIONS:
            return f"`{option}` moves the repository git reads"
    for step in (*run.directory, *dash_c_values(run.global_options)):
        if step is None:
            return "a `cd -`, `popd` or multi-operand `cd` names no directory"
        if _EXPANSION.search(step) or (step.startswith("~") and not _HOME_PATH.match(step)):
            return f"the directory `{step}` needs an expansion the daemon cannot perform"
    return None


def invocation_directory(run: GitInvocation, cwd: Path) -> Path:
    """Where ``run`` executes: ``cwd``, then each ``cd`` and ``-C`` in turn.

    Only meaningful once :func:`placement_problem` returned None.
    """
    directory = cwd
    for step in (*run.directory, *dash_c_values(run.global_options)):
        if step is None:
            raise ValueError("invocation_directory needs a placeable invocation")
        directory = directory / Path(step).expanduser()
    return directory
