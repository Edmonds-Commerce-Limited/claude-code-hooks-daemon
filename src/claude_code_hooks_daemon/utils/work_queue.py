"""The durable work queue: one record per dispatched agent (Plan 00470 Task 3.3).

A usage-limit restart leaves a new session with no teammates, and a user
interrupt kills every in-process agent. Both times each agent had to be
re-briefed by hand from whatever its worktree still held. This file is what makes
a respawn mechanical: for every agent a coordinator dispatched it holds the
worktree, the branch, the brief (inline, or a path to a brief file) and the last
commit the coordinator knew of.

The coordinator writes it through ``hooks-daemon work-queue add|update|done``
(the ``issue-sdlc`` runbook calls them at dispatch and completion), so nobody
edits JSON by hand. ``work_queue_rebrief`` (SessionStart ``resume``/``compact``)
and ``limit_rebrief`` read it back and list what is still ``running``.

**Project-wide, not per session.** A restart is a new session id, so a record
cannot be keyed to the session that wrote it.

**The writer is strict, the hook is not.** ``read_queue`` raises
``WorkQueueError`` on a corrupt file or a newer schema, so a writer never
overwrites a file it cannot read and a re-brief can say the queue is unreadable
instead of claiming it is empty. Concurrent writers (several CLI processes, and
daemon threads) serialise on a ``flock`` of a sidecar lock file.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.blockage_marker import write_json_atomically

logger = logging.getLogger(__name__)

#: Placed under ``ProjectContext.daemon_untracked_dir()``, beside ``limit-events.json``.
WORK_QUEUE_FILENAME: Final[str] = "work-queue.json"

#: Bumped when the record shape changes; a reader refuses a newer file.
SCHEMA_VERSION: Final[int] = 1

STATUS_RUNNING: Final[str] = "running"
STATUS_DONE: Final[str] = "done"
STATUS_ABANDONED: Final[str] = "abandoned"
STATUSES: Final[frozenset[str]] = frozenset({STATUS_RUNNING, STATUS_DONE, STATUS_ABANDONED})

#: An inline brief longer than this belongs in a file the record points at.
MAX_BRIEF_CHARS: Final[int] = 4000

#: How much of an inline brief the re-brief prints per agent.
LISTING_BRIEF_CHARS: Final[int] = 500

_KEY_VERSION: Final[str] = "version"
_KEY_RECORDS: Final[str] = "records"
_LOCK_SUFFIX: Final[str] = ".lock"
_LOCK_FILE_MODE: Final[int] = 0o600

_SECONDS_PER_MINUTE: Final[int] = 60
_SECONDS_PER_HOUR: Final[int] = 3600
_SECONDS_PER_DAY: Final[int] = 86400


class WorkQueueError(Exception):
    """The queue cannot be read, or a request against it is invalid."""


@dataclass(frozen=True)
class WorkRecord:
    """One dispatched agent, with what a respawn needs."""

    name: str
    worktree: str
    branch: str
    brief: str
    brief_file: str | None
    last_sha: str
    status: str
    created_at: float
    updated_at: float


_STR_FIELDS: Final[tuple[str, ...]] = ("name", "worktree", "branch", "brief", "last_sha", "status")
_TIME_FIELDS: Final[tuple[str, ...]] = ("created_at", "updated_at")


def default_queue_path() -> Path | None:
    """The project's queue file, or None when there is no project context."""
    if not ProjectContext.is_initialized():
        logger.debug("work_queue: no project context, so no queue")
        return None
    return ProjectContext.daemon_untracked_dir() / WORK_QUEUE_FILENAME


def _parse_record(entry: object) -> WorkRecord:
    if not isinstance(entry, dict):
        raise WorkQueueError(f"malformed record (not an object): {entry!r}")
    strings = {key: entry.get(key) for key in _STR_FIELDS}
    times = {key: entry.get(key) for key in _TIME_FIELDS}
    brief_file = entry.get("brief_file")
    if (
        not all(isinstance(v, str) for v in strings.values())
        or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in times.values())
        or not (brief_file is None or isinstance(brief_file, str))
        or strings["status"] not in STATUSES
        or not strings["name"]
    ):
        raise WorkQueueError(f"malformed record: {entry!r}")
    return WorkRecord(
        name=str(strings["name"]),
        worktree=str(strings["worktree"]),
        branch=str(strings["branch"]),
        brief=str(strings["brief"]),
        brief_file=brief_file,
        last_sha=str(strings["last_sha"]),
        status=str(strings["status"]),
        created_at=float(times["created_at"] or 0),
        updated_at=float(times["updated_at"] or 0),
    )


