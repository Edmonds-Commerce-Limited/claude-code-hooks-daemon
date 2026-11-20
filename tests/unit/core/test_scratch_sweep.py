"""The read-only scratch sweep report (Plan 00627 Task 1.7)."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path

from claude_code_hooks_daemon.config.models import ScratchConfig
from claude_code_hooks_daemon.core.scratch_liveness import BackgroundRecords, LivenessInputs
from claude_code_hooks_daemon.core.scratch_sweep import (
    SweepReport,
    render_table,
    report_json,
    run_sweep,
)
from claude_code_hooks_daemon.core.scratch_walk import WalkBudget
from claude_code_hooks_daemon.core.untracked_roots import resolve_sweep_root
from tests.support.scratch_tree import ScratchTree, build_scratch_tree

_DAY = 86400.0


def _now() -> float:
    # ctime cannot be set, so the injected clock sits well past the real ctimes.
    return time.time() + 3 * _DAY


def _sweep(
    tree: ScratchTree,
    *,
    now: float,
    cwds: dict[int, Path] | None = None,
    budget: WalkBudget | None = None,
    error: str = "",
    refused: tuple[str, ...] = (),
    config: ScratchConfig | None = None,
    root: Path | None = None,
    reference_roots: tuple[str, ...] = ("untracked/repos",),
) -> SweepReport:
    inputs = LivenessInputs(
        cwds={1: Path("/elsewhere")} if cwds is None else cwds,
        background=BackgroundRecords((), error),
        min_age_minutes=30,
        now=now,
    )
    config = config or ScratchConfig()
    return run_sweep(
        resolve_sweep_root(
            root or tree.root,
            project_root=tree.base / "project",
            config=config,
            reference_roots=reference_roots,
        ),
        config=config,
        now=now,
        budget=budget or WalkBudget(seconds=60, max_inodes=10_000),
        inputs=inputs,
        project_root=tree.base / "project",
        scandir=tree.refusing_scandir(*refused),
    )


def _verdicts(report: SweepReport) -> dict[str, str]:
    return {row.name: row.verdict.value for row in report.rows}


def _old(tree: ScratchTree, now: float) -> None:
    for path in tree.root.iterdir():
        tree.set_tree_mtime(path.name, now - 2 * _DAY)


class TestSweepRoot:
    """DESIGN.md section 4.1: the root's TTL, and roots that are never swept."""

    def test_a_refused_root_is_never_listed(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        repos = tree.base / "project" / "untracked" / "repos"
        (repos / "alpha").mkdir(parents=True)
        listed: list[str] = []
        real = tree.refusing_scandir()

        def spy(path: str) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
            listed.append(path)
            return real(path)

        config = ScratchConfig.model_validate({"untracked_ttl": {"repos": "1h"}})
        report = run_sweep(
            resolve_sweep_root(
                repos, project_root=tree.base / "project", config=config, reference_roots=()
            ),
            config=config,
            now=_now(),
            budget=WalkBudget(seconds=60, max_inodes=10_000),
            inputs=LivenessInputs(
                cwds={1: Path("/elsewhere")},
                background=BackgroundRecords((), ""),
                min_age_minutes=30,
                now=_now(),
            ),
            project_root=tree.base / "project",
            scandir=spy,
        )
        assert listed == []
        assert report.rows == ()
        assert not report.complete
        assert any("never swept" in reason for reason in report.incomplete_reasons)

    def test_an_entry_holding_a_reference_root_is_not_judged(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        tree.file("kept/inner/a.txt")
        tree.file("notes.txt")
        _old(tree, now)
        report = _sweep(
            tree, now=now, reference_roots=("untracked/repos", "untracked/scratch/kept/inner")
        )
        assert _verdicts(report) == {"notes.txt": "UNCERTAIN"}
        assert any("kept" in note for note in report.notes)

    def test_the_root_ttl_decides_due(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        tree.file("notes.txt")
        _old(tree, now)
        config = ScratchConfig.model_validate({"untracked_ttl": {"scratch": "7d"}})
        assert _verdicts(_sweep(tree, now=now, config=config)) == {"notes.txt": "LIVE"}


class TestRunSweep:
    def test_each_entry_gets_one_verdict(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        tree.file("commit-a.txt", b"msg")
        tree.file("notes.txt", b"keep?")
        tree.file("cache/__pycache__/m.pyc", b"pyc")
        tree.git_marker("clone")
        tree.file(".gitignore", b"*\n")
        _old(tree, now)
        report = _sweep(tree, now=now)
        assert _verdicts(report) == {
            "cache": "DISPOSABLE",
            "clone": "REPOSITORY",
            "commit-a.txt": "DISPOSABLE",
            "notes.txt": "UNCERTAIN",
        }
        assert report.complete

    def test_a_refused_directory_makes_the_entry_stuck_and_the_report_incomplete(
        self, tmp_path: Path
    ) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        tree.file("box/inner/a.txt")
        _old(tree, now)
        report = _sweep(tree, now=now, refused=("box/inner",))
        assert _verdicts(report) == {"box": "STUCK"}
        assert not report.complete
        assert any("1 entry" in reason for reason in report.incomplete_reasons)

    def test_a_spent_budget_still_lists_every_entry(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        for name in ("a", "b", "c"):
            tree.file(f"{name}/x/y.txt")
        _old(tree, now)
        report = _sweep(tree, now=now, budget=WalkBudget(seconds=60, max_inodes=3))
        assert sorted(_verdicts(report)) == ["a", "b", "c"]
        assert "STUCK" in _verdicts(report).values()
        assert any("inode cap" in reason for reason in report.incomplete_reasons)

    def test_a_missing_root_is_reported_and_not_created(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        tree.root.rmdir()
        report = _sweep(tree, now=_now())
        assert report.rows == ()
        assert report.complete
        assert any("does not exist" in note for note in report.notes)
        assert not tree.root.exists()

    def test_an_unlistable_root_is_incomplete_never_empty_and_clean(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        report = _sweep(tree, now=_now(), refused=("",))
        assert not report.complete
        assert report.incomplete_reasons

    def test_a_root_that_is_a_file_is_incomplete(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        tree.root.rmdir()
        tree.root.write_text("x")
        report = _sweep(tree, now=_now())
        assert not report.complete
        assert "not a directory" in report.incomplete_reasons[0]

    def test_a_root_that_cannot_be_read_is_incomplete(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        blocker = tree.file("plain.txt")
        report = _sweep(tree, now=_now(), root=blocker / "below")
        assert not report.complete
        assert "could not be read" in report.incomplete_reasons[0]

    def test_a_root_that_is_a_link_is_not_followed(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        tree.root.rmdir()
        tree.root.symlink_to(tree.outside)
        tree.outside_dummy("secret.txt")
        report = _sweep(tree, now=_now())
        assert report.rows == ()
        assert not report.complete

    def test_an_entry_a_process_sits_in_is_live(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        tree.file("work/a.txt")
        _old(tree, now)
        report = _sweep(tree, now=now, cwds={9: (tree.root / "work").resolve()})
        assert _verdicts(report) == {"work": "LIVE"}

    def test_an_empty_cwd_map_is_noted(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        report = _sweep(tree, now=_now(), cwds={})
        assert any("working director" in note for note in report.notes)

    def test_the_repository_marker_is_carried_on_a_live_row(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        tree.git_marker("fresh")
        report = _sweep(tree, now=time.time())
        (row,) = report.rows
        assert row.verdict.value == "LIVE"
        assert row.repository.value == "found"

    def test_the_no_birth_note_is_reported_once(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        tree.file("a.txt")
        tree.file("b.txt")
        report = _sweep(tree, now=_now())
        assert sum("birth" in note for note in report.notes) == 1


class TestRendering:
    def _report(self, tmp_path: Path) -> SweepReport:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        tree.file("notes.txt")
        tree.file("a.log")
        tree.git_marker("clone")
        _old(tree, now)
        return _sweep(tree, now=now)

    def test_the_table_states_dry_run_counts_and_unevaluated_rungs(self, tmp_path: Path) -> None:
        text = "\n".join(render_table(self._report(tmp_path), max_listed=50))
        assert "nothing was changed" in text
        assert "DISPOSABLE 1" in text
        assert "KEPT, PROTECTED, REFERENCED" in text
        assert "repository, not judged" in text

    def test_the_table_suggests_no_removal(self, tmp_path: Path) -> None:
        text = "\n".join(render_table(self._report(tmp_path), max_listed=50)).lower()
        for word in ("rm ", "delete", "--apply"):
            assert word not in text

    def test_the_table_is_bounded_by_max_listed(self, tmp_path: Path) -> None:
        text = "\n".join(render_table(self._report(tmp_path), max_listed=1))
        assert "2 more" in text

    def test_an_incomplete_report_says_so_first(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        lines = render_table(_sweep(tree, now=_now(), refused=("",)), max_listed=50)
        assert lines[1].startswith("INCOMPLETE")

    def test_a_control_character_in_a_name_is_escaped(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        tree.file("bad\nname.txt")
        text = "\n".join(render_table(_sweep(tree, now=_now()), max_listed=50))
        assert "bad\\x0aname.txt" in text

    def test_json_carries_every_row_and_field(self, tmp_path: Path) -> None:
        document = report_json(self._report(tmp_path))
        json.dumps(document)
        assert document["dry_run"] is True
        assert document["not_evaluated"] == ["KEPT", "PROTECTED", "REFERENCED"]
        rows = {row["name"]: row for row in document["entries"]}
        assert set(rows) == {"a.log", "clone", "notes.txt"}
        assert rows["clone"]["repository"] == "found"
        assert rows["a.log"]["proofs"] == ["P1"]
        assert rows["notes.txt"]["uncovered"] == ["notes.txt"]
