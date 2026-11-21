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

import pytest

from claude_code_hooks_daemon.config.models import ScratchConfig
from claude_code_hooks_daemon.core.scratch_filing import HINT_TRACKED
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
    unreadable: tuple[int, ...] = (),
) -> SweepReport:
    inputs = LivenessInputs(
        cwds={1: Path("/elsewhere")} if cwds is None else cwds,
        background=BackgroundRecords((), error),
        min_age_minutes=30,
        now=now,
        unreadable_pids=unreadable,
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

    def test_an_empty_cwd_map_makes_the_report_incomplete_and_due_entries_stuck(
        self, tmp_path: Path
    ) -> None:
        """F-BYPS low: no readable cwd at all is liveness unknown, not liveness absent."""
        tree = build_scratch_tree(tmp_path)
        tree.file("old.log")
        report = _sweep(tree, now=_now(), cwds={})
        assert not report.complete
        assert any("working director" in reason for reason in report.incomplete_reasons)
        (row,) = report.rows
        assert row.verdict.value == "STUCK"
        assert any("liveness" in reason for reason in row.reasons)

    def test_unreadable_pids_make_due_entries_stuck(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        tree.file("old.log")
        report = _sweep(tree, now=_now(), unreadable=(41, 42))
        assert not report.complete
        assert any("2 process" in reason for reason in report.incomplete_reasons)
        (row,) = report.rows
        assert row.verdict.value == "STUCK"

    def test_unknown_liveness_leaves_an_entry_within_its_ttl_live(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        tree.file("new.log")
        report = _sweep(tree, now=time.time(), cwds={})
        (row,) = report.rows
        assert row.verdict.value == "LIVE"

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
        assert "evaluated in this phase" not in text
        assert "not a git repository" in text

    def test_a_keep_marker_makes_the_entry_kept_with_its_reason(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        tree.file("pinned/a.log")
        tree.file("pinned/.scratch-keep", b"owner's draft\nsecond line\n")
        _old(tree, now)
        report = _sweep(tree, now=now)
        (row,) = [row for row in report.rows if row.name == "pinned"]
        assert row.verdict.value == "KEPT"
        assert row.reasons == ("pinned by .scratch-keep: owner's draft",)

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
        assert document["not_evaluated"] == []
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


def _git_sweep(
    gp: GitProject, now: float, *, root: Path | None = None, **kwargs: Any
) -> SweepReport:
    """A sweep of a real git project's scratch root, every entry's TTL past."""
    config = ScratchConfig()
    project_git = build_project_git(gp.project, remote="origin", default_branch="main")
    return run_sweep(
        resolve_sweep_root(
            root or gp.tree.root,
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


class TestFilingProposals:
    """DESIGN.md section 6 at sweep level (Plan 00627 Task 2.5)."""

    def _plan(self, gp: GitProject) -> str:
        folder = gp.project / "CLAUDE" / "Plan" / "00627-x"
        (folder / "subagent-reports").mkdir(parents=True)
        (folder / "PLAN.md").write_text("# Plan: x\n")
        return "CLAUDE/Plan/00627-x/subagent-reports/"

    def test_a_plan_numbered_file_is_proposed_and_nothing_moves(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        destination = self._plan(gp)
        gp.tree.file("00627-report.md", b"findings\n")
        now = _now()
        _old(gp.tree, now)
        report = _git_sweep(gp, now, plan_dir="CLAUDE/Plan")
        row = report.rows[0]
        assert row.verdict.value == "UNCERTAIN"
        assert row.filing_destination == destination
        assert row.filing_command == (f"mv -n -- untracked/scratch/00627-report.md {destination}")
        text = "\n".join(render_table(report, max_listed=50))
        assert "Filing proposals" in text
        assert row.filing_command in text
        assert report_json(report)["entries"][0]["filing_command"] == row.filing_command
        assert (gp.tree.root / "00627-report.md").exists()
        assert not (gp.project / destination / "00627-report.md").exists()

    def test_no_plan_directory_proposes_no_plan(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        self._plan(gp)
        gp.tree.file("00627-report.md", b"findings\n")
        now = _now()
        _old(gp.tree, now)
        row = _git_sweep(gp, now).rows[0]
        assert (row.filing_command, row.filing_destination.startswith("No tracked home")) == (
            "",
            True,
        )

    def test_a_p3_disposable_entry_gets_no_proposal(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        now = _now()
        gp.tree.file("copy/app.py", b"print('app')\n")
        _old(gp.tree, now)
        row = _git_sweep(gp, now, plan_dir="CLAUDE/Plan").rows[0]
        assert (row.verdict.value, row.filing_destination) == ("DISPOSABLE", "")

    def test_a_worktree_is_protected_by_a_repository(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        gp.worktree("wt", "wt-branch")
        now = _now()
        _old(gp.tree, now)
        row = _git_sweep(gp, now, plan_dir="CLAUDE/Plan").rows[0]
        assert row.verdict.value == "PROTECTED"
        assert row.filing_destination.startswith("commit and push to a branch on the remote")

    def test_an_entry_holding_a_tracked_file_is_for_a_human(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        self._plan(gp)
        gp.tree.file("00627-held/x.txt", b"tracked\n")
        git(gp.project, "add", "-f", "--", "untracked/scratch/00627-held/x.txt")
        git(gp.project, "commit", "-q", "-m", "track")
        now = _now()
        _old(gp.tree, now)
        row = _git_sweep(gp, now, plan_dir="CLAUDE/Plan").rows[0]
        assert row.verdict.value == "PROTECTED"
        assert (row.filing_destination, row.filing_command) == (HINT_TRACKED, "")

    def test_the_proposals_section_is_bounded(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        for name in ("a.md", "b.md", "c.md"):
            gp.tree.file(name, b"prose\n")
        now = _now()
        _old(gp.tree, now)
        text = "\n".join(render_table(_git_sweep(gp, now), max_listed=1))
        assert "2 more proposal(s)" in text


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

    def test_a_reference_to_a_sub_root_itself_protects_its_entries(self, tmp_path: Path) -> None:
        """F-BYPS 3: ``--root untracked/scratch/sub`` honours a line naming ``sub``."""
        gp = build_git_project(tmp_path)
        commit_file(gp.project, "docs/ref.md", "see untracked/scratch/sub for the evidence\n")
        gp.tree.file("sub/run.log")
        gp.tree.file("sub/qa-findings.md")
        now = _now()
        for name in ("run.log", "qa-findings.md"):
            gp.tree.set_tree_mtime(f"sub/{name}", now - 2 * _DAY)
        report = _git_sweep(gp, now, root=gp.tree.root / "sub")
        assert _verdicts(report) == {"run.log": "REFERENCED", "qa-findings.md": "REFERENCED"}

    def test_an_ancestor_mention_does_not_protect_sub_root_entries(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        commit_file(gp.project, "docs/ref.md", "scratch goes in untracked/scratch/ always\n")
        gp.tree.file("sub/run.log")
        now = _now()
        gp.tree.set_tree_mtime("sub/run.log", now - 2 * _DAY)
        report = _git_sweep(gp, now, root=gp.tree.root / "sub")
        assert _verdicts(report) == {"run.log": "DISPOSABLE"}

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


class TestCrossEntryDependencies:
    """F-BYPS 2: an entry another entry's ``.git`` pointer depends on is never disposable."""

    def test_a_standalone_repository_another_entry_points_into_is_protected(
        self, tmp_path: Path
    ) -> None:
        gp = build_git_project(tmp_path)
        repo = gp.standalone("a/repo")
        gp.tree.git_marker("b", gitdir=str(repo / ".git"))
        now = _now()
        _old(gp.tree, now)
        report = _git_sweep(gp, now)
        assert _verdicts(report) == {"a": "PROTECTED", "b": "PROTECTED"}
        row = next(row for row in report.rows if row.name == "a")
        assert "b/.git" in " ".join(row.reasons)
        assert (row.filing_destination, row.filing_command) == ("", "")

    def test_a_relative_pointer_into_another_entry_is_followed_lexically(
        self, tmp_path: Path
    ) -> None:
        gp = build_git_project(tmp_path)
        gp.standalone("a")
        gp.tree.git_marker("b/x", gitdir="../../a/.git")
        now = _now()
        _old(gp.tree, now)
        assert _verdicts(_git_sweep(gp, now))["a"] == "PROTECTED"

    def test_a_pointer_into_its_own_entry_changes_nothing(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        parent = gp.standalone("e/main")
        git(parent, "worktree", "add", "-q", "-b", "side", str(gp.tree.root / "e" / "side"))
        now = _now()
        _old(gp.tree, now)
        assert _verdicts(_git_sweep(gp, now)) == {"e": "DISPOSABLE"}

    def test_n2_a_separate_git_dir_whose_work_tree_is_outside_is_protected(
        self, tmp_path: Path
    ) -> None:
        gp = build_git_project(tmp_path)
        work = gp.tree.outside / "wt"
        git(gp.tree.root, "init", "-q", "--separate-git-dir", str(gp.tree.root / "gd"), str(work))
        commit_file(work, "work.txt", "lives outside the scratch root\n")
        now = _now()
        _old(gp.tree, now)
        report = _git_sweep(gp, now)
        assert _verdicts(report) == {"gd": "PROTECTED"}
        row = next(row for row in report.rows if row.name == "gd")
        assert "separate-git-dir" in " ".join(row.reasons)

    def test_n2_a_separate_git_dir_with_its_work_tree_in_the_entry_is_disposable(
        self, tmp_path: Path
    ) -> None:
        gp = build_git_project(tmp_path)
        entry = gp.tree.root / "e"
        entry.mkdir()
        git(gp.tree.root, "init", "-q", "--separate-git-dir", str(entry / "gd"), str(entry / "wt"))
        commit_file(entry / "wt", "work.txt", "throwaway\n")
        now = _now()
        _old(gp.tree, now)
        assert _verdicts(_git_sweep(gp, now)) == {"e": "DISPOSABLE"}

    def test_an_unreadable_pointer_makes_disposable_rows_stuck(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        gp.standalone("a")
        gp.tree.directory("b")
        os.mkfifo(gp.tree.root / "b" / ".git")
        now = _now()
        _old(gp.tree, now)
        report = _git_sweep(gp, now)
        assert _verdicts(report)["a"] == "STUCK"
        assert not report.complete
        assert any("b/.git" in reason for reason in report.incomplete_reasons)

    def test_n1_an_entry_lending_its_objects_is_protected(self, tmp_path: Path) -> None:
        """N1: ``git clone --shared`` leaves the borrower needing the lender's objects."""
        gp = build_git_project(tmp_path)
        lender = gp.standalone("lender")
        borrower = gp.tree.root / "borrower"
        git(gp.tree.root, "clone", "-q", "--shared", str(lender), str(borrower))
        (borrower / "new.txt").write_text("work\n")
        git(borrower, "add", "new.txt")
        git(borrower, "commit", "-q", "-m", "work")
        now = _now()
        _old(gp.tree, now)
        report = _git_sweep(gp, now)
        assert _verdicts(report)["lender"] == "PROTECTED"
        row = next(row for row in report.rows if row.name == "lender")
        assert "borrower/.git/objects/info/alternates" in " ".join(row.reasons)

    @pytest.mark.parametrize("relative", [True, False])
    def test_n1_an_alternates_line_relative_or_absolute_is_mapped(
        self, tmp_path: Path, relative: bool
    ) -> None:
        gp = build_git_project(tmp_path)
        gp.standalone("a")
        gp.standalone("b")
        target = "../../../a/.git/objects" if relative else str(gp.tree.root / "a/.git/objects")
        alternates = gp.tree.root / "b/.git/objects/info/alternates"
        alternates.parent.mkdir(parents=True, exist_ok=True)
        alternates.write_text(f"# a comment\n\n{target}\n")
        now = _now()
        _old(gp.tree, now)
        verdicts = _verdicts(_git_sweep(gp, now))
        assert verdicts["a"] == "PROTECTED"

    def test_n1_an_alternates_line_into_its_own_entry_changes_nothing(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        gp.standalone("e/one")
        gp.standalone("e/two")
        alternates = gp.tree.root / "e/two/.git/objects/info/alternates"
        alternates.parent.mkdir(parents=True, exist_ok=True)
        alternates.write_text("../../../one/.git/objects\n")
        now = _now()
        _old(gp.tree, now)
        report = _git_sweep(gp, now)
        # The borrower is related (it borrows objects), so ``e`` is PROTECTED on its
        # own account; the cross-entry pass must add no dependency of its own.
        assert report.complete
        assert not any("depends on this one" in r for row in report.rows for r in row.reasons)

    @pytest.mark.parametrize("shape", ["fifo", "oversize", "link", "quoted"])
    def test_n1_an_unreadable_alternates_file_makes_disposable_rows_stuck(
        self, tmp_path: Path, shape: str
    ) -> None:
        gp = build_git_project(tmp_path)
        gp.standalone("a")
        gp.standalone("b")
        alternates = gp.tree.root / "b/.git/objects/info/alternates"
        alternates.parent.mkdir(parents=True, exist_ok=True)
        if shape == "fifo":
            os.mkfifo(alternates)
        elif shape == "oversize":
            alternates.write_text(f"{gp.tree.root / 'a/.git/objects'}\n" * 10_000)
        elif shape == "quoted":
            quoted = str(gp.tree.root / "a/.git/obj") + "\\145cts"
            alternates.write_text(f'"{quoted}"\n')
        else:
            (gp.tree.root / "b/alt.txt").write_text(f"{gp.tree.root / 'a/.git/objects'}\n")
            alternates.symlink_to(gp.tree.root / "b/alt.txt")
        now = _now()
        _old(gp.tree, now)
        report = _git_sweep(gp, now)
        verdicts = _verdicts(report)
        assert verdicts["a"] != "DISPOSABLE"
        assert verdicts["b"] != "DISPOSABLE"
        assert not report.complete
        assert any("alternates" in reason for reason in report.incomplete_reasons)

    def test_an_entry_not_walked_to_the_end_makes_disposable_rows_stuck(
        self, tmp_path: Path
    ) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        tree.file("box/inner/a.txt")
        tree.file("cache/__pycache__/m.pyc", b"pyc")
        _old(tree, now)
        report = _sweep(tree, now=now, refused=("box/inner",))
        assert _verdicts(report) == {"box": "STUCK", "cache": "STUCK"}
        assert any("box was not walked" in reason for reason in report.incomplete_reasons)


_SESSION = "s-20261101T000000Z-abcdefgh"


class TestSessionDirectoryIsNeverActedOnWhole:
    """Task 4.3 step 1: a session directory is a container, never packed as one entry."""

    def test_a_due_session_directory_is_not_actionable(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        tree.file(f"{_SESSION}/.scratch-session.json", b"{}")
        tree.file(f"{_SESSION}/cache/__pycache__/m.pyc", b"pyc")
        tree.file("cache/__pycache__/m.pyc", b"pyc")
        _old(tree, now)
        report = _sweep(tree, now=now)
        assert _verdicts(report) == {_SESSION: "STUCK", "cache": "DISPOSABLE"}
        row = next(row for row in report.rows if row.name == _SESSION)
        assert any("session directory" in reason for reason in row.reasons)
        assert row.proofs == ()

    def test_a_link_with_a_session_name_is_judged_as_an_ordinary_entry(
        self, tmp_path: Path
    ) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        (tree.root / _SESSION).symlink_to(tmp_path / "nowhere")
        report = _sweep(tree, now=now)
        row = next(row for row in report.rows if row.name == _SESSION)
        assert not any("session directory" in reason for reason in row.reasons)

    def test_a_session_child_pointing_at_an_entry_still_protects_it(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        gp.tree.file("lender/.git/objects/pack/x", b"x")
        alternates = gp.tree.root / f"{_SESSION}/clone/.git/objects/info/alternates"
        alternates.parent.mkdir(parents=True)
        alternates.write_text(f"{gp.tree.root / 'lender/.git/objects'}\n")
        now = _now()
        _old(gp.tree, now)
        verdicts = _verdicts(_git_sweep(gp, now))
        assert verdicts[_SESSION] not in {"DISPOSABLE", "UNCERTAIN"}
        assert verdicts["lender"] not in {"DISPOSABLE", "UNCERTAIN"}


def _children(report: SweepReport, session: str = _SESSION) -> dict[str, str]:
    """The verdicts of one session directory's children (its sub-report)."""
    found = [sub for sub in report.sessions if Path(sub.root).name == session]
    assert len(found) == 1, [sub.root for sub in report.sessions]
    return _verdicts(found[0])


_ACTIONABLE_VALUES = {"DISPOSABLE", "UNCERTAIN"}


class TestSessionChildrenAreTheEntries:
    """Task 4.3 step 2: a session directory's children are judged as entries of their own."""

    def _session(self, tree: ScratchTree) -> None:
        tree.file(f"{_SESSION}/.scratch-session.json", b"{}")
        # scratch_session writes the manifest through ``.<name>.tmp-<hex>``.
        tree.file(f"{_SESSION}/..scratch-session.json.tmp-0123456789ab", b"{}")
        tree.file(f"{_SESSION}/cache/__pycache__/m.pyc", b"pyc")

    def test_children_are_judged_and_container_files_are_never_rows(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        self._session(tree)
        _old(tree, now)
        report = _sweep(tree, now=now)
        assert _verdicts(report) == {_SESSION: "STUCK"}
        assert _children(report) == {"cache": "DISPOSABLE"}
        document = report_json(report)
        assert document["sessions"][0]["entries"][0]["name"] == "cache"
        assert any("cache" in line for line in render_table(report, max_listed=50))

    def test_a_session_keep_marker_keeps_every_child(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        self._session(tree)
        tree.file(f"{_SESSION}/.scratch-keep", b"hold the session\n")
        _old(tree, now)
        assert _children(_sweep(tree, now=now)) == {"cache": "KEPT"}

    def test_a_working_directory_at_the_session_holds_every_child(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        self._session(tree)
        _old(tree, now)
        report = _sweep(tree, now=now, cwds={7: (tree.root / _SESSION).resolve()})
        assert _children(report) == {"cache": "LIVE"}

    def test_a_working_directory_in_one_child_does_not_hold_another(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        self._session(tree)
        tree.file(f"{_SESSION}/work/notes.txt", b"n")
        _old(tree, now)
        cwd = (tree.root / _SESSION / "work").resolve()
        children = _children(_sweep(tree, now=now, cwds={7: cwd}))
        assert children["work"] == "LIVE"
        assert children["cache"] == "DISPOSABLE"

    def test_a_not_due_session_does_not_block_a_due_child(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        self._session(tree)
        tree.file(f"{_SESSION}/fresh/notes.txt", b"n")
        _old(tree, now)
        tree.set_tree_mtime(f"{_SESSION}/fresh", now - 60)
        report = _sweep(tree, now=now)
        assert _verdicts(report)[_SESSION] == "LIVE"
        children = _children(report)
        assert children["cache"] == "DISPOSABLE"
        assert children["fresh"] == "LIVE"

    def test_a_dependency_on_the_session_holds_every_child(self, tmp_path: Path) -> None:
        gp = build_git_project(tmp_path)
        gp.tree.file(f"{_SESSION}/.scratch-session.json", b"{}")
        gp.tree.file(f"{_SESSION}/cache/__pycache__/m.pyc", b"pyc")
        gp.tree.file(f"{_SESSION}/lender/.git/objects/pack/x", b"x")
        alternates = gp.tree.root / "clone/.git/objects/info/alternates"
        alternates.parent.mkdir(parents=True)
        alternates.write_text(f"{gp.tree.root / _SESSION / 'lender/.git/objects'}\n")
        now = _now()
        _old(gp.tree, now)
        children = _children(_git_sweep(gp, now))
        assert children["cache"] not in _ACTIONABLE_VALUES
        assert children["lender"] not in _ACTIONABLE_VALUES

    def test_a_session_that_is_a_repository_is_judged_whole(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        self._session(tree)
        tree.file(f"{_SESSION}/.git/HEAD", b"ref: refs/heads/main\n")
        _old(tree, now)
        report = _sweep(tree, now=now)
        assert report.sessions == ()
        assert _verdicts(report)[_SESSION] not in _ACTIONABLE_VALUES

    def test_a_session_named_child_is_an_ordinary_entry(self, tmp_path: Path) -> None:
        tree = build_scratch_tree(tmp_path)
        now = _now()
        self._session(tree)
        inner = "s-20261102T000000Z-ijklmnop"
        tree.file(f"{_SESSION}/{inner}/__pycache__/m.pyc", b"pyc")
        _old(tree, now)
        report = _sweep(tree, now=now)
        assert _children(report)[inner] == "DISPOSABLE"
        assert all(Path(sub.root).name != inner for sub in report.sessions)

    def test_a_recorded_longer_ttl_holds_a_child(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime

        from claude_code_hooks_daemon.core.scratch_session import ensure_session_dir, new_entry

        tree = build_scratch_tree(tmp_path)
        now = _now()
        born = datetime.fromtimestamp(now - 3 * _DAY, UTC)
        session = ensure_session_dir(
            tree.root, "abcdefgh-session", now=born, checkout="c", branch=None
        ).path
        new_entry(session, "long", now=born, purpose=None, plan=None, ttl_hours=70)
        new_entry(session, "short", now=born, purpose=None, plan=None, ttl_hours=None)
        (session / "long" / "a.log").write_bytes(b"x")
        (session / "short" / "a.log").write_bytes(b"x")
        _old(tree, now)
        children = _children(_sweep(tree, now=now), session.name)
        assert children["long"] == "LIVE"
        assert children["short"] in _ACTIONABLE_VALUES
