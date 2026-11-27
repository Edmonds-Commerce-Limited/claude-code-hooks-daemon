"""``housekeeping --run scratch-sweep-apply``: the unconfirmed scratch apply (Plan 00627 R13).

The owner ruled that expired scratch may be cleaned without a confirmation
each time (Plan 00474 ledger). The housekeeping step therefore runs the SAME
apply core as ``scratch-sweep --apply`` -- the same classification, pressure
rules, hold window and archive store -- with no terminal question, and acts
only on what that core finds due. The ``scratch-sweep --apply`` verb keeps its
terminal gate: the unconfirmed path is this step alone.

Everything runs through the real parser, the real sweep on a real git project,
the real store and GNU tar (the fixtures of ``test_cli_scratch_apply.py``).
"""

from __future__ import annotations

import argparse
import io
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support.scratch_tree import ScratchTree, build_git_project

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.cli import (
    build_parser,
    cmd_housekeeping,
    cmd_scratch_sweep,
    run_scratch_sweep_apply_step,
)

_DAY = 86400.0
_HOUR = 3600.0
_SESSION = "s-20261101T000000Z-abcdefgh"
_ARCHIVE_LINE = re.compile(r"^\s+- (?P<path>\S+) archive (?P<id>\S+)$", re.MULTILINE)


