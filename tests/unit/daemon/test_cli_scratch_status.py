"""``scratch-sweep status`` through the CLI (Plan 00627 Task 3.10).

Read-only: no store is created, nothing under ``untracked/`` changes, and a
linked worktree reads the main checkout's store (the only one there is).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest
from tests.support.scratch_tree import ScratchTree, build_git_project, git

from claude_code_hooks_daemon.daemon.cli import build_parser

_DAY = 86400.0


@pytest.fixture
def tree(tmp_path: Path) -> ScratchTree:
    tree = build_git_project(tmp_path).tree
    (tmp_path / "project" / ".claude" / "hooks-daemon").mkdir(parents=True)
    return tree


def _project(tree: ScratchTree) -> Path:
    return tree.base / "project"


def _store(project: Path) -> Path:
    return project / "untracked" / "scratch-archive"


def _parse(project: Path, *argv: str) -> argparse.Namespace:
    args = build_parser().parse_args(["scratch-sweep", *argv])
    args.project_root = project
    return args


def _run(args: argparse.Namespace, *, now: float) -> int:
    return int(
        args.func(
            args,
            wall_clock=lambda: now,
            process_cwds=lambda: {1: Path("/elsewhere")},
            confirm_apply=lambda _root, _notice: True,
        )
    )


def _snapshot(project: Path) -> list[tuple[str, int, int]]:
    found = []
    for dirpath, dirnames, filenames in os.walk(project / "untracked"):
        for name in sorted(dirnames + filenames):
            info = (Path(dirpath) / name).lstat()
            found.append((str(Path(dirpath) / name), info.st_ino, info.st_mtime_ns))
    return sorted(found)


def _archived(tree: ScratchTree, capsys: pytest.CaptureFixture[str], now: float) -> str:
    tree.file("old/a.txt", b"alpha")
    tree.set_tree_mtime("old", now - 5 * _DAY)
    assert _run(_parse(_project(tree), "--apply", "--json"), now=now) == 0
    document = json.loads(capsys.readouterr().out)
    (outcome,) = [row for row in document["entries"] if row["name"] == "old"]
    return str(outcome["archive_id"])


class TestStatus:
    def test_it_is_a_subcommand_with_only_json(self) -> None:
        args = build_parser().parse_args(["scratch-sweep", "status", "--json"])
        assert args.scratch_action == "status"
        assert args.status_json is True

    def test_no_store_is_reported_and_not_created(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _project(tree)
        assert _run(_parse(project, "status"), now=time.time()) == 0
        assert "no archive store" in capsys.readouterr().out
        assert not _store(project).exists()

    def test_lists_a_live_archive_and_changes_nothing(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        archive_id = _archived(tree, capsys, now)
        project = _project(tree)
        before = _snapshot(project)
        assert _run(_parse(project, "status"), now=now) == 0
        out = capsys.readouterr().out
        assert archive_id in out
        assert "untracked/scratch/old" in out
        assert _snapshot(project) == before

    def test_json_carries_the_effective_expiry_with_keeps(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        archive_id = _archived(tree, capsys, now)
        project = _project(tree)
        later = now + _DAY
        keep = ("keep", archive_id, "--reason", "need it", "--hours", "150")
        assert _run(_parse(project, *keep), now=later) == 0
        capsys.readouterr()
        assert _run(_parse(project, "status", "--json"), now=later) == 0
        (row,) = json.loads(capsys.readouterr().out)["archives"]
        assert row["archive_id"] == archive_id
        assert row["keeps"] == 1
        assert row["expires"] is not None
        expected = later + 150 * 3600
        assert abs(_epoch(row["expires"]) - expected) < 2

    def test_a_linked_worktree_reads_the_main_store(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        archive_id = _archived(tree, capsys, now)
        linked = tree.base / "linked"
        git(_project(tree), "worktree", "add", "-q", "-b", "side", str(linked))
        (linked / ".claude" / "hooks-daemon").mkdir(parents=True, exist_ok=True)
        assert _run(_parse(linked, "status"), now=now) == 0
        assert archive_id in capsys.readouterr().out
        assert not _store(linked).exists()


def _epoch(text: str) -> float:
    return datetime.fromisoformat(text).timestamp()


class TestStoreStatusForTheInventory:
    def test_an_absent_store_is_an_empty_status_not_none(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core.scratch_store_view import StoreStatus
        from claude_code_hooks_daemon.daemon.cli import _scratch_store_status

        status = _scratch_store_status(tmp_path / "no-store", {})
        assert status == StoreStatus(archives=(), torn=False)
        assert not (tmp_path / "no-store").exists()
