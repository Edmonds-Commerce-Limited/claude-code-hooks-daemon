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
cannot state) is applied as ``git add -A``: every working-tree change, never
less than the add could stage.
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
_ADD_EVERYTHING: Final[str] = "-A"
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


@contextmanager
def simulated_staging(
    reading: CommitReading, cwd: str | Path | None, repo_root: Path
) -> Iterator[dict[str, str] | None]:
    """Yield the environment of the index ``reading``'s ``git add`` runs leave, else ``None``.

    ``None`` when no ``git add`` comes before the commit, or git could not set
    the copy up; the caller then reads the real index, as it always did. The
    scratch copy is removed when the block ends.
    """
    if not reading.stagings:
        yield None
        return
    with tempfile.TemporaryDirectory(prefix=_SCRATCH_PREFIX, ignore_cleanup_errors=True) as scratch:
        env = _scratch_environment(repo_root, Path(scratch))
        if env is not None:
            for staging in reading.stagings:
                _apply(staging, cwd, repo_root, env)
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
    result = run_git(directory, _ADD, *arguments, env=env)
    if result.returncode == 0:
        return
    if any(message in result.stderr for message in _NOTHING_STAGED_MESSAGES):
        return
    logger.debug("staging simulation: add failed (%s); taking every change", result.stderr)
    _add_everything(repo_root, env)


def _add_everything(repo_root: Path, env: Mapping[str, str]) -> None:
    """Stage every working-tree change into the scratch index."""
    result = run_git(repo_root, _ADD, _ADD_EVERYTHING, env=env)
    if result.returncode != 0:
        logger.warning("staging simulation: add -A failed in %s: %s", repo_root, result.stderr)