def read_queue(path: Path) -> list[WorkRecord]:
    """Every record in ``path``; ``[]`` when the file does not exist.

    Raises:
        WorkQueueError: The file is unreadable, not this schema, or holds a malformed record.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkQueueError(f"work queue unreadable ({path}): {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get(_KEY_RECORDS), list):
        raise WorkQueueError(f"work queue unreadable ({path}): not a queue object")
    version = raw.get(_KEY_VERSION)
    if version != SCHEMA_VERSION:
        raise WorkQueueError(
            f"work queue {path} has version {version!r}; this daemon reads version {SCHEMA_VERSION}"
        )
    return [_parse_record(entry) for entry in raw[_KEY_RECORDS]]


def _write(path: Path, records: list[WorkRecord]) -> None:
    payload = {
        _KEY_VERSION: SCHEMA_VERSION,
        _KEY_RECORDS: [
            {
                "name": r.name,
                "worktree": r.worktree,
                "branch": r.branch,
                "brief": r.brief,
                "brief_file": r.brief_file,
                "last_sha": r.last_sha,
                "status": r.status,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
            for r in records
        ],
    }
    try:
        write_json_atomically(path, payload)
    except OSError as exc:
        raise WorkQueueError(f"work queue not written ({path}): {exc}") from exc


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Hold an exclusive lock for a read-modify-write of ``path``."""
    lock_path = path.parent / f".{path.name}{_LOCK_SUFFIX}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, _LOCK_FILE_MODE)
    except OSError as exc:
        raise WorkQueueError(f"work queue lock unavailable ({lock_path}): {exc}") from exc
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def add_record(
    path: Path,
    name: str,
    *,
    worktree: str,
    branch: str,
    brief: str,
    brief_file: str | None,
    last_sha: str,
    now: float,
) -> None:
    """Record a dispatch as ``running``; a name already queued is re-dispatched in place.

    Raises:
        WorkQueueError: A required field is blank, the brief is too long to inline, or
            the queue cannot be read or written.
    """
    name = name.strip()
    worktree = worktree.strip()
    if not name:
        raise WorkQueueError("name must not be blank")
    if not worktree:
        raise WorkQueueError("worktree must not be blank")
    if not brief.strip() and not brief_file:
        raise WorkQueueError("a brief is required: pass --brief text or --brief-file PATH")
    if len(brief) > MAX_BRIEF_CHARS:
        raise WorkQueueError(
            f"brief is {len(brief)} characters (limit {MAX_BRIEF_CHARS}); "
            "put it in a file and pass --brief-file"
        )
    with _locked(path):
        records = read_queue(path)
        existing = next((r for r in records if r.name == name), None)
        record = WorkRecord(
            name=name,
            worktree=worktree,
            branch=branch.strip(),
            brief=brief,
            brief_file=brief_file,
            last_sha=last_sha.strip(),
            status=STATUS_RUNNING,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        kept = [r for r in records if r.name != name]
        _write(path, [*kept, record])


def update_record(
    path: Path,
    name: str,
    *,
    now: float,
    last_sha: str | None = None,
    status: str | None = None,
) -> WorkRecord:
    """Move a queued agent's last sha and/or status; fields left as None are kept.

    Raises:
        WorkQueueError: The name is not queued, the status is unknown, or the queue
            cannot be read or written.
    """
    if status is not None and status not in STATUSES:
        raise WorkQueueError(f"unknown status {status!r}; one of {sorted(STATUSES)}")
    with _locked(path):
        records = read_queue(path)
        current = next((r for r in records if r.name == name), None)
        if current is None:
            raise WorkQueueError(f"'{name}' is not in the work queue")
        updated = replace(
            current,
            last_sha=current.last_sha if last_sha is None else last_sha.strip(),
            status=current.status if status is None else status,
            updated_at=now,
        )
        _write(path, [updated if r.name == name else r for r in records])
    return updated


def active_records(records: list[WorkRecord]) -> list[WorkRecord]:
    """The records still ``running``, oldest dispatch first."""
    return sorted((r for r in records if r.status == STATUS_RUNNING), key=lambda r: r.created_at)


def _age(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    if seconds >= _SECONDS_PER_DAY:
        return f"{int(seconds // _SECONDS_PER_DAY)}d"
    if seconds >= _SECONDS_PER_HOUR:
        return f"{int(seconds // _SECONDS_PER_HOUR)}h"
    return f"{int(seconds // _SECONDS_PER_MINUTE)}m"


def _clip(text: str) -> str:
    return text if len(text) <= LISTING_BRIEF_CHARS else text[:LISTING_BRIEF_CHARS] + " [...]"


def _render_record(record: WorkRecord, now: float) -> list[str]:
    exists = Path(record.worktree).is_dir()
    lines = [
        f"- {record.name} (dispatched {_age(now - record.created_at)} ago, "
        f"last update {_age(now - record.updated_at)} ago)",
        f"    worktree: {record.worktree}" + ("" if exists else "  [MISSING on disk]"),
        f"    branch: {record.branch or '(none recorded)'}",
        f"    last sha: {record.last_sha or '(none recorded)'}",
    ]
    if record.brief_file:
        lines.append(f"    brief file: {record.brief_file}")
    if record.brief.strip():
        lines.append(f"    brief: {_clip(' '.join(record.brief.split()))}")
    return lines


def render_rebrief(records: list[WorkRecord], *, now: float) -> list[str]:
    """The advisory lines naming each running agent with its respawn facts; ``[]`` for none."""
    if not records:
        return []
    lines = [
        f"WORK QUEUE: {len(records)} dispatched agent(s) recorded as still running",
        "",
        "These agents are not respawned for you: a restart, an interrupt or a usage "
        "limit may have killed them, and nothing re-dispatches them. For each one, "
        "check its worktree (`git -C <worktree> status`, `git -C <worktree> log -1`) "
        "against the last sha, then re-dispatch it from its brief if the work is not "
        "finished, or close the record "
        "(`bin/hooks-daemon work-queue done NAME` / `update NAME --status abandoned`).",
        "",
    ]
    for record in records:
        lines += _render_record(record, now)
    lines += ["", "Full briefs: `bin/hooks-daemon work-queue list --json`."]
    return lines
