"""The read-only scratch sweep report (Plan 00627 Task 1.7)."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import time
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import ScratchConfig
from claude_code_hooks_daemon.core.scratch_liveness import BackgroundRecords, LivenessInputs
from claude_code_hooks_daemon.core.scratch_repos import build_project_git
from claude_code_hooks_daemon.core.scratch_sweep import (
    HashBudget,
    SweepReport,
    render_table,
    report_json,
    run_sweep,
)
from claude_code_hooks_daemon.core.scratch_walk import WalkBudget
from claude_code_hooks_daemon.core.untracked_roots import resolve_sweep_root
from tests.support.scratch_tree import (
    GitProject,
    ScratchTree,
    build_git_project,
    build_scratch_tree,
    commit_file,
    git,
    quiet_project_git,
)

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
        project_git=quiet_project_git(tree.base / "project"),
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
            project_git=quiet_project_git(tree.base / "project"),
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
            "clone": "STUCK",
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
        assert "evaluated in this phase: KEPT" in text
        assert "not a git repository" in text

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
        assert document["not_evaluated"] == ["KEPT"]
        rows = {row["name"]: row for row in document["entries"]}
        assert set(rows) == {"a.log", "clone", "notes.txt"}
        assert rows["clone"]["repository"] == "found"
        assert rows["a.log"]["proofs"] == ["P1"]
        assert rows["notes.txt"]["uncovered"] == ["notes.txt"]


class TestTrackedListing:
    def test_a_failed_tracked_listing_makes_the_report_incomplete(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        tree.file("a.log", b"x")
        _old(tree, _now())
        project = tree.base / "project"
        quiet = quiet_project_git(project)

        def failing(
            cwd: Path, *args: str, timeout: float = 30.0, env: Mapping[str, str] | None = None
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["git", *args], 128, "", "not a repository")

        config = ScratchConfig()
        report = run_sweep(
            resolve_sweep_root(tree.root, project_root=project, config=config, reference_roots=()),
            config=config,
            now=_now(),
            budget=WalkBudget(seconds=60, max_inodes=10_000),
            inputs=LivenessInputs(
                cwds={1: Path("/elsewhere")},
                background=BackgroundRecords((), ""),
                min_age_minutes=30,
                now=_now(),
            ),
            project_root=project,
            project_git=dataclasses.replace(quiet, runner=failing),
        )
        assert not report.complete
        assert any("tracked files" in reason for reason in report.incomplete_reasons)
        assert _verdicts(report) == {"a.log": "STUCK"}


def _git_sweep(gp: GitProject, now: float, **kwargs: Any) -> SweepReport:
    """A sweep of a real git project's scratch root, every entry's TTL past."""
    config = ScratchConfig()
    project_git = build_project_git(gp.project, remote="origin", default_branch="main")
    return run_sweep(
        resolve_sweep_root(
            gp.tree.root,
            project_root=gp.project,
            config=config,
            reference_roots=("untracked/repos",),
        ),
        config=config,
        now=now,
        budget=WalkBudget(seconds=60, max_inodes=10_000),
        inputs=LivenessInputs(
            cwds={1: Path("/elsewhere")},
            background=BackgroundRecords((), ""),
            min_age_minutes=30,
            now=now,
        ),
        project_root=gp.project,
        project_git=project_git,
        **kwargs,
    )


class TestP3IdenticalCopy:
    """DESIGN.md section 3.2 P3 and section 14 (Plan 00627 Task 2.3)."""

    def _sweep(self, gp: GitProject, now: float, **kwargs: Any) -> SweepReport:
        return _git_sweep(gp, now, **kwargs)

    def test_a_copy_of_a_file_on_the_pushed_default_tip_is_disposable(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        now = _now()
        gp.tree.file("copy/app.py", b"print('app')\n")
        _old(gp.tree, now)
        report = self._sweep(gp, now)
        row = report.rows[0]
        assert (row.verdict.value, [p.value for p in row.proofs]) == ("DISPOSABLE", ["P3"])

    def test_a_blob_only_on_an_unpushed_branch_proves_nothing(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        git(gp.project, "checkout", "-q", "-b", "local")
        commit_file(gp.project, "local.txt", "only local\n")
        git(gp.project, "checkout", "-q", "main")
        now = _now()
        gp.tree.file("copy/local.txt", b"only local\n")
        _old(gp.tree, now)
        assert _verdicts(self._sweep(gp, now)) == {"copy": "UNCERTAIN"}

    def test_a_blob_in_history_but_not_on_the_default_tip_proves_nothing(
        self, tmp_path: Path
    ) -> None:
        gp = build_git_project(tmp_path)
        commit_file(gp.project, "src/app.py", "print('v2')\n")
        git(gp.project, "push", "-q", "origin", "main")
        git(gp.project, "fetch", "-q", "origin")
        now = _now()
        gp.tree.file("copy/app.py", b"print('app')\n")
        _old(gp.tree, now)
        assert _verdicts(self._sweep(gp, now)) == {"copy": "UNCERTAIN"}

    def test_a_link_beside_a_copy_leaves_the_entry_uncertain_unhashed(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        now = _now()
        gp.tree.file("copy/app.py", b"print('app')\n")
        (gp.tree.root / "copy" / "link").symlink_to(gp.tree.outside)
        _old(gp.tree, now)
        assert _verdicts(self._sweep(gp, now)) == {"copy": "UNCERTAIN"}

    def test_an_exhausted_hash_budget_leaves_files_uncertain_with_a_note(
        self, tmp_path: Path
    ) -> None:
        gp = build_git_project(tmp_path)
        now = _now()
        gp.tree.file("a/app.py", b"print('app')\n")
        gp.tree.file("b/app.py", b"print('app')\n")
        _old(gp.tree, now)
        report = self._sweep(gp, now, hash_budget=HashBudget(max_files=1, max_bytes=1_000_000))
        assert sorted(_verdicts(report).values()) == ["DISPOSABLE", "UNCERTAIN"]
        assert any("P3" in note for note in report.notes)


class TestReferenced:
    """DESIGN.md section 3.4 at sweep level (Plan 00627 Task 2.4)."""

    def _sweep(self, gp: GitProject, now: float) -> SweepReport:
        return _git_sweep(gp, now)

    def test_referenced_beats_p7_and_p1_and_names_file_and_line(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        commit_file(
            gp.project, "docs/a.md", "x\nsee untracked/scratch/repo and untracked/scratch/a.log\n"
        )
        gp.standalone("repo")
        gp.tree.file("a.log")
        gp.tree.file("other.log")
        now = _now()
        _old(gp.tree, now)
        report = self._sweep(gp, now)
        assert _verdicts(report) == {
            "a.log": "REFERENCED",
            "other.log": "DISPOSABLE",
            "repo": "REFERENCED",
        }
        row = next(row for row in report.rows if row.name == "repo")
        assert row.reasons == ("named by 1 tracked line(s), first HEAD:docs/a.md:2",)
        assert report.complete

    def test_protected_beats_referenced(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        commit_file(gp.project, "docs/a.md", "untracked/scratch/wt\n")
        gp.worktree("wt", "wt-branch")
        now = _now()
        _old(gp.tree, now)
        assert _verdicts(self._sweep(gp, now)) == {"wt": "PROTECTED"}

    def test_unknown_references_make_due_entries_stuck_and_the_report_incomplete(
        self, tmp_path: Path
    ) -> None:
        gp = build_git_project(tmp_path)
        gp.tree.file("a.log")
        now = _now()
        _old(gp.tree, now)
        project_git = build_project_git(gp.project, remote="origin", default_branch="main")
        real = project_git.runner

        def failing_grep(
            cwd: Path, *args: str, timeout: float = 30.0, env: Mapping[str, str] | None = None
        ) -> subprocess.CompletedProcess[str]:
            if "grep" in args:
                return subprocess.CompletedProcess(["git", *args], 128, "", "boom")
            return real(cwd, *args, timeout=timeout, env=env)

        config = ScratchConfig()
        report = run_sweep(
            resolve_sweep_root(
                gp.tree.root, project_root=gp.project, config=config, reference_roots=()
            ),
            config=config,
            now=now,
            budget=WalkBudget(seconds=60, max_inodes=10_000),
            inputs=LivenessInputs(
                cwds={1: Path("/elsewhere")},
                background=BackgroundRecords((), ""),
                min_age_minutes=30,
                now=now,
            ),
            project_root=gp.project,
            project_git=dataclasses.replace(project_git, runner=failing_grep),
        )
        assert _verdicts(report) == {"a.log": "STUCK"}
        assert not report.complete
        assert any("git grep failed" in reason for reason in report.incomplete_reasons)
