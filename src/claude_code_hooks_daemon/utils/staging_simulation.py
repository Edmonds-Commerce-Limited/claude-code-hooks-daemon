"""The index a command's own ``git add`` leaves, read without running the add.

Ledger 00474 N246 (and 00466 N61): ``git add leak.txt && git commit -m x`` records
``leak.txt``, but a commit gate runs BEFORE the command, so the index it reads
does not hold the file yet. :func:`simulated_staging` runs each ``git add`` that
comes before the commit against a COPY of the index, with new blobs written to
a scratch object directory, and hands back the environment that points git at
them. A gate that asks git with that environment judges the tree the commit
will record. The real index, object store and working tree are never written.

An add whose scope cannot be read (a pathspec the shell builds, an interactive
or file-driven option, a directory the command reaches by a move this reading
cannot state) is applied as ``git add -A --ignore-errors``: every working-tree
change git can stage, never less than the add could stage.

When even that cannot finish (git timed out, or failed outright) the copy is
NOT the index the commit will record, and a gate must not judge it as if it
were: :func:`simulated_staging` raises :class:`SimulationIncompleteError`, whose
message tells the user to run ``git add`` as its own call.

The add runs the repository's own configured clean filters and ``core.fsmonitor``
hook, as the real add does moments later; that is the owner's own configuration.
It runs with ``core.splitIndex=false`` so it never writes a ``sharedindex.*``
file into the real ``.git``.
"""

import logging
import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.git_commit_parsing import (
    CommitReading,
    StagingRun,
    is_shell_resolved,
)
from claude_code_hooks_daemon.utils.git_facts import landing_directories
from claude_code_hooks_daemon.utils.git_repo import run_git

logger = logging.getLogger(__name__)

_ADD: Final[str] = "add"
_ADD_EVERYTHING: Final[tuple[str, ...]] = ("-A", "--ignore-errors")
_ADD_TRACKED: Final[tuple[str, ...]] = ("-u",)
_NO_SPLIT_INDEX: Final[tuple[str, ...]] = ("-c", "core.splitIndex=false")

#: ``git add --ignore-errors`` stages what it can and exits 1 for what it could
#: not (an embedded repository with no commit); any other non-zero status means
#: it did not run to the end.
_PARTIAL_ADD_EXIT: Final[int] = 1

INCOMPLETE_SIMULATION_REASON: Final[str] = (
    "The `git add` in this command could not be simulated completely ({why}), so "
    "the commit gate cannot tell what the commit would record. Run `git add` as "
    "its own call first, then run `git commit` as a separate command: the gate "
    "then reads the real index."
)
_END_OF_OPTIONS: Final[str] = "--"
_SCRATCH_PREFIX: Final[str] = "echd-staging-"
_INDEX_NAME: Final[str] = "index"
_OBJECTS_NAME: Final[str] = "objects"

_INDEX_FILE_VAR: Final[str] = "GIT_INDEX_FILE"
_OBJECT_DIRECTORY_VAR: Final[str] = "GIT_OBJECT_DIRECTORY"
_ALTERNATE_OBJECTS_VAR: Final[str] = "GIT_ALTERNATE_OBJECT_DIRECTORIES"

#: ``git add`` flags that change WHAT is staged or only report; every other
#: option (``-p``, ``--chmod``, ``--pathspec-from-file``, ...) is one this reading
#: cannot follow.
_SHORT_FLAG_LETTERS: Final[frozenset[str]] = frozenset("fAuNvn")
_LONG_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "--force",
        "--all",
        "--no-all",
        "--update",
        "--intent-to-add",
        "--verbose",
        "--dry-run",
        "--ignore-removal",
        "--no-ignore-removal",
        "--renormalize",
        "--ignore-errors",
    }
)

#: What git says when an add stages NOTHING because of the paths it was given,
#: rather than because git could not run: the real add fails the same way.
_NOTHING_STAGED_MESSAGES: Final[tuple[str, ...]] = (
    "did not match any files",
    "ignored by one of your .gitignore files",
)


class SimulationIncompleteError(Exception):
    """The copy of the index is not what the command's ``git add`` would leave.

    The message is the reason to give the user; a gate denies with it.
    """


@contextmanager
def simulated_staging(
    reading: CommitReading,
    cwd: str | Path | None,
    repo_root: Path,
    *,
    include_tracked_changes: bool = False,
) -> Iterator[dict[str, str] | None]:
    """Yield the environment of the index ``reading``'s ``git add`` runs leave, else ``None``.

    ``None`` when no ``git add`` comes before the commit, or git could not set
    the copy up; the caller then reads the real index, as it always did. The
    scratch copy is removed when the block ends.

    ``include_tracked_changes`` also simulates the ``git add -u`` that a
    ``git commit -a``/``--all`` performs, so the copy holds what that commit
    records: every modified or deleted tracked file, and no untracked one.
    Off by default, because most callers judge the index as it stands.

    Raises:
        SimulationIncompleteError: If an add could not be applied to the copy,
            so the copy is not the index the commit will record.
    """
    commits_tracked = include_tracked_changes and reading.commits_all
    if not reading.stagings and not commits_tracked:
        yield None
        return
    with tempfile.TemporaryDirectory(prefix=_SCRATCH_PREFIX, ignore_cleanup_errors=True) as scratch:
        env = _scratch_environment(repo_root, Path(scratch))
        if env is not None:
            for staging in reading.stagings:
                _apply(staging, cwd, repo_root, env)
            if commits_tracked:
                _add_tracked_changes(repo_root, env)
        yield env


