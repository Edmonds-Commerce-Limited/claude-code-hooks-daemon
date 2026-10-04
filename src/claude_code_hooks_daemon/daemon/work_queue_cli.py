"""The ``work-queue`` verb: write and read the durable work queue (Plan 00470 Task 3.3).

``add`` at dispatch, ``update``/``done`` as the agent reports, ``list`` to see what
is still running. The file format and its rules live in
``claude_code_hooks_daemon.utils.work_queue``; this module is argument handling
only. Every refusal prints to stderr and returns 1, so a coordinator's shell sees
that nothing was recorded.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.utils.work_queue import (
    STATUS_ABANDONED,
    STATUS_DONE,
    STATUSES,
    WORK_QUEUE_FILENAME,
    WorkQueueError,
    WorkRecord,
    active_records,
    add_record,
    read_queue,
    update_record,
)


def _queue_path(args: argparse.Namespace) -> Path:
    """The queue file for the project, initialising the project context if needed."""
    from claude_code_hooks_daemon.core.project_context import ProjectContext
    from claude_code_hooks_daemon.daemon.cli import get_project_path

    project_path = (
        Path(args.project_root).resolve() if args.project_root else get_project_path(None)
    )
    if not ProjectContext.is_initialized():
        try:
            ProjectContext.initialize(project_path / ".claude" / "hooks-daemon.yaml")
        except ValueError as exc:
            print(f"WARNING: could not initialise project context: {exc}", file=sys.stderr)
    try:
        return ProjectContext.daemon_untracked_dir() / WORK_QUEUE_FILENAME
    except RuntimeError as exc:
        raise WorkQueueError(f"no untracked directory to hold the queue: {exc}") from exc


def _head_sha(worktree: str) -> str:
    """The worktree's HEAD, for a record added without ``--sha``."""
    from claude_code_hooks_daemon.utils.git_repo import run_git

    done = run_git(Path(worktree), "rev-parse", "HEAD")
    sha = done.stdout.strip()
    if done.returncode != 0 or not sha:
        raise WorkQueueError(
            f"could not read HEAD of {worktree} ({done.stderr.strip() or 'not a git checkout'}); "
            "pass --sha"
        )
    return sha


def _cmd_add(args: argparse.Namespace, path: Path) -> int:
    if args.brief_file and not Path(args.brief_file).is_file():
        raise WorkQueueError(f"brief file not found: {args.brief_file}")
    last_sha = args.sha if args.sha else _head_sha(args.worktree)
    add_record(
        path,
        args.name,
        worktree=args.worktree,
        branch=args.branch,
        brief=args.brief or "",
        brief_file=str(Path(args.brief_file).resolve()) if args.brief_file else None,
        last_sha=last_sha,
        now=time.time(),
    )
    print(f"Queued '{args.name.strip()}' (running) at {last_sha}")
    return 0


def _cmd_update(args: argparse.Namespace, path: Path) -> int:
    record = update_record(path, args.name, now=time.time(), last_sha=args.sha, status=args.status)
    print(f"Updated '{record.name}': {record.status} at {record.last_sha}")
    return 0


def _cmd_done(args: argparse.Namespace, path: Path) -> int:
    record = update_record(path, args.name, now=time.time(), last_sha=args.sha, status=STATUS_DONE)
    print(f"Closed '{record.name}' (done) at {record.last_sha}")
    return 0


def _describe(record: WorkRecord) -> str:
    return (
        f"{record.name} [{record.status}] worktree={record.worktree} "
        f"branch={record.branch or '-'} sha={record.last_sha or '-'}"
    )


def _cmd_list(args: argparse.Namespace, path: Path) -> int:
    records = read_queue(path)
    shown = records if args.all else active_records(records)
    if args.json:
        print(json.dumps([asdict(r) for r in shown], indent=2))
    elif not shown:
        print("The work queue is empty." if args.all else "No running agents in the work queue.")
    else:
        for record in shown:
            print(_describe(record))
    return 0


_ACTIONS = {"add": _cmd_add, "update": _cmd_update, "done": _cmd_done, "list": _cmd_list}


def cmd_work_queue(args: argparse.Namespace) -> int:
    """Run one ``work-queue`` action.

    Returns:
        0 on success, 1 when the request was refused or the queue could not be used.
    """
    try:
        return _ACTIONS[args.work_queue_action](args, _queue_path(args))
    except WorkQueueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _project_root_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project-root",
        dest="project_root",
        type=Path,
        default=None,
        help="Project root override (default: auto-detected)",
    )


def add_work_queue_parser(subparsers: Any) -> None:
    """Register ``work-queue`` and its four actions on the CLI's subparsers."""
    parser = subparsers.add_parser(
        "work-queue",
        help="Record dispatched agents (worktree, branch, brief, last sha) so a restart "
        "can re-brief them: add, update, done, list",
    )
    actions = parser.add_subparsers(dest="work_queue_action", required=True)

    add = actions.add_parser("add", help="Record a dispatch as running (re-adding a name resets it)")
    add.add_argument("name", help="The agent's name")
    add.add_argument("--worktree", required=True, help="The agent's worktree path")
    add.add_argument("--branch", required=True, help="The agent's branch")
    brief = add.add_mutually_exclusive_group(required=True)
    brief.add_argument("--brief", help="The brief, inline (a long one belongs in --brief-file)")
    brief.add_argument("--brief-file", dest="brief_file", help="Path to a file holding the brief")
    add.add_argument("--sha", default=None, help="Last known commit (default: the worktree's HEAD)")
    _project_root_option(add)

    update = actions.add_parser("update", help="Move a queued agent's last sha or status")
    update.add_argument("name", help="The agent's name")
    update.add_argument("--sha", default=None, help="Last known commit")
    update.add_argument(
        "--status", default=None, choices=sorted(STATUSES), help=f"e.g. {STATUS_ABANDONED}"
    )
    _project_root_option(update)

    done = actions.add_parser("done", help="Close a queued agent as done")
    done.add_argument("name", help="The agent's name")
    done.add_argument("--sha", default=None, help="Its final commit")
    _project_root_option(done)

    listing = actions.add_parser("list", help="Show the queue (running records by default)")
    listing.add_argument("--all", action="store_true", help="Include done and abandoned records")
    listing.add_argument("--json", action="store_true", help="Machine-readable, with full briefs")
    _project_root_option(listing)

    parser.set_defaults(func=cmd_work_queue)
