"""`hooks-daemon scratch-sweep`, the Phase 1 dry run (Plan 00627 Task 1.7).

The verdicts and report shape are pinned in ``tests/unit/core/test_scratch_sweep.py``;
these tests cover the verb: argument parsing, exit codes, the default root, and
that a run changes no inode anywhere under the test base.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import pytest
from tests.support.scratch_tree import ScratchTree, build_git_project, git

from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_scratch_sweep

_DAY = 86400.0


@pytest.fixture
def tree(tmp_path: Path) -> ScratchTree:
    tree = build_git_project(tmp_path).tree
    (tmp_path / "project" / ".claude" / "hooks-daemon").mkdir(parents=True)
    return tree


def _args(
    tree: ScratchTree,
    *,
    as_json: bool = False,
    root: Path | None = None,
    budget_seconds: float = 60.0,
    max_inodes: int = 100_000,
) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=tree.base / "project",
        json=as_json,
        root=root,
        budget_seconds=budget_seconds,
        max_inodes=max_inodes,
    )


def _run(
    tree: ScratchTree,
    args: argparse.Namespace,
    *,
    refused: tuple[str, ...] = (),
    now: float | None = None,
) -> int:
    clock_now = time.time() + 3 * _DAY if now is None else now
    return cmd_scratch_sweep(
        args,
        scandir=tree.refusing_scandir(*refused),
        wall_clock=lambda: clock_now,
        process_cwds=lambda: {1: Path("/elsewhere")},
    )


def _populate(tree: ScratchTree) -> None:
    tree.file("commit-a.txt", b"m")
    tree.file("notes/n.txt", b"n")
    tree.symlink("notes/escape", tree.outside_dummy("dummy.txt"))
    tree.fifo("pipe-entry")
    tree.file("locked/inner/x.txt", b"x")
    tree.git_marker("clone")
    # A real clone of the project with a stat-dirty tracked file: a plain
    # ``git status`` would rewrite its index (the inode test below would fail).
    real = tree.root / "realclone"
    git(tree.root, "clone", "-q", f"file://{tree.base / 'remote.git'}", str(real))
    os.utime(real / "src" / "app.py", (1_000_000, 1_000_000))
    tree.set_tree_mtime("realclone", time.time() - 2 * _DAY)


class TestParser:
    def test_defaults(self) -> None:
        args = build_parser().parse_args(["scratch-sweep"])
        assert args.json is False
        assert args.root is None
        assert args.budget_seconds > 0
        assert args.max_inodes > 0
        assert args.func is cmd_scratch_sweep

    def test_flags(self) -> None:
        args = build_parser().parse_args(
            ["scratch-sweep", "--json", "--root", "x", "--budget-seconds", "5", "--max-inodes", "9"]
        )
        assert (args.json, args.root, args.budget_seconds, args.max_inodes) == (
            True,
            Path("x"),
            5.0,
            9,
        )

    @pytest.mark.parametrize("flag", ["--budget-seconds", "--max-inodes"])
    def test_a_non_positive_budget_is_refused(self, flag: str) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["scratch-sweep", flag, "0"])

    def test_there_is_no_apply_flag_yet(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["scratch-sweep", "--apply"])


class TestReadOnly:
    @pytest.mark.parametrize("as_json", [False, True])
    def test_a_run_changes_no_inode(
        self, tree: ScratchTree, as_json: bool, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _populate(tree)
        before = tree.snapshot()
        code = _run(tree, _args(tree, as_json=as_json), refused=("locked/inner",))
        assert code == 0
        assert tree.snapshot() == before
        assert (tree.outside / "dummy.txt").read_bytes() == b"dummy"
        out = capsys.readouterr().out
        if as_json:
            document = json.loads(out)
            assert document["complete"] is False
            verdicts = {row["name"]: row["verdict"] for row in document["entries"]}
            assert verdicts["locked"] == "STUCK"
            assert verdicts["clone"] == "STUCK"
            reasons = {row["name"]: row["reasons"] for row in document["entries"]}
            # The unwalked ``locked`` entry leaves cross-entry dependencies unknown,
            # which turns a DISPOSABLE row STUCK (F-BYPS 2); the clone itself was judged.
            realclone = (verdicts["realclone"], reasons["realclone"][:1])
            assert realclone[0] in {"PROTECTED", "UNCERTAIN"} or (
                realclone[0] == "STUCK" and "other entries depend on" in realclone[1][0]
            ), reasons
        else:
            assert "INCOMPLETE" in out
        assert "dummy" not in out.replace("dummy.txt", "")

    def test_a_missing_default_root_is_not_created(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tree.root.rmdir()
        before = tree.snapshot()
        assert _run(tree, _args(tree)) == 0
        assert tree.snapshot() == before
        assert "does not exist" in capsys.readouterr().out


class TestOutput:
    def test_the_default_root_is_the_project_scratch(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tree.file("a.log", b"x", mtime=time.time() - 2 * _DAY)
        assert _run(tree, _args(tree, as_json=True)) == 0
        document = json.loads(capsys.readouterr().out)
        assert Path(document["root"]) == tree.root
        assert [row["name"] for row in document["entries"]] == ["a.log"]

    def test_the_configured_plan_directory_reaches_the_filing_proposal(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = tree.base / "project" / ".claude" / "hooks-daemon.yaml"
        config.write_text('version: "2.0"\nplan_workflow:\n  directory: plans\n')
        plan = tree.base / "project" / "plans" / "00627-x"
        plan.mkdir(parents=True)
        (plan / "PLAN.md").write_text("# Plan: x\n")
        tree.file("00627-r.md", b"prose\n", mtime=time.time() - 2 * _DAY)
        assert _run(tree, _args(tree, as_json=True)) == 0
        row = json.loads(capsys.readouterr().out)["entries"][0]
        assert row["filing_destination"] == "plans/00627-x/subagent-reports/"
        assert row["filing_command"].startswith("mv -n -- untracked/scratch/00627-r.md ")
        assert (tree.root / "00627-r.md").exists()

    def test_an_explicit_root_outside_untracked_is_refused(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        other = tree.base / "other"
        other.mkdir()
        (other / "f.out").write_text("x")
        assert _run(tree, _args(tree, as_json=True, root=other)) == 0
        document = json.loads(capsys.readouterr().out)
        assert document["entries"] == []
        assert any("never swept" in reason for reason in document["incomplete_reasons"])

    def test_an_explicit_untracked_root_with_a_ttl(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = tree.base / "project" / ".claude" / "hooks-daemon.yaml"
        config.write_text('version: "2.0"\nscratch:\n  untracked_ttl:\n    briefs: 1h\n')
        briefs = tree.base / "project" / "untracked" / "briefs"
        briefs.mkdir()
        (briefs / "f.out").write_text("x")
        assert _run(tree, _args(tree, as_json=True, root=briefs)) == 0
        document = json.loads(capsys.readouterr().out)
        assert [row["name"] for row in document["entries"]] == ["f.out"]

    def test_the_reference_repositories_root_is_refused(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repos = tree.base / "project" / "untracked" / "repos" / "alpha"
        repos.mkdir(parents=True)
        (repos / "notes.log").write_text("x")
        assert _run(tree, _args(tree, as_json=True, root=Path("untracked/repos"))) == 0
        document = json.loads(capsys.readouterr().out)
        assert document["entries"] == []
        assert document["complete"] is False
        assert any("never swept" in reason for reason in document["incomplete_reasons"])

    def test_a_relative_root_is_taken_from_the_project(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tree.file("a.log")
        assert _run(tree, _args(tree, as_json=True, root=Path("untracked/scratch"))) == 0
        document = json.loads(capsys.readouterr().out)
        assert Path(document["root"]) == tree.root

    def test_the_budget_flags_reach_the_walk(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tree.file("a/b/c.txt", mtime=time.time() - 2 * _DAY)
        tree.set_tree_mtime("a", time.time() - 2 * _DAY)
        assert _run(tree, _args(tree, as_json=True, max_inodes=1)) == 0
        document = json.loads(capsys.readouterr().out)
        assert document["complete"] is False
        assert any("inode cap of 1" in reason for reason in document["incomplete_reasons"])

    def test_a_malformed_background_record_makes_entries_live(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tree.file("a.log", b"x")
        tree.set_tree_mtime("a.log", time.time() - 2 * _DAY)
        untracked = tree.base / "project" / ".claude" / "hooks-daemon" / "untracked"
        untracked.mkdir()
        (untracked / "background-processes.jsonl").write_text("not json\n")
        assert _run(tree, _args(tree, as_json=True)) == 0
        (row,) = json.loads(capsys.readouterr().out)["entries"]
        assert row["verdict"] == "LIVE"
