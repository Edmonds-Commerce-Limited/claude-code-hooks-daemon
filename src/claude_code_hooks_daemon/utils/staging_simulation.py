"""The index a command's own ``git add`` leaves, read without running the add.

Ledger 00474 N246 (and 00466 N61): ``git add leak.txt && git commit -m x`` records
``leak.txt``, but a commit gate runs BEFORE the command, so the index it reads
does not hold the file yet. :func:`simulated_staging` runs each ``git add`` that
comes before the commit against a COPY of the index, with new blobs written to
a scratch object directory, and hands back the environment that points git at
them. A gate that asks git with that environment judges the tree the commit
will record. The real index, object store and working tree are never written.

``git update-index`` (with ``--add``/``--remove``) and ``git apply --cached``/
``--index`` are run against the same copy: the second from a patch file this
reading can open, whose ``---``/``+++`` headers name the paths it touches (staged
from the working tree when the patch itself will not apply). A patch it cannot
open or state the paths of is treated like an unreadable add.

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

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_commit_parsing import (
    ADD_TOKEN,
    APPLY_TOKEN,
    UPDATE_INDEX_TOKEN,
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

#: The headline wording for a deny filed under the gate's rule when the commit
#: could not be read, so the rule's own text (about content) is not claimed.
INCOMPLETE_SIMULATION_BLOCKED: Final[str] = "a commit whose staging this gate could not simulate"

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

#: ``git update-index`` options that put a named path into the index or take it
#: out; ``--cacheinfo``, ``--index-info``, ``--stdin`` and the rest name content
#: this reading cannot follow.
_UPDATE_INDEX_SHORT_LETTERS: Final[frozenset[str]] = frozenset("q")
_UPDATE_INDEX_LONG_FLAGS: Final[frozenset[str]] = frozenset(
    {"--add", "--remove", "--force-remove", "--replace", "--verbose"}
)

#: ``git apply`` options that leave the patch's meaning alone; ``-p<n>``, ``-C``,
#: ``--directory``, ``--include`` and ``--exclude`` change the paths, so are unreadable.
_APPLY_TO_INDEX_FLAGS: Final[frozenset[str]] = frozenset({"--cached", "--index"})
_APPLY_SHORT_LETTERS: Final[str] = "v"
_APPLY_LONG_FLAGS: Final[frozenset[str]] = frozenset({*_APPLY_TO_INDEX_FLAGS, "--verbose"})
_STDIN_OPERAND: Final[str] = "-"
_MAX_PATCH_BYTES: Final[int] = 8 * 1024 * 1024
_OLD_HEADER: Final[str] = "--- "
_NEW_HEADER: Final[str] = "+++ "
_OLD_SIDE: Final[str] = "a/"
_NEW_SIDE: Final[str] = "b/"
_DEV_NULL: Final[str] = "/dev/null"

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


class UnreadablePatchError(Exception):
    """A patch file whose touched paths this reading cannot state."""


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
        # copy2, not copyfile: git decides whether a file edited within the
        # index's own timestamp tick is modified by comparing entries with the
        # index file's mtime, and a copy stamped "now" hides such an edit.
        shutil.copy2(index, copied)
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
    if staging.subcommand == APPLY_TOKEN and not _APPLY_TO_INDEX_FLAGS.intersection(
        staging.arguments
    ):
        return  # without --cached/--index git apply only edits the working tree
    flags = {
        ADD_TOKEN: (_SHORT_FLAG_LETTERS, _LONG_FLAGS),
        UPDATE_INDEX_TOKEN: (_UPDATE_INDEX_SHORT_LETTERS, _UPDATE_INDEX_LONG_FLAGS),
        APPLY_TOKEN: (frozenset(_APPLY_SHORT_LETTERS), _APPLY_LONG_FLAGS),
    }[staging.subcommand]
    arguments = _readable_arguments(staging.arguments, *flags)
    if arguments is None or any(move is None for move in staging.moves):
        _add_everything(repo_root, env)
        return
    start = Path(cwd) if cwd else repo_root
    for directory in landing_directories(staging.moves, staging.optional_moves, start):
        if not _is_repository(directory, repo_root):
            continue
        if staging.subcommand == ADD_TOKEN:
            _add(directory, arguments, repo_root, env)
        elif staging.subcommand == UPDATE_INDEX_TOKEN:
            _update_index(directory, arguments, repo_root, env)
        else:
            _apply_patches(directory, arguments, repo_root, env)


def _readable_arguments(
    arguments: Sequence[str], short_letters: frozenset[str], long_flags: frozenset[str]
) -> list[str] | None:
    """``arguments`` when every one is a known flag or a literal operand, else ``None``."""
    readable: list[str] = []
    for position, word in enumerate(arguments):
        if word == _END_OF_OPTIONS:
            readable.extend(arguments[position:])
            break
        if word.startswith("--"):
            if word not in long_flags:
                return None
        elif word.startswith("-") and len(word) > 1:
            if not set(word[1:]) <= short_letters:
                return None
        readable.append(word)
    return None if any(is_shell_resolved(word) for word in readable) else readable


def _update_index(
    directory: Path, arguments: Sequence[str], repo_root: Path, env: Mapping[str, str]
) -> None:
    """``git update-index <arguments>`` against the scratch index; a failure takes every change."""
    result = run_git(directory, *_NO_SPLIT_INDEX, UPDATE_INDEX_TOKEN, *arguments, env=env)
    if result.returncode != 0:
        logger.debug(
            "staging simulation: update-index failed (%s); taking every change", result.stderr
        )
        _add_everything(repo_root, env)


def _patch_operands(arguments: Sequence[str]) -> list[str]:
    """The patch files among the readable ``git apply`` arguments."""
    operands: list[str] = []
    options_ended = False
    for word in arguments:
        if not options_ended and word == _END_OF_OPTIONS:
            options_ended = True
        elif options_ended or not word.startswith("-") or word == _STDIN_OPERAND:
            operands.append(word)
    return operands


def _apply_patches(
    directory: Path, arguments: Sequence[str], repo_root: Path, env: Mapping[str, str]
) -> None:
    """Apply each patch file to the scratch index; an unreadable patch takes every change.

    A patch that does not apply cleanly still stages the paths its headers name,
    taken from the working tree: the commit may run after the failed apply (``;``)
    and the gate must not judge less than could be staged.
    """
    operands = _patch_operands(arguments)
    if not operands or _STDIN_OPERAND in operands:
        _add_everything(repo_root, env)
        return
    try:
        patches = [(operand, _patch_paths(directory / operand)) for operand in operands]
    except UnreadablePatchError as error:
        log_and_continue(
            logger,
            error,
            reason="a patch whose paths cannot be stated is simulated as an add of every working-tree change, never as less than it could stage",
            level=logging.DEBUG,
        )
        _add_everything(repo_root, env)
    else:
        for operand, touched in patches:
            applied = run_git(
                directory, *_NO_SPLIT_INDEX, APPLY_TOKEN, "--cached", operand, env=env
            )
            if applied.returncode != 0:
                logger.debug(
                    "staging simulation: apply failed (%s); staging its paths", applied.stderr
                )
                # Header paths are relative to the repository root, whatever the directory.
                _add(repo_root, [_END_OF_OPTIONS, *touched], repo_root, env)


def _patch_paths(patch: Path) -> list[str]:
    """The paths ``patch`` touches, from its file headers.

    Raises:
        UnreadablePatchError: If the file cannot be read in full, names a path
            in quotes (special characters) or with no ``a/``/``b/`` prefix, or
            names no path at all.
    """
    try:
        if patch.stat().st_size > _MAX_PATCH_BYTES:
            raise UnreadablePatchError(f"patch {patch} is larger than {_MAX_PATCH_BYTES} bytes")
        text = patch.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise UnreadablePatchError(f"patch {patch} unreadable ({error})") from error
    paths: dict[str, None] = {}
    old_name = ""
    for line in text.splitlines():
        if line.startswith(_OLD_HEADER):
            old_name = _header_name(line[len(_OLD_HEADER) :], _OLD_SIDE)
        elif line.startswith(_NEW_HEADER):
            name = _header_name(line[len(_NEW_HEADER) :], _NEW_SIDE)
            if name == _DEV_NULL:
                name = old_name
            if not name or name == _DEV_NULL or name.startswith('"'):
                raise UnreadablePatchError(f"patch {patch} names a path this reading cannot state")
            paths[name] = None
    if not paths:
        raise UnreadablePatchError(f"patch {patch} names no file")
    return list(paths)


def _header_name(header: str, side: str) -> str:
    """The path of a ``---``/``+++`` header with its ``a/``/``b/`` side prefix removed.

    The empty string when the header carries no such prefix (``-p0`` patches).
    """
    name = header.split("\t")[0]
    if name == _DEV_NULL:
        return name
    if name.startswith('"'):
        return name
    return name[len(side) :] if name.startswith(side) else ""


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
        logger.warning(
            "staging simulation: add %s failed in %s: %s",
            " ".join(options),
            repo_root,
            result.stderr,
        )
        raise SimulationIncompleteError(
            INCOMPLETE_SIMULATION_REASON.format(
                why=result.stderr.strip() or f"git exited {result.returncode}"
            )
        )