def _git_path(repo_root: Path, name: str) -> Path | None:
    """Where git keeps ``name`` for the repository at ``repo_root``."""
    result = run_git(repo_root, "rev-parse", "--git-path", name)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return repo_root / result.stdout.strip()


def _scratch_environment(repo_root: Path, scratch: Path) -> dict[str, str] | None:
    """The environment of a copy of ``repo_root``'s index in ``scratch``, or ``None``."""
    index = _git_path(repo_root, _INDEX_NAME)
    objects = _git_path(repo_root, _OBJECTS_NAME)
    if index is None or objects is None:
        logger.warning("staging simulation: git could not name the index of %s", repo_root)
        return None
    copied = scratch / _INDEX_NAME
    if index.is_file():
        shutil.copyfile(index, copied)
    written = scratch / _OBJECTS_NAME
    written.mkdir()
    alternates = [str(objects), *filter(None, [os.environ.get(_ALTERNATE_OBJECTS_VAR)])]
    return {
        _INDEX_FILE_VAR: str(copied),
        _OBJECT_DIRECTORY_VAR: str(written),
        _ALTERNATE_OBJECTS_VAR: os.pathsep.join(alternates),
    }


def _apply(
    staging: StagingRun, cwd: str | Path | None, repo_root: Path, env: Mapping[str, str]
) -> None:
    """Run ``staging`` against the scratch index, in every directory it may run in."""
    arguments = _readable_arguments(staging.arguments)
    if arguments is None or any(move is None for move in staging.moves):
        _add_everything(repo_root, env)
        return
    start = Path(cwd) if cwd else repo_root
    for directory in landing_directories(staging.moves, staging.optional_moves, start):
        if _is_repository(directory, repo_root):
            _add(directory, arguments, repo_root, env)


def _readable_arguments(arguments: Sequence[str]) -> list[str] | None:
    """``arguments`` when every one is a flag or a literal pathspec, else ``None``."""
    readable: list[str] = []
    for position, word in enumerate(arguments):
        if word == _END_OF_OPTIONS:
            readable.extend(arguments[position:])
            break
        if word.startswith("--"):
            if word not in _LONG_FLAGS:
                return None
        elif word.startswith("-") and len(word) > 1:
            if not set(word[1:]) <= _SHORT_FLAG_LETTERS:
                return None
        readable.append(word)
    return None if any(is_shell_resolved(word) for word in readable) else readable


def _is_repository(directory: Path, repo_root: Path) -> bool:
    """Whether ``directory`` is a place inside the repository at ``repo_root``."""
    result = run_git(directory, "rev-parse", "--show-toplevel")
    return result.returncode == 0 and Path(result.stdout.strip()).resolve() == repo_root.resolve()


def _add(
    directory: Path, arguments: Sequence[str], repo_root: Path, env: Mapping[str, str]
) -> None:
    """``git add <arguments>`` in ``directory``; a failure git would share is no staging."""
    result = run_git(directory, *_NO_SPLIT_INDEX, _ADD, *arguments, env=env)
    if result.returncode == 0:
        return
    if any(message in result.stderr for message in _NOTHING_STAGED_MESSAGES):
        return
    logger.debug("staging simulation: add failed (%s); taking every change", result.stderr)
    _add_everything(repo_root, env)


def _add_everything(repo_root: Path, env: Mapping[str, str]) -> None:
    """Stage every working-tree change git can into the scratch index."""
    _run_complete_add(repo_root, _ADD_EVERYTHING, env)


def _add_tracked_changes(repo_root: Path, env: Mapping[str, str]) -> None:
    """Stage every modified or deleted tracked file, as `git commit -a` does."""
    _run_complete_add(repo_root, _ADD_TRACKED, env)


def _run_complete_add(repo_root: Path, options: Sequence[str], env: Mapping[str, str]) -> None:
    """``git add <options>`` at the repository root against the scratch index.

    Raises:
        SimulationIncompleteError: If git did not run to the end (timeout, or a
            failure other than files it had to skip).
    """
    result = run_git(repo_root, *_NO_SPLIT_INDEX, _ADD, *options, env=env)
    if result.returncode not in (0, _PARTIAL_ADD_EXIT):
        logger.warning("staging simulation: add -A failed in %s: %s", repo_root, result.stderr)
        raise SimulationIncompleteError(
            INCOMPLETE_SIMULATION_REASON.format(
                why=result.stderr.strip() or f"git exited {result.returncode}"
            )
        )
