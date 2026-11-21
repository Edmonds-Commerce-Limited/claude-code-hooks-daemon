"""``scratch-sweep`` across registered worktrees (Plan 00627 Task 6.1), and pressure.

A dry run from the main checkout also reports every other registered
worktree's ``untracked/scratch`` root (DESIGN.md section 11). ``--apply``
acts only on the root of the checkout it runs in: from a linked worktree it
packs that worktree's entries into the MAIN checkout's archive store, and from
the main checkout it never touches a linked worktree's tree. ``_scratch_pressure``
is tested directly against an inventory written by the real writer.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from tests.support.scratch_tree import ScratchTree, build_git_project, git

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.scratch_archive_apply import Pressure
from claude_code_hooks_daemon.core.untracked_roots import resolve_sweep_root
from claude_code_hooks_daemon.daemon.cli import (
    SCRATCH_SWEEP_DEFAULT_MAX_INODES,
    SCRATCH_SWEEP_DEFAULT_SECONDS,
    _record_scratch_inventory,
    _scratch_pressure,
    _ScratchSources,
    build_parser,
)

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


def _linked(tree: ScratchTree, now: float) -> Path:
    linked = tree.base / "linked"
    git(_project(tree), "worktree", "add", "-q", "-b", "side", str(linked))
    (linked / ".claude" / "hooks-daemon").mkdir(parents=True, exist_ok=True)
    scratch = linked / "untracked" / "scratch"
    scratch.mkdir(parents=True)
    lone = scratch / "lone.log"
    lone.write_text("x")
    os.utime(lone, (now - 5 * _DAY, now - 5 * _DAY))
    return linked


def _run(project: Path, *argv: str, now: float) -> int:
    args = build_parser().parse_args(["scratch-sweep", *argv])
    args.project_root = project
    return int(
        args.func(
            args,
            wall_clock=lambda: now,
            process_cwds=lambda: {1: Path("/elsewhere")},
            confirm_apply=lambda _root: True,
        )
    )


def _sources(project: Path, config: Config, now: float) -> _ScratchSources:
    return _ScratchSources(
        repo=project,
        config=config,
        budget_seconds=SCRATCH_SWEEP_DEFAULT_SECONDS,
        max_inodes=SCRATCH_SWEEP_DEFAULT_MAX_INODES,
        scandir=os.scandir,
        wall_clock=lambda: now,
        budget_clock=time.monotonic,
        process_cwds=lambda: {1: Path("/elsewhere")},
        git_runner=None,
    )


def _classify(sources: _ScratchSources) -> Any:
    root = resolve_sweep_root(
        sources.repo / "untracked" / "scratch",
        project_root=sources.repo,
        config=sources.config.scratch,
        reference_roots=(),
    )
    return sources.classify(root)


def _config_with_entry_caps(warn: int, block: int) -> Config:
    config = Config()
    entries = config.scratch.caps.entries.model_copy(update={"warn": warn, "block": block})
    caps = config.scratch.caps.model_copy(update={"entries": entries})
    scratch = config.scratch.model_copy(update={"caps": caps})
    return config.model_copy(update={"scratch": scratch})


class TestScratchPressure:
    def test_no_inventory_gives_no_pressure(self, tree: ScratchTree) -> None:
        sources = _sources(_project(tree), _config_with_entry_caps(1, 2), time.time())
        assert _scratch_pressure(sources, 24.0) is None

    def test_an_inventory_at_block_gives_pressure(self, tree: ScratchTree) -> None:
        for name in ("a", "b", "c"):
            tree.file(f"{name}/f.txt", b"x")
        sources = _sources(_project(tree), _config_with_entry_caps(1, 2), time.time())
        _record_scratch_inventory(sources, _classify(sources))
        pressure = _scratch_pressure(sources, 24.0)
        assert isinstance(pressure, Pressure)
        assert pressure.ttl_hours == 24.0
        assert _scratch_pressure(sources, None) is None

    def test_an_inventory_below_block_gives_no_pressure(self, tree: ScratchTree) -> None:
        tree.file("a/f.txt", b"x")
        sources = _sources(_project(tree), _config_with_entry_caps(100, 200), time.time())
        _record_scratch_inventory(sources, _classify(sources))
        assert _scratch_pressure(sources, 24.0) is None


class TestDryRunReportsEveryWorktree:
    def test_the_main_dry_run_lists_a_linked_root(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        linked = _linked(tree, now)
        assert _run(_project(tree), now=now) == 0
        out = capsys.readouterr().out
        assert str(linked / "untracked" / "scratch") in out
        assert "lone.log" in out
        assert not _store(_project(tree)).exists()
        assert (linked / "untracked" / "scratch" / "lone.log").exists()

    def test_the_json_dry_run_carries_the_worktree_reports(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        linked = _linked(tree, now)
        assert _run(_project(tree), "--json", now=now) == 0
        document = json.loads(capsys.readouterr().out)
        (report,) = document["worktrees"]
        assert report["root"] == str(linked / "untracked" / "scratch")
        assert [row["name"] for row in report["entries"]] == ["lone.log"]

    def test_a_worktree_without_a_scratch_root_is_skipped(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        linked = tree.base / "bare-linked"
        git(_project(tree), "worktree", "add", "-q", "-b", "bare", str(linked))
        assert _run(_project(tree), "--json", now=time.time()) == 0
        assert json.loads(capsys.readouterr().out)["worktrees"] == []
        assert not (linked / "untracked" / "scratch").exists()


class TestApplyIsLimitedToItsOwnCheckout:
    def test_apply_in_a_linked_worktree_packs_into_the_main_store(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        linked = _linked(tree, now)
        assert _run(linked, "--apply", now=now) == 0, capsys.readouterr().err
        assert not (linked / "untracked" / "scratch" / "lone.log").exists()
        assert not _store(linked).exists()
        index = (_store(_project(tree)) / "index.jsonl").read_text()
        assert str(linked.resolve()) in index

    def test_apply_in_the_main_checkout_leaves_a_linked_root_alone(self, tree: ScratchTree) -> None:
        now = time.time() + 3 * _DAY
        linked = _linked(tree, now)
        tree.file("mine/f.txt", b"x")
        tree.set_tree_mtime("mine", now - 5 * _DAY)
        assert _run(_project(tree), "--apply", now=now) == 0
        assert (linked / "untracked" / "scratch" / "lone.log").exists()
        assert not (_project(tree) / "untracked" / "scratch" / "mine").exists()

    def test_apply_with_a_root_in_another_worktree_is_refused(self, tree: ScratchTree) -> None:
        now = time.time() + 3 * _DAY
        linked = _linked(tree, now)
        root = str(linked / "untracked" / "scratch")
        assert _run(_project(tree), "--apply", "--root", root, now=now) == 1
        assert (linked / "untracked" / "scratch" / "lone.log").exists()
        assert not _store(_project(tree)).exists()

    @pytest.mark.parametrize("action", [("restore", "x"), ("keep", "x", "--reason", "r")])
    def test_restore_and_keep_stay_main_checkout_only(
        self, tree: ScratchTree, action: tuple[str, ...]
    ) -> None:
        now = time.time()
        linked = _linked(tree, now)
        assert _run(linked, *action, now=now) == 1
        assert not _store(linked).exists()
        assert not _store(_project(tree)).exists()
