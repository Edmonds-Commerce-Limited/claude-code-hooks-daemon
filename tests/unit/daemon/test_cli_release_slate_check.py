"""Plan 00359 — ``bin/hooks-daemon release-slate-check``.

The exit code IS the contract the release skill consumes: 0 means clean and
the pipeline proceeds exactly as before; 2 means something is in flight and a
human decides; 1 means the check could not be made — which must never read as
clean. ``--accept`` records that the human has decided, so the report still
prints but the exit is 0.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.release_slate import (
    BranchAhead,
    CiRunState,
    PlanSummary,
    SlateReport,
)
from claude_code_hooks_daemon.daemon import cli

_HEAD = "abcdef0123456789abcdef0123456789abcdef01"


def _report(*, clean: bool) -> SlateReport:
    ci = CiRunState(sha=_HEAD, status="completed", conclusion="success")
    if clean:
        return SlateReport(_HEAD, ci, (), (), (), (), ())
    return SlateReport(
        head_sha=_HEAD,
        head_ci=CiRunState(sha=_HEAD, status="completed", conclusion="cancelled"),
        in_flight_plans=(PlanSummary(1, "mid-work", "In Progress"),),
        release_gated_plans=(),
        attention_plans=(),
        branches_ahead=(BranchAhead("agent-x", 3),),
        worktrees=(Path("/w/.claude/worktrees/x"),),
        pending_release_notes=("the release now checks the slate",),
    )


def _undetermined_report() -> SlateReport:
    """Collection completed, but one of its git reads failed."""
    return SlateReport(
        head_sha=_HEAD,
        head_ci=CiRunState(sha=_HEAD, status="completed", conclusion="success"),
        in_flight_plans=(),
        release_gated_plans=(),
        attention_plans=(),
        branches_ahead=(),
        worktrees=(),
        undetermined_reason="git worktree list --porcelain failed (exit 128)",
    )


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {"accept": False, "json": False}
    values.update(overrides)
    return argparse.Namespace(**values)


class TestExitCodeIsTheContract:
    def test_clean_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = cli.cmd_release_slate_check(_args(), collect=lambda: _report(clean=True))
        assert code == cli.RELEASE_SLATE_CLEAN
        assert "CLEAN" in capsys.readouterr().out

    def test_in_flight_exits_two_with_the_report(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = cli.cmd_release_slate_check(_args(), collect=lambda: _report(clean=False))
        assert code == cli.RELEASE_SLATE_IN_FLIGHT
        out = capsys.readouterr().out
        assert "00001" in out
        assert "agent-x" in out
        assert "cancelled" in out

    def test_accept_turns_in_flight_into_zero_but_still_prints(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The decision is the human's; the report is still the record of it."""
        code = cli.cmd_release_slate_check(_args(accept=True), collect=lambda: _report(clean=False))
        assert code == cli.RELEASE_SLATE_CLEAN
        out = capsys.readouterr().out
        assert "00001" in out
        assert "accept" in out.lower()

    def test_a_collection_failure_exits_one_never_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def broken() -> SlateReport:
            raise OSError("not a git repository")

        code = cli.cmd_release_slate_check(_args(), collect=broken)
        assert code == cli.RELEASE_SLATE_UNDETERMINED
        assert "not a git repository" in capsys.readouterr().err

    def test_accept_does_not_rescue_an_undetermined_check(self) -> None:
        """Acknowledging WIP is not the same as acknowledging blindness."""

        def broken() -> SlateReport:
            raise OSError("boom")

        code = cli.cmd_release_slate_check(_args(accept=True), collect=broken)
        assert code == cli.RELEASE_SLATE_UNDETERMINED

    def test_a_report_that_collected_but_could_not_determine_exits_one(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A git listing that FAILED is not a listing that was empty.

        Collection completes — there is a report to print — but part of it is
        blind, so the exit is UNDETERMINED rather than CLEAN.
        """
        code = cli.cmd_release_slate_check(_args(), collect=lambda: _undetermined_report())
        assert code == cli.RELEASE_SLATE_UNDETERMINED
        out = capsys.readouterr().out
        assert "git worktree list --porcelain failed" in out

    def test_accept_does_not_rescue_an_undetermined_report_either(self) -> None:
        code = cli.cmd_release_slate_check(
            _args(accept=True), collect=lambda: _undetermined_report()
        )
        assert code == cli.RELEASE_SLATE_UNDETERMINED


class TestJsonOutput:
    def test_json_carries_the_verdict_and_every_section(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import json

        cli.cmd_release_slate_check(_args(json=True), collect=lambda: _report(clean=False))
        payload = json.loads(capsys.readouterr().out)
        assert payload["clean"] is False
        assert payload["head_sha"] == _HEAD
        assert payload["head_ci"]["green"] is False
        assert [p["number"] for p in payload["in_flight_plans"]] == [1]
        assert payload["branches_ahead"][0]["name"] == "agent-x"
        assert payload["pending_release_notes"] == ["the release now checks the slate"]


_MATRIX_JOBS = [
    {"name": "Classify change", "conclusion": "success"},
    {"name": "QA (Python3.11)", "conclusion": "success"},
    {"name": "QA (Python3.12)", "conclusion": "success"},
    {"name": "QA (Python3.13)", "conclusion": "success"},
]
_TIER_JOBS = [
    {"name": "Classify change", "conclusion": "success"},
    {"name": "QA (docs or code tier)", "conclusion": "success"},
    {"name": "QA (Python${{ matrix.python-version }})", "conclusion": "skipped"},
]


class _FakeGh:
    """Stands in for ``gh run list`` and ``gh run view``, recording every argv."""

    def __init__(
        self,
        runs: list[dict[str, object]],
        jobs_by_run: dict[int, list[dict[str, str]]],
        *,
        view_fails: bool = False,
        view_output: str | None = None,
    ) -> None:
        self.runs = runs
        self.jobs_by_run = jobs_by_run
        self.view_fails = view_fails
        self.view_output = view_output
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        if argv[2] == "list":
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.runs), "")
        if self.view_fails:
            raise subprocess.CalledProcessError(1, argv)
        if self.view_output is not None:
            return subprocess.CompletedProcess(argv, 0, self.view_output, "")
        run_id = int(argv[3])
        return subprocess.CompletedProcess(
            argv, 0, json.dumps({"jobs": self.jobs_by_run[run_id]}), ""
        )


def _run(run_id: int, *, sha: str = _HEAD, conclusion: str = "success") -> dict[str, object]:
    return {
        "databaseId": run_id,
        "headSha": sha,
        "status": "completed",
        "conclusion": conclusion,
    }


@pytest.fixture
def fake_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "run_git",
        lambda *a, **k: subprocess.CompletedProcess([], 0, "main\n", ""),
    )


def _install(monkeypatch: pytest.MonkeyPatch, gh: _FakeGh) -> None:
    monkeypatch.setattr(subprocess, "run", gh)


@pytest.mark.usefixtures("fake_branch")
class TestTheCiLookupRequiresTheFullMatrix:
    def test_a_run_whose_matrix_jobs_all_succeeded_is_green(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gh = _FakeGh([_run(1)], {1: _MATRIX_JOBS})
        _install(monkeypatch, gh)
        state = cli._gh_ci_lookup(_HEAD)
        assert state is not None
        assert state.is_green

    def test_the_run_list_is_limited_to_the_qa_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gh = _FakeGh([_run(1)], {1: _MATRIX_JOBS})
        _install(monkeypatch, gh)
        cli._gh_ci_lookup(_HEAD)
        listing = gh.calls[0]
        assert listing[listing.index("--workflow") + 1] == "qa.yml"
        assert "databaseId" in listing[listing.index("--json") + 1]

    def test_a_tier_run_is_not_green_and_names_the_remedy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _FakeGh([_run(1)], {1: _TIER_JOBS}))
        state = cli._gh_ci_lookup(_HEAD)
        assert state is not None
        assert not state.is_green
        assert "gh workflow run qa.yml --ref main" in state.describe()

    def test_a_full_matrix_run_beats_a_newer_tier_run_on_the_same_sha(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gh = _FakeGh([_run(2), _run(1)], {2: _TIER_JOBS, 1: _MATRIX_JOBS})
        _install(monkeypatch, gh)
        state = cli._gh_ci_lookup(_HEAD)
        assert state is not None
        assert state.is_green

    def test_the_run_that_was_read_is_named_in_the_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _FakeGh([_run(2), _run(1)], {2: _TIER_JOBS, 1: _MATRIX_JOBS}))
        state = cli._gh_ci_lookup(_HEAD)
        assert state is not None
        assert state.run_id == 1
        assert "run 1" in state.describe()

    def test_the_newest_full_matrix_run_wins_over_an_older_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failed_jobs = [*_MATRIX_JOBS[:3], {"name": "QA (Python3.13)", "conclusion": "failure"}]
        gh = _FakeGh([_run(3, conclusion="failure"), _run(2)], {3: failed_jobs, 2: _MATRIX_JOBS})
        _install(monkeypatch, gh)
        state = cli._gh_ci_lookup(_HEAD)
        assert state is not None
        assert state.run_id == 3
        assert not state.is_green

    def test_a_cancelled_run_is_passed_over_for_its_rerun(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gh = _FakeGh([_run(2, conclusion="cancelled"), _run(1)], {1: _MATRIX_JOBS})
        _install(monkeypatch, gh)
        state = cli._gh_ci_lookup(_HEAD)
        assert state is not None
        assert state.is_green
        assert state.run_id == 1
        assert all(call[3] != "2" for call in gh.calls if call[2] == "view")

    def test_a_newer_rerun_beats_an_older_cancelled_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gh = _FakeGh([_run(2), _run(1, conclusion="cancelled")], {2: _MATRIX_JOBS})
        _install(monkeypatch, gh)
        state = cli._gh_ci_lookup(_HEAD)
        assert state is not None
        assert state.run_id == 2

    def test_an_in_progress_newer_run_does_not_hide_a_completed_older_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        running = {**_run(2), "status": "in_progress", "conclusion": ""}
        gh = _FakeGh([running, _run(1)], {1: _MATRIX_JOBS})
        _install(monkeypatch, gh)
        state = cli._gh_ci_lookup(_HEAD)
        assert state is not None
        assert state.is_green
        assert state.run_id == 1

    def test_with_no_qualifying_run_the_newest_run_is_reported_not_green(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        running = {**_run(2), "status": "in_progress", "conclusion": ""}
        _install(monkeypatch, _FakeGh([running], {}))
        state = cli._gh_ci_lookup(_HEAD)
        assert state is not None
        assert not state.is_green
        assert state.run_id == 2
        assert "in_progress" in state.describe()

    def test_a_run_for_another_sha_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, _FakeGh([_run(1, sha="f" * 40)], {1: _MATRIX_JOBS}))
        assert cli._gh_ci_lookup(_HEAD) is None

    def test_a_failed_matrix_run_is_not_green_and_is_named(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failed_jobs = [*_MATRIX_JOBS[:3], {"name": "QA (Python3.13)", "conclusion": "failure"}]
        _install(monkeypatch, _FakeGh([_run(1, conclusion="failure")], {1: failed_jobs}))
        state = cli._gh_ci_lookup(_HEAD)
        assert state is not None
        assert not state.is_green
        assert state.run_id == 1

    def test_a_failed_tier_run_is_not_green(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, _FakeGh([_run(1, conclusion="failure")], {1: _TIER_JOBS}))
        state = cli._gh_ci_lookup(_HEAD)
        assert state is not None
        assert not state.is_green

    def test_a_failing_job_listing_raises_so_the_gate_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _FakeGh([_run(1)], {}, view_fails=True))
        with pytest.raises(subprocess.SubprocessError):
            cli._gh_ci_lookup(_HEAD)

    @pytest.mark.parametrize("output", ["not json", "[]", '{"jobs": "x"}'])
    def test_unparseable_job_output_raises_so_the_gate_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, output: str
    ) -> None:
        _install(monkeypatch, _FakeGh([_run(1)], {}, view_output=output))
        with pytest.raises(ValueError):
            cli._gh_ci_lookup(_HEAD)

    def test_a_job_listing_failure_is_a_problem_never_clean(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.core.release_slate import collect_slate

        _install(monkeypatch, _FakeGh([_run(1)], {}, view_fails=True))
        report = collect_slate(
            repo_root=Path("/nonexistent-repo"),
            plan_root=Path("/nonexistent-plans"),
            archive_dir_names=frozenset(),
            run_fn=lambda *a, **k: subprocess.CompletedProcess([], 0, f"{_HEAD}\n", ""),
            ci_lookup=cli._gh_ci_lookup,
        )
        assert not report.head_ci.is_green
        assert report.head_ci.problem


class TestTheSubcommandIsRegistered:
    def test_help_names_the_command_and_both_flags(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The parser is built inside main(); --help proves registration without running it."""
        monkeypatch.setattr("sys.argv", ["hooks-daemon", "release-slate-check", "--help"])
        with pytest.raises(SystemExit) as exit_info:
            cli.main()
        assert exit_info.value.code == 0
        out = capsys.readouterr().out
        assert "--accept" in out
        assert "--json" in out
