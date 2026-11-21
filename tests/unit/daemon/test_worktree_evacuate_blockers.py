"""Each blocking verdict keeps the worktree on a real repository (Plan 00627 Task 6.2).

One test per verdict the evacuation gate refuses that is not covered by
``test_worktree_evacuate.py``: PROTECTED, REFERENCED, STUCK, liveness unknown,
a foreign owner, no birth stamp and an incomplete walk. Each runs
``worktree-reap --reap`` through the CLI on a real repository with a real
linked worktree, and asserts the worktree is kept, nothing in its scratch is
touched, no store is created and the question is never asked.
"""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from tests.support.scratch_tree import ScratchTree, commit_file, git
from tests.unit.daemon.test_worktree_evacuate import (
    _NAME,
    _build,
    _git_identity,
    _inodes,
    _keep_text,
    _main,
    _never_asked,
    _scratch,
    _set_mtime,
    _store,
    _worktree,
    _write,
)

from claude_code_hooks_daemon.core import worktree_scratch_evacuation
from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.cli import cmd_worktree_reap
from claude_code_hooks_daemon.daemon.worktree_evacuate import EvacuateSeams

__all__ = ["_git_identity"]

_DAY = 86400.0
_ELSEWHERE: Mapping[int, Path] = {1: Path("/elsewhere")}


@pytest.fixture
def tree(tmp_path: Path) -> ScratchTree:
    return _build(tmp_path)


def _old(path: Path) -> None:
    """Set ``path`` and everything in it five days back; its ctime stays now."""
    _set_mtime(path, time.time() - 5 * _DAY)


def _due_entry(tree: ScratchTree) -> Path:
    """``old/`` holding two files, due once the clock is past its ctime's TTL."""
    entry = _scratch(tree) / "old"
    _write(entry / "a.txt", b"alpha", time.time())
    _write(entry / "sub" / "b.txt", b"beta", time.time())
    _old(entry)
    return entry


def _run(
    tree: ScratchTree,
    capsys: pytest.CaptureFixture[str],
    *,
    process_cwds: Callable[[], Mapping[int, Path]] = lambda: _ELSEWHERE,
) -> tuple[int, str]:
    now = time.time() + _DAY + 60
    args = argparse.Namespace(
        project_root=str(_main(tree)),
        base_branch="main",
        reap=True,
        only=_NAME,
        reap_branches=False,
    )
    rc = cmd_worktree_reap(
        args,
        age_fn=lambda _p: 999_999.0,
        process_cwds_fn=lambda: {},
        evacuate_seams=EvacuateSeams(
            confirm=_never_asked, wall_clock=lambda: now, process_cwds=process_cwds
        ),
    )
    return rc, capsys.readouterr().out


def _assert_kept(tree: ScratchTree, rc: int, out: str, before: object, blocker: str) -> None:
    assert rc == 1, out
    assert _worktree(tree).is_dir(), out
    assert _inodes(_scratch(tree)) == before, out
    assert not _store(tree).exists(), out
    assert blocker in _keep_text(out), out


class TestEachBlockingVerdictKeepsTheWorktree:
    def test_protected(self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]) -> None:
        """A clone of the project holding a commit no remote holds (R6)."""
        clone = _scratch(tree) / "clone"
        clone.parent.mkdir(parents=True, exist_ok=True)
        # --no-hardlinks: a hard-linked object has a name outside the entry (STUCK).
        git(_main(tree), "clone", "-q", "--no-hardlinks", str(_main(tree)), str(clone))
        commit_file(clone, "work.txt", "unpushed\n", "unpushed work")
        _old(clone)
        before = _inodes(_scratch(tree))

        rc, out = _run(tree, capsys)

        _assert_kept(tree, rc, out, before, "clone: PROTECTED")

    def test_referenced(self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]) -> None:
        """A tracked file on the worktree's branch names a path in the entry."""
        commit_file(_main(tree), "NOTES.md", "see untracked/scratch/old/a.txt\n", "cite it")
        git(_worktree(tree), "merge", "-q", "--ff-only", "main")
        _due_entry(tree)
        before = _inodes(_scratch(tree))

        rc, out = _run(tree, capsys)

        _assert_kept(tree, rc, out, before, "old: REFERENCED")

    def test_stuck(
        self, tree: ScratchTree, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A file with another name outside the entry was never read whole."""
        entry = _due_entry(tree)
        os.link(entry / "a.txt", tmp_path / "outside.txt")
        _old(entry)
        before = _inodes(_scratch(tree))

        rc, out = _run(tree, capsys)

        _assert_kept(tree, rc, out, before, "old: STUCK")

    def test_liveness_unknown(self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]) -> None:
        """No process working directory was readable: "no process in it" is unproven."""
        _due_entry(tree)
        before = _inodes(_scratch(tree))

        rc, out = _run(tree, capsys, process_cwds=lambda: {})

        _assert_kept(tree, rc, out, before, "no process working directory could be read")

    @pytest.mark.skipif(os.geteuid() != 0, reason="giving a file to another user needs root")
    def test_foreign_owner(self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]) -> None:
        """An inode another user owns is never packed (fix B)."""
        entry = _due_entry(tree)
        os.chown(entry / "sub" / "b.txt", 4242, 4242)
        _old(entry)
        before = _inodes(_scratch(tree))

        rc, out = _run(tree, capsys)

        _assert_kept(tree, rc, out, before, "old: 'sub/b.txt' is owned by uid 4242")

    def test_no_birth_stamp(
        self,
        tree: ScratchTree,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A filesystem that records no birth time cannot bind consent (fix A)."""
        _due_entry(tree)
        before = _inodes(_scratch(tree))
        monkeypatch.setattr(worktree_scratch_evacuation, "birth_stamp", lambda _fd, _name: None)

        rc, out = _run(tree, capsys)

        _assert_kept(tree, rc, out, before, "old: no birth stamp")

    def test_incomplete_walk(
        self,
        tree: ScratchTree,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The classification stopped at its inode cap: nothing unread is judged."""
        entry = _due_entry(tree)
        for index in range(12):
            _write(entry / f"f{index}.txt", b"x", time.time())
        _old(entry)
        before = _inodes(_scratch(tree))
        monkeypatch.setattr(cli, "SCRATCH_SWEEP_DEFAULT_MAX_INODES", 4)

        rc, out = _run(tree, capsys)

        _assert_kept(tree, rc, out, before, "inode cap of 4 reached")
