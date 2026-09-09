"""Plan 00359 — ``bin/hooks-daemon release-slate-check``.

The exit code IS the contract the release skill consumes: 0 means clean and
the pipeline proceeds exactly as before; 2 means something is in flight and a
human decides; 1 means the check could not be made — which must never read as
clean. ``--accept`` records that the human has decided, so the report still
prints but the exit is 0.
"""

from __future__ import annotations

import argparse
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
