"""Plan 00359 — the release pipeline checks the slate is clean before it starts.

Every existing release gate looks at the CODE. None looks at the state of the
WORK around it, so a release could begin on a HEAD that CI never passed, over
plans mid-work, with unlanded branches and live worktrees — and every gate
would pass. ``collect_slate`` puts all of that on one screen and says whether
there is anything for a human to decide.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.core.release_slate import (
    CiRunState,
    SlateReport,
    collect_slate,
)

_HEAD = "1cdcc2b1deadbeef00000000000000000000abcd"


def _plan(root: Path, number: int, name: str, *, status: str, priority: str = "Medium") -> None:
    folder = root / f"{number:05d}-{name}"
    folder.mkdir(parents=True)
    (folder / "PLAN.md").write_text(
        f"# Plan {number:05d}: {name}\n\n"
        f"**Status**: {status}\n"
        f"**Created**: 2026-09-08\n"
        f"**Owner**: joseph\n"
        f"**Priority**: {priority}\n\n"
        "## Overview\n\ntext\n",
        encoding="utf-8",
    )


def _plan_tree(tmp_path: Path) -> Path:
    root = tmp_path / "CLAUDE" / "Plan"
    _plan(root, 1, "mid-work", status="In Progress")
    _plan(
        root,
        2,
        "waiting-for-release",
        status="In Progress (blocked SOLELY on a human running `/release`)",
    )
    _plan(root, 3, "security-finding", status="Not Started", priority="High")
    _plan(root, 4, "ordinary", status="Not Started")
    _plan(root, 5, "dormant", status="Dormant")
    _plan(root / "Completed", 6, "done", status="Complete")
    return root


class _FakeGit:
    """A repo with one branch ahead of main and one live worktree."""

    def __init__(self, *, branches_ahead: dict[str, int] | None = None, worktrees: int = 0):
        self.branches_ahead = branches_ahead if branches_ahead is not None else {}
        self.worktrees = worktrees

    def __call__(self, cwd: Path, *args: str, **_: object) -> subprocess.CompletedProcess[str]:
        if args[0] == "rev-parse" and "HEAD" in args:
            return subprocess.CompletedProcess([], 0, f"{_HEAD}\n", "")
        if args[0] == "worktree" and args[1] == "list":
            lines = [f"worktree {cwd}\nHEAD {_HEAD}\nbranch refs/heads/main\n"]
            lines += [
                f"worktree {cwd}/.claude/worktrees/wt-{n}\nHEAD {_HEAD}\nbranch refs/heads/wt-{n}\n"
                for n in range(self.worktrees)
            ]
            return subprocess.CompletedProcess([], 0, "\n".join(lines), "")
        if args[0] == "for-each-ref":
            names = ["main", *self.branches_ahead]
            return subprocess.CompletedProcess([], 0, "".join(f"{n}\n" for n in names), "")
        if args[0] == "rev-list" and "--count" in args:
            spec = args[-1]
            branch = spec.split("..", 1)[1]
            return subprocess.CompletedProcess(
                [], 0, f"{self.branches_ahead.get(branch, 0)}\n", ""
            )
        return subprocess.CompletedProcess([], 0, "", "")


def _green(sha: str) -> CiRunState:
    return CiRunState(sha=sha, status="completed", conclusion="success")


def _collect(tmp_path: Path, *, git: _FakeGit | None = None, ci: object = None) -> SlateReport:
    plan_root = _plan_tree(tmp_path)
    return collect_slate(
        repo_root=tmp_path,
        plan_root=plan_root,
        archive_dir_names=frozenset({"Completed", "Cancelled"}),
        run_fn=git if git is not None else _FakeGit(),
        ci_lookup=ci if ci is not None else _green,
    )


class TestPlansAreClassifiedNotJustListed:
    def test_a_mid_work_plan_is_in_flight(self, tmp_path: Path) -> None:
        report = _collect(tmp_path)
        assert [p.number for p in report.in_flight_plans] == [1]

    def test_a_plan_waiting_for_the_release_is_not_a_blocker(self, tmp_path: Path) -> None:
        """It is the OPPOSITE of a blocker — it wants this release to happen."""
        report = _collect(tmp_path)
        assert [p.number for p in report.release_gated_plans] == [2]
        assert 2 not in [p.number for p in report.in_flight_plans]

    def test_a_high_priority_unstarted_plan_is_surfaced_for_attention(self, tmp_path: Path) -> None:
        report = _collect(tmp_path)
        assert [p.number for p in report.attention_plans] == [3]

    def test_ordinary_dormant_and_archived_plans_are_not_reported(self, tmp_path: Path) -> None:
        report = _collect(tmp_path)
        reported = {p.number for p in report.in_flight_plans}
        reported |= {p.number for p in report.release_gated_plans}
        reported |= {p.number for p in report.attention_plans}
        assert reported.isdisjoint({4, 5, 6})


class TestHeadMustBeGreenNotMerelyRecentlyGreen:
    def test_a_successful_completed_run_for_head_is_green(self, tmp_path: Path) -> None:
        report = _collect(tmp_path)
        assert report.head_ci.is_green
        assert report.head_sha == _HEAD

    def test_an_in_progress_run_is_not_green(self, tmp_path: Path) -> None:
        report = _collect(
            tmp_path, ci=lambda sha: CiRunState(sha=sha, status="in_progress", conclusion=None)
        )
        assert not report.head_ci.is_green

    def test_a_cancelled_run_is_not_green(self, tmp_path: Path) -> None:
        """The exact failure that prompted this: each push cancelled the last run."""
        report = _collect(
            tmp_path, ci=lambda sha: CiRunState(sha=sha, status="completed", conclusion="cancelled")
        )
        assert not report.head_ci.is_green

    def test_a_running_run_reported_with_an_empty_conclusion_renders_cleanly(
        self, tmp_path: Path
    ) -> None:
        """`gh run list` says conclusion "" (not null) while a run is in progress."""
        report = _collect(
            tmp_path, ci=lambda sha: CiRunState(sha=sha, status="in_progress", conclusion="")
        )
        assert not report.head_ci.is_green
        assert report.head_ci.describe() == "in_progress"

    def test_no_run_at_all_for_head_is_not_green(self, tmp_path: Path) -> None:
        report = _collect(tmp_path, ci=lambda sha: None)
        assert not report.head_ci.is_green
        assert report.head_ci.sha == _HEAD

    def test_a_lookup_failure_is_not_green_and_is_named(self, tmp_path: Path) -> None:
        """Could-not-determine must never read as clean."""

        def broken(sha: str) -> CiRunState | None:
            raise OSError("gh: not authenticated")

        report = _collect(tmp_path, ci=broken)
        assert not report.head_ci.is_green
        assert "not authenticated" in report.head_ci.problem


class TestBranchesAndWorktreesAreListedNeverTouched:
    def test_branches_ahead_of_main_are_listed_with_their_counts(self, tmp_path: Path) -> None:
        report = _collect(tmp_path, git=_FakeGit(branches_ahead={"agent-x": 3, "feature/y": 1}))
        assert {b.name: b.ahead for b in report.branches_ahead} == {"agent-x": 3, "feature/y": 1}

    def test_a_branch_with_nothing_unlanded_is_not_listed(self, tmp_path: Path) -> None:
        report = _collect(tmp_path, git=_FakeGit(branches_ahead={"merged": 0}))
        assert report.branches_ahead == ()

    def test_live_worktrees_are_counted_excluding_the_main_one(self, tmp_path: Path) -> None:
        report = _collect(tmp_path, git=_FakeGit(worktrees=2))
        assert len(report.worktrees) == 2


class TestTheVerdict:
    def test_clean_when_nothing_is_in_flight(self, tmp_path: Path) -> None:
        root = tmp_path / "CLAUDE" / "Plan"
        _plan(
            root,
            2,
            "waiting",
            status="In Progress (blocked SOLELY on a human running `/release`)",
        )
        report = collect_slate(
            repo_root=tmp_path,
            plan_root=root,
            archive_dir_names=frozenset({"Completed"}),
            run_fn=_FakeGit(),
            ci_lookup=_green,
        )
        assert report.is_clean

    def test_any_in_flight_plan_makes_it_not_clean(self, tmp_path: Path) -> None:
        assert not _collect(tmp_path).is_clean

    def test_a_non_green_head_alone_makes_it_not_clean(self, tmp_path: Path) -> None:
        root = tmp_path / "CLAUDE" / "Plan"
        root.mkdir(parents=True)
        report = collect_slate(
            repo_root=tmp_path,
            plan_root=root,
            archive_dir_names=frozenset(),
            run_fn=_FakeGit(),
            ci_lookup=lambda sha: None,
        )
        assert not report.is_clean

    def test_a_branch_ahead_alone_makes_it_not_clean(self, tmp_path: Path) -> None:
        root = tmp_path / "CLAUDE" / "Plan"
        root.mkdir(parents=True)
        report = collect_slate(
            repo_root=tmp_path,
            plan_root=root,
            archive_dir_names=frozenset(),
            run_fn=_FakeGit(branches_ahead={"agent-x": 1}),
            ci_lookup=_green,
        )
        assert not report.is_clean

    def test_attention_plans_alone_do_not_make_it_unclean(self, tmp_path: Path) -> None:
        """They are shown; whether they matter is scope, and scope is the human's call."""
        root = tmp_path / "CLAUDE" / "Plan"
        _plan(root, 3, "finding", status="Not Started", priority="High")
        report = collect_slate(
            repo_root=tmp_path,
            plan_root=root,
            archive_dir_names=frozenset(),
            run_fn=_FakeGit(),
            ci_lookup=_green,
        )
        assert report.is_clean
        assert [p.number for p in report.attention_plans] == [3]


class TestTheReportReadsAsAReportNotAQuestion:
    def test_a_clean_slate_renders_without_a_question_mark(self, tmp_path: Path) -> None:
        root = tmp_path / "CLAUDE" / "Plan"
        root.mkdir(parents=True)
        report = collect_slate(
            repo_root=tmp_path,
            plan_root=root,
            archive_dir_names=frozenset(),
            run_fn=_FakeGit(),
            ci_lookup=_green,
        )
        assert "?" not in report.render()

    def test_an_unclean_slate_names_every_item(self, tmp_path: Path) -> None:
        report = _collect(
            tmp_path,
            git=_FakeGit(branches_ahead={"agent-x": 3}, worktrees=1),
            ci=lambda sha: CiRunState(sha=sha, status="completed", conclusion="cancelled"),
        )
        text = report.render()
        assert "00001" in text
        assert "00002" in text
        assert "00003" in text
        assert "agent-x" in text
        assert "cancelled" in text
        assert _HEAD[:8] in text