class _Stream(io.StringIO):
    def __init__(self, text: str = "", *, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScratchTree:
    tree = build_git_project(tmp_path).tree
    (tmp_path / "project" / ".claude" / "hooks-daemon").mkdir(parents=True)
    # No terminal anywhere: the step must act without one.
    monkeypatch.setattr("sys.stdin", _Stream("", tty=False))
    return tree


def _project(tree: ScratchTree) -> Path:
    return tree.base / "project"


def _store(project: Path) -> Path:
    return project / "untracked" / "scratch-archive"


def _step(
    tree: ScratchTree,
    *,
    now: float,
    cwds: Callable[[], dict[int, Path]] | None = None,
    scandir: Callable[[str], Any] = os.scandir,
) -> int:
    return run_scratch_sweep_apply_step(
        _project(tree),
        scandir=scandir,
        wall_clock=lambda: now,
        process_cwds=cwds or (lambda: {1: Path("/elsewhere")}),
    )


def _due(tree: ScratchTree, rel: str, now: float) -> None:
    tree.file(f"{rel}/a.txt", b"alpha")
    tree.set_tree_mtime(rel, now - 5 * _DAY)


def _archived(out: str) -> dict[str, str]:
    return {match["path"]: match["id"] for match in _ARCHIVE_LINE.finditer(out)}


class TestTheStepActsWithoutATerminal:
    def test_a_due_entry_is_archived_and_removed(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due(tree, "old", now)
        assert _step(tree, now=now) == 0
        out = capsys.readouterr().out
        assert not (tree.root / "old").exists()
        assert _store(_project(tree)).is_dir()
        assert "removed 1 entry" in out
        assert "untracked/scratch/old" in _archived(out)
        # Names, never contents.
        assert "alpha" not in out

    def test_a_removed_entry_restores(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due(tree, "old", now)
        assert _step(tree, now=now) == 0
        archive_id = _archived(capsys.readouterr().out)["untracked/scratch/old"]
        args = build_parser().parse_args(["scratch-sweep", "restore", archive_id])
        args.project_root = _project(tree)
        assert (
            cmd_scratch_sweep(args, wall_clock=lambda: now, process_cwds=lambda: {1: Path("/x")})
            == 0
        )
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"

    def test_nothing_due_removes_nothing_and_says_so(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time()
        tree.file("fresh/a.txt", b"alpha", mtime=now - _HOUR)
        assert _step(tree, now=now) == 0
        assert (tree.root / "fresh" / "a.txt").read_bytes() == b"alpha"
        assert "removed 0 entries" in capsys.readouterr().out


class TestTheStepNeverTouchesWhatTheSweepProtects:
    def test_a_scratch_keep_entry_is_never_removed(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        tree.file("pinned/a.txt", b"alpha")
        tree.file("pinned/.scratch-keep", b"hold\n")
        tree.set_tree_mtime("pinned", now - 5 * _DAY)
        assert _step(tree, now=now) == 0
        assert (tree.root / "pinned" / "a.txt").read_bytes() == b"alpha"
        assert "untracked/scratch/pinned" not in _archived(capsys.readouterr().out)

    def test_a_kept_child_of_a_session_is_never_removed(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        tree.file(f"{_SESSION}/old/a.txt", b"alpha")
        tree.file(f"{_SESSION}/kept/a.txt", b"kept")
        tree.file(f"{_SESSION}/kept/.scratch-keep", b"hold\n")
        tree.set_tree_mtime(_SESSION, now - 5 * _DAY)
        assert _step(tree, now=now) == 0
        archived = _archived(capsys.readouterr().out)
        assert f"untracked/scratch/{_SESSION}/old" in archived
        assert (tree.root / _SESSION / "kept" / "a.txt").read_bytes() == b"kept"

    def test_a_live_session_directory_is_never_removed(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due(tree, f"{_SESSION}/old", now)
        held = tree.root.resolve() / _SESSION
        assert _step(tree, now=now, cwds=lambda: {4: held}) == 0
        assert (tree.root / _SESSION / "old" / "a.txt").read_bytes() == b"alpha"
        assert _archived(capsys.readouterr().out) == {}

    def test_an_entry_inside_its_ttl_is_never_removed(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Three days ahead so the files' real birth time is past the TTL too.
        now = time.time() + 3 * _DAY
        tree.file("young/a.txt", b"alpha", mtime=now - _HOUR)
        _due(tree, "old", now)
        assert _step(tree, now=now) == 0
        archived = _archived(capsys.readouterr().out)
        assert set(archived) == {"untracked/scratch/old"}
        assert (tree.root / "young" / "a.txt").read_bytes() == b"alpha"


class TestTheStepFailsClosed:
    def test_a_store_refusal_removes_nothing(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due(tree, "old", now)
        project = _project(tree)
        (project / ".claude" / "hooks-daemon.yaml").write_text(
            'version: "2.0"\nscratch:\n  untracked_ttl:\n    scratch: "7 days"\n'
        )
        assert _step(tree, now=now) == 1
        assert not _store(project).exists()
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"
        err = capsys.readouterr().err
        assert "refused" in err
        assert "nothing was removed" in err

    def test_an_unreadable_directory_removes_nothing(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due(tree, "old", now)
        _due(tree, "locked", now)
        assert _step(tree, now=now, scandir=tree.refusing_scandir("locked")) == 1
        assert not _store(_project(tree)).exists()
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"
        err = capsys.readouterr().err
        assert "incomplete" in err
        assert "nothing was removed" in err


class TestTheCliVerbKeepsItsGate:
    def test_scratch_sweep_apply_still_refuses_without_a_terminal(self, tree: ScratchTree) -> None:
        now = time.time() + 3 * _DAY
        _due(tree, "old", now)
        args = build_parser().parse_args(["scratch-sweep", "--apply"])
        args.project_root = _project(tree)
        code = cmd_scratch_sweep(
            args, wall_clock=lambda: now, process_cwds=lambda: {1: Path("/elsewhere")}
        )
        assert code == 1
        assert not _store(_project(tree)).exists()
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"

    def test_the_scratch_sweep_verb_gained_no_unconfirmed_flag(self) -> None:
        args = build_parser().parse_args(["scratch-sweep", "--apply"])
        assert not any(key in {"run", "unconfirmed", "yes"} for key in vars(args))


def _housekeeping_args(root: Path, *argv: str) -> argparse.Namespace:
    args = build_parser().parse_args(["housekeeping", *argv])
    args.project_root = str(root)
    return args


class TestTheHousekeepingRunFlag:
    def test_run_dispatches_the_step_for_this_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Path] = []

        def fake(repo: Path) -> int:
            seen.append(repo)
            return 0

        monkeypatch.setattr(cli, "run_scratch_sweep_apply_step", fake)
        args = _housekeeping_args(tmp_path, "--run", "scratch-sweep-apply")
        assert cmd_housekeeping(args) == 0
        assert seen == [tmp_path]

    def test_run_refuses_a_step_it_cannot_run_in_process(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = _housekeeping_args(tmp_path, "--run", "prune-venvs")
        assert cmd_housekeeping(args) == 2
        assert "scratch-sweep-apply" in capsys.readouterr().err
