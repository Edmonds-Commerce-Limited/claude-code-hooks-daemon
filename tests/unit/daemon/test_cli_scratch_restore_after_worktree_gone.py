"""Restoring an archive whose worktree is gone (Plan 00627 Task 6.2, the restore gate).

This file documents WHY ``worktree-reap --reap`` evacuates only a worktree
scratch root's own entries and keeps any worktree whose scratch holds a session
directory (DESIGN.md section 11, section 13 niggle):

- A root-level entry's archive restores into the main checkout's scratch root
  after the worktree that held it is removed.
- A session child's archive does NOT: ``restore`` opens the record's session
  directory in the destination root and never creates it, so once the worktree
  is gone the archive cannot come back unless the main checkout happens to hold
  a session directory of the same name.

The second test pins today's refusal (the restore the evacuation would need
does not happen), so the day ``restore`` learns to
create the session directory (the follow-up named in the niggle) this test
fails and the evacuation limit can be lifted with it. The same gap already
exists for a ``scratch-sweep --apply`` run in a linked worktree whose session
children are archived and whose worktree is later removed.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest
from tests.support.scratch_tree import ScratchTree, build_git_project, git

from claude_code_hooks_daemon.daemon.cli import build_parser

_DAY = 86400.0
_SESSION = "s-20261101T000000Z-abcdefgh"


@pytest.fixture
def tree(tmp_path: Path) -> ScratchTree:
    tree = build_git_project(tmp_path).tree
    (tmp_path / "project" / ".claude" / "hooks-daemon").mkdir(parents=True)
    return tree


def _project(tree: ScratchTree) -> Path:
    return tree.base / "project"


def _linked(tree: ScratchTree) -> Path:
    linked = tree.base / "linked"
    git(_project(tree), "worktree", "add", "-q", "-b", "side", str(linked))
    (linked / ".claude" / "hooks-daemon").mkdir(parents=True, exist_ok=True)
    return linked


def _run(project: Path, *argv: str, now: float) -> int:
    args = build_parser().parse_args(["scratch-sweep", *argv])
    args.project_root = project
    return int(
        args.func(
            args,
            wall_clock=lambda: now,
            process_cwds=lambda: {1: Path("/elsewhere")},
            confirm_apply=lambda _root, _notice: True,
        )
    )


def _old(path: Path, content: bytes, now: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    for item in (path, *path.parents):
        os.utime(item, (now - 5 * _DAY, now - 5 * _DAY))
        if item.name == "scratch":
            break


def _archive_in_linked(tree: ScratchTree, relative: str, capsys: pytest.CaptureFixture[str]) -> str:
    """Archive ``untracked/scratch/<relative>`` of a linked worktree, then remove the worktree."""
    now = time.time() + 3 * _DAY
    linked = _linked(tree)
    _old(linked / "untracked" / "scratch" / relative / "a.txt", b"alpha", now)
    capsys.readouterr()
    assert _run(linked, "--apply", "--json", now=now) == 0
    document = json.loads(capsys.readouterr().out)
    rows = [*document["entries"], *(row for sub in document["sessions"] for row in sub["entries"])]
    (archived,) = [row for row in rows if row["outcome"] == "archived"]
    shutil.rmtree(linked)
    git(_project(tree), "worktree", "prune")
    return str(archived["archive_id"])


def test_a_root_entry_restores_into_the_main_checkout(
    tree: ScratchTree, capsys: pytest.CaptureFixture[str]
) -> None:
    archive_id = _archive_in_linked(tree, "notes", capsys)
    assert _run(_project(tree), "restore", archive_id, now=time.time()) == 0
    assert (tree.root / "notes" / "a.txt").read_bytes() == b"alpha"


def test_a_session_child_cannot_be_restored_once_its_worktree_is_gone(
    tree: ScratchTree, capsys: pytest.CaptureFixture[str]
) -> None:
    archive_id = _archive_in_linked(tree, f"{_SESSION}/work", capsys)
    assert not (tree.root / _SESSION).exists()

    assert _run(_project(tree), "restore", archive_id, now=time.time()) == 1

    assert f"the session directory {_SESSION!r}" in capsys.readouterr().err
    assert not (tree.root / _SESSION).exists()
