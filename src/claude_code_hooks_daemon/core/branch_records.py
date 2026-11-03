"""Who created and who touched a branch, kept in the repository's own git config.

The creator record is three keys under ``branch.<name>``: ``hooksDaemonCreator``
(``<session_id>:<agent_id>``, the agent empty for the main thread),
``hooksDaemonCreated`` (unix time) and ``hooksDaemonRoute`` (how it was made:
``switch``, ``checkout``, ``branch``, ``worktree`` or ``worktree_create``). It is
written once, and never over an existing creator, so resetting a branch does not
claim it.

The touch record is the multi-valued ``hooksDaemonTouchedBy``: one identity per
session and agent that changed the branch. Each identity is added once per branch
per session, remembered in the session's spend-ledger state so later calls cost
no git at all. ``touched_branches`` reads it back for the stop guard (Plan 00558
Task 4.4).

Config is the store because it travels with the repository's branches across
every worktree and needs no file of ours to be in sync with ``refs/heads``.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.worktree_naming import is_worktree_create_name
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import branch_ref, run_git
from claude_code_hooks_daemon.utils.spend_ledger import read_state, state_path, write_state

logger = logging.getLogger(__name__)

CREATOR_KEY = "hooksDaemonCreator"
CREATED_KEY = "hooksDaemonCreated"
ROUTE_KEY = "hooksDaemonRoute"
TOUCHED_KEY = "hooksDaemonTouchedBy"

#: The route WorktreeCreate records; WorktreeRemove deletes only these branches.
WORKTREE_CREATE_ROUTE = "worktree_create"

#: Spend-ledger state kind holding the branches already recorded this session.
_STATE_KIND = "branch-touch"
_SEEN = "seen"

#: ``git config`` exit status for "no such key" (any other non-zero is a failure).
_CONFIG_KEY_ABSENT = 1


def identity(session_id: str, agent_id: str | None) -> str:
    """The ``<session>:<agent>`` identity; the agent is empty on the main thread."""
    return f"{session_id}:{agent_id or ''}"


def _key(name: str, key: str) -> str:
    return f"branch.{name}.{key}"


def _get_all(repo: Path, name: str, key: str, timeout: float) -> list[str]:
    """Every value of ``branch.<name>.<key>``; raises RuntimeError when git fails."""
    result = run_git(repo, "config", "--get-all", _key(name, key), timeout=timeout)
    if result.returncode == _CONFIG_KEY_ABSENT:
        return []
    if result.returncode != 0:
        raise RuntimeError(
            f"git config --get-all {_key(name, key)} failed: {result.stderr.strip()}"
        )
    return [line for line in result.stdout.splitlines() if line]


def _set(repo: Path, name: str, key: str, value: str, timeout: float, *, add: bool = False) -> bool:
    """Write one key; a failure is logged and reported as False."""
    args = ["config", "--add"] if add else ["config"]
    result = run_git(repo, *args, _key(name, key), value, timeout=timeout)
    if result.returncode != 0:
        logger.warning(
            "branch_records: could not write %s in %s: %s",
            _key(name, key),
            repo,
            result.stderr.strip(),
        )
        return False
    return True


def write_creator(
    repo: Path,
    name: str,
    creator: str,
    route: str,
    *,
    now: float | None = None,
    timeout: float = Timeout.GIT_CONTEXT,
) -> bool:
    """Write the three creator keys unconditionally (three git calls).

    For a caller that has just created ``name`` itself, such as WorktreeCreate;
    ``record_creation`` is the checked form. Returns False when any write failed.
    """
    created = str(int(time.time() if now is None else now))
    results = [
        _set(repo, name, CREATOR_KEY, creator, timeout),
        _set(repo, name, CREATED_KEY, created, timeout),
        _set(repo, name, ROUTE_KEY, route, timeout),
    ]
    return all(results)


def record_creation(
    repo: Path,
    name: str,
    *,
    session_id: str,
    agent_id: str | None,
    route: str,
    now: float | None = None,
) -> bool:
    """Record the creator of ``name`` once the ref is confirmed and nobody claims it.

    Returns True when the record was written. A missing ref, an existing creator
    or a git failure writes nothing (failures are logged).
    """
    exists = run_git(repo, "show-ref", "--verify", "--quiet", branch_ref(name))
    if exists.returncode != 0:
        return False
    try:
        if _get_all(repo, name, CREATOR_KEY, Timeout.GIT_CONTEXT):
            return False
    except RuntimeError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"branch_records: the creator of {name} is left unrecorded; a recorder "
            "never blocks the call it observes",
        )
        return False
    return write_creator(repo, name, identity(session_id, agent_id), route, now=now)


def creator_route(repo: Path, name: str, *, timeout: float = Timeout.GIT_CONTEXT) -> str | None:
    """The recorded creation route of ``name``; None when no record exists.

    Raises:
        RuntimeError: git could not read the config.
    """
    values = _get_all(repo, name, ROUTE_KEY, timeout)
    return values[-1] if values else None


def worktree_branch_deletable(
    repo: Path, name: str, *, timeout: float = Timeout.GIT_CONTEXT
) -> bool:
    """Whether WorktreeRemove may delete ``name`` (when merged) as its own branch.

    The creator record decides: route ``worktree_create`` is eligible, any other
    route is not. Only a branch with no record at all falls back to the
    ``<slug>-<8 hex>`` name shape. An unreadable record is not eligible.
    """
    try:
        route = creator_route(repo, name, timeout=timeout)
    except RuntimeError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"branch_records: {name} is kept because its creator record is "
            "unreadable; an unproven branch is never deleted",
        )
        return False
    if route is None:
        return is_worktree_create_name(name)
    return route == WORKTREE_CREATE_ROUTE


def record_touch(
    repo: Path,
    branch: str,
    *,
    session_id: str,
    agent_id: str | None,
    untracked: Path,
) -> bool:
    """Add this identity to ``branch``'s touch record, once per session state.

    A call with an agent touching a branch whose creator is this session's main
    thread (``<session>:``, as WorktreeCreate writes it) rebinds the creator to
    the agent. Returns whether the identity is on the record; every git failure
    is logged and reported as False.
    """
    who = identity(session_id, agent_id)
    path = state_path(untracked, session_id, _STATE_KIND, who)
    state = read_state(path)
    seen = state.get(_SEEN)
    seen_list: list[str] = [str(item) for item in seen] if isinstance(seen, list) else []
    marker = f"{repo.resolve()}\0{branch}"
    if marker in seen_list:
        return True
    try:
        touched = _get_all(repo, branch, TOUCHED_KEY, Timeout.GIT_CONTEXT)
        creators = _get_all(repo, branch, CREATOR_KEY, Timeout.GIT_CONTEXT) if agent_id else []
    except RuntimeError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"branch_records: the touch of {branch} is left unrecorded; a recorder "
            "never blocks the call it observes",
        )
        return False
    if who not in touched and not _set(
        repo, branch, TOUCHED_KEY, who, Timeout.GIT_CONTEXT, add=True
    ):
        return False
    if creators == [identity(session_id, None)]:
        _set(repo, branch, CREATOR_KEY, who, Timeout.GIT_CONTEXT)
    write_state(path, {**state, _SEEN: [*seen_list, marker]})
    return True


def _touch_values(repo: Path, timeout: float) -> list[tuple[str, str]]:
    """Every ``(branch, identity)`` pair on a touch record; RuntimeError when git fails."""
    pattern = rf"^branch\..*\.{TOUCHED_KEY.lower()}$"
    result = run_git(repo, "config", "--get-regexp", pattern, timeout=timeout)
    if result.returncode == _CONFIG_KEY_ABSENT:
        return []
    if result.returncode != 0:
        raise RuntimeError(f"git config --get-regexp failed: {result.stderr.strip()}")
    prefix, suffix = "branch.", f".{TOUCHED_KEY.lower()}"
    pairs: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        key, _, value = line.partition(" ")
        if key.startswith(prefix) and key.endswith(suffix):
            pairs.append((key[len(prefix) : -len(suffix)], value))
    return pairs


def touched_branches(repo: Path, session_id: str, agent_id: str | None) -> list[str]:
    """The branches of ``repo`` whose touch record holds this identity, sorted.

    Raises:
        RuntimeError: git could not read the config.
    """
    who = identity(session_id, agent_id)
    return sorted({name for name, value in _touch_values(repo, Timeout.GIT_CONTEXT) if value == who})


def touched_by_session(
    repo: Path, session_id: str, *, timeout: float = Timeout.GIT_CONTEXT
) -> dict[str, set[str]]:
    """Each branch this session touched, with the agent ids that touched it.

    The main thread is the empty agent id.

    Raises:
        RuntimeError: git could not read the config.
    """
    prefix = f"{session_id}:"
    touched: dict[str, set[str]] = {}
    for name, value in _touch_values(repo, timeout):
        if value.startswith(prefix):
            touched.setdefault(name, set()).add(value[len(prefix) :])
    return touched
