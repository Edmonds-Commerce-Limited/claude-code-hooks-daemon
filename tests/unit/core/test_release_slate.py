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
    CiLookup,
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
            # Full refnames, as `--format=%(refname)` returns them — never the
            # short form, which a same-named tag turns into `heads/<name>`.
            names = ["main", *self.branches_ahead]
            return subprocess.CompletedProcess(
                [], 0, "".join(f"refs/heads/{n}\n" for n in names), ""
            )
        if args[0] == "rev-list" and "--count" in args:
            spec = args[-1]
            branch = spec.split("..", 1)[1].removeprefix("refs/heads/")
            return subprocess.CompletedProcess([], 0, f"{self.branches_ahead.get(branch, 0)}\n", "")
        return subprocess.CompletedProcess([], 0, "", "")


def _green(sha: str) -> CiRunState:
    return CiRunState(sha=sha, status="completed", conclusion="success")


def _collect(
    tmp_path: Path,
    *,
    git: _FakeGit | None = None,
    ci: CiLookup | None = None,
    notes: Path | None = None,
) -> SlateReport:
    plan_root = _plan_tree(tmp_path)
    return collect_slate(
        repo_root=tmp_path,
        plan_root=plan_root,
        archive_dir_names=frozenset({"Completed", "Cancelled"}),
        run_fn=git if git is not None else _FakeGit(),
        ci_lookup=ci if ci is not None else _green,
        release_notes_root=notes,
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


class _FailingGit(_FakeGit):
    """A repo whose ``failing`` git subcommand exits non-zero."""

    def __init__(
        self,
        failing: str,
        *,
        branches_ahead: dict[str, int] | None = None,
        worktrees: int = 0,
    ) -> None:
        super().__init__(branches_ahead=branches_ahead, worktrees=worktrees)
        self.failing = failing

    def __call__(self, cwd: Path, *args: str, **kw: object) -> subprocess.CompletedProcess[str]:
        if args[0] == self.failing:
            return subprocess.CompletedProcess([], 128, "", "fatal: not a git repository\n")
        return super().__call__(cwd, *args, **kw)


class TestAGitFailureIsNeverReadAsNothingInFlight:
    """`is_clean` reads "no branches, no worktrees" as clean.

    So a failing `git worktree list` returned as an empty listing CONTRIBUTES
    to a clean verdict — while the module's own rule for CI, applied two
    functions away, is that a lookup failure must never read as clean. The
    CLI reserves exit 1 for "could not determine" precisely for this.
    """

    def test_a_failing_worktree_listing_is_reported_not_swallowed(self, tmp_path: Path) -> None:
        report = _collect(tmp_path, git=_FailingGit("worktree"))
        assert report.undetermined_reason
        assert "worktree" in report.undetermined_reason

    def test_a_failing_branch_listing_is_reported_not_swallowed(self, tmp_path: Path) -> None:
        report = _collect(tmp_path, git=_FailingGit("for-each-ref"))
        assert "for-each-ref" in report.undetermined_reason

    def test_a_failing_rev_parse_is_reported(self, tmp_path: Path) -> None:
        report = _collect(tmp_path, git=_FailingGit("rev-parse"))
        assert "rev-parse" in report.undetermined_reason

    def test_an_undetermined_slate_is_never_clean(self, tmp_path: Path) -> None:
        root = tmp_path / "CLAUDE" / "Plan"
        root.mkdir(parents=True)
        report = collect_slate(
            repo_root=tmp_path,
            plan_root=root,
            archive_dir_names=frozenset(),
            run_fn=_FailingGit("worktree"),
            ci_lookup=_green,
        )
        # Everything else about this repo says clean: no plans, no branches.
        assert report.in_flight_plans == ()
        assert report.branches_ahead == ()
        assert report.is_clean is False

    def test_a_healthy_repo_carries_no_reason(self, tmp_path: Path) -> None:
        assert _collect(tmp_path).undetermined_reason == ""

    def test_the_render_says_undetermined_rather_than_clean(self, tmp_path: Path) -> None:
        root = tmp_path / "CLAUDE" / "Plan"
        root.mkdir(parents=True)
        report = collect_slate(
            repo_root=tmp_path,
            plan_root=root,
            archive_dir_names=frozenset(),
            run_fn=_FailingGit("worktree"),
            ci_lookup=_green,
        )
        text = report.render()
        assert "UNDETERMINED" in text
        assert "Slate: CLEAN" not in text


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


def _notes_dir(tmp_path: Path, *callouts: tuple[str, str]) -> Path:
    """The pending release-notes holding area, with its README and any callouts."""
    notes = tmp_path / "CLAUDE" / "UPGRADES" / "UNRELEASED" / "release-notes"
    notes.mkdir(parents=True)
    (notes / "README.md").write_text("# Release Notes — Pending Callouts\n", encoding="utf-8")
    for filename, title in callouts:
        (notes / filename).write_text(
            f"# Callout: {title}\n\n**Plan**: 00359\n**Audience**: everyone\n\nA sentence.\n",
            encoding="utf-8",
        )
    return notes


class TestPendingReleaseNotesAreInformationOnly:
    """Plan 00360: the slate check says what the release WILL SAY, never blocks on it."""

    def test_pending_callouts_are_listed_by_their_titles(self, tmp_path: Path) -> None:
        notes = _notes_dir(
            tmp_path,
            ("01-slate-gate.md", "the release now checks the slate"),
            ("02-glob-fix.md", "a malformed glob no longer skips the guard"),
        )
        report = _collect(tmp_path, notes=notes)
        assert report.pending_release_notes == (
            "the release now checks the slate",
            "a malformed glob no longer skips the guard",
        )
        text = report.render()
        assert "This release will say" in text
        assert "the release now checks the slate" in text

    def test_a_callout_without_a_title_line_is_named_by_its_file(self, tmp_path: Path) -> None:
        notes = _notes_dir(tmp_path)
        (notes / "03-untitled.md").write_text("no heading here\n", encoding="utf-8")
        assert _collect(tmp_path, notes=notes).pending_release_notes == ("03-untitled.md",)

    def test_the_readme_alone_means_nothing_pending(self, tmp_path: Path) -> None:
        report = _collect(tmp_path, notes=_notes_dir(tmp_path))
        assert report.pending_release_notes == ()
        assert "This release will say: none" in report.render()

    def test_a_missing_holding_area_means_nothing_pending(self, tmp_path: Path) -> None:
        missing = tmp_path / "nowhere"
        assert _collect(tmp_path, notes=missing).pending_release_notes == ()

    def test_pending_callouts_never_change_the_verdict(self, tmp_path: Path) -> None:
        root = tmp_path / "CLAUDE" / "Plan"
        root.mkdir(parents=True)
        report = collect_slate(
            repo_root=tmp_path,
            plan_root=root,
            archive_dir_names=frozenset(),
            run_fn=_FakeGit(),
            ci_lookup=_green,
            release_notes_root=_notes_dir(tmp_path, ("01-x.md", "x")),
        )
        assert report.pending_release_notes == ("x",)
        assert report.is_clean is True
