"""The housekeeping pass: a fixed step list whose ORDER and DISPOSITION are the
contract (Plan 00330 Phase 3).

Decision 5: report-only steps first, mutating steps after, `optimise` last
because it restarts the daemon. Decision 6: only the idempotent formatters
(`format-markdown`, `regenerate-docs`) act without confirmation; every other
mutating step reports and acts only on explicit request. Decision 7: the same
step list feeds the routed `housekeeping` command and the idle advisory.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon.cli import main
from claude_code_hooks_daemon.daemon.housekeeping import (
    HOUSEKEEPING_STEPS,
    UNCONFIRMED_STEP_NAMES,
    Disposition,
    HousekeepingStep,
    UnknownStepError,
    mutating_steps,
    plan_pass,
    render_procedure,
    report_only_steps,
    step_names,
)

_REPORT_ONLY_EXPECTED = {
    "plan-qa-sweep",
    "docs-qa-sweep",
    "check-worktree-seed",
    "audit-handler-keys",
    "check-permissions",
    "disk-usage",
    "remote-docs-check",
    "verdicts",
    "block-report",
    "harvest-background",
    "worktree-reap",
    "skill-scan",
}

_MUTATING_EXPECTED = {
    "format-markdown",
    "regenerate-docs",
    "reconcile-settings",
    "remote-docs-refresh",
    "prune-venvs",
    "check-permissions-fix",
    "worktree-reap-reap",
    "optimise",
}


def _parser_accepts(argv: tuple[str, ...]) -> bool:
    """True when argparse recognises the verb (``--help`` exits 0 on a known one)."""
    with patch("sys.argv", ["claude-hooks-daemon", argv[0], "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    return exc_info.value.code == 0


class TestStepList:
    def test_names_are_unique(self) -> None:
        names = step_names()
        assert len(names) == len(set(names))

    def test_the_ruling_step_set_is_present(self) -> None:
        assert set(step_names()) == _REPORT_ONLY_EXPECTED | _MUTATING_EXPECTED

    def test_report_only_steps_never_mutate(self) -> None:
        assert {s.name for s in report_only_steps()} == _REPORT_ONLY_EXPECTED
        assert all(not s.mutates for s in report_only_steps())

    def test_mutating_steps_all_mutate(self) -> None:
        assert {s.name for s in mutating_steps()} == _MUTATING_EXPECTED
        assert all(s.mutates for s in mutating_steps())


class TestOrdering:
    """Decision 5."""

    def test_every_report_only_step_precedes_every_mutating_step(self) -> None:
        flags = [step.mutates for step in HOUSEKEEPING_STEPS]
        first_mutating = flags.index(True)
        assert not any(flags[:first_mutating])
        assert all(flags[first_mutating:])

    def test_optimise_is_last_because_it_restarts_the_daemon(self) -> None:
        last = HOUSEKEEPING_STEPS[-1]
        assert last.name == "optimise"
        assert last.restarts_daemon
        assert [s.name for s in HOUSEKEEPING_STEPS if s.restarts_daemon] == ["optimise"]

    def test_unconfirmed_formatters_run_before_confirmation_gated_steps(self) -> None:
        mutating = [s for s in HOUSEKEEPING_STEPS if s.mutates]
        gated_seen = False
        for step in mutating:
            if step.confirmation_required:
                gated_seen = True
            else:
                assert not gated_seen, f"{step.name} acts unconfirmed but follows a gated step"


class TestDisposition:
    """Decision 6."""

    def test_only_the_idempotent_formatters_act_without_confirmation(self) -> None:
        unconfirmed = {
            s.name for s in HOUSEKEEPING_STEPS if s.mutates and not s.confirmation_required
        }
        assert unconfirmed == {"format-markdown", "regenerate-docs"} == set(UNCONFIRMED_STEP_NAMES)

    def test_report_only_steps_need_no_confirmation(self) -> None:
        assert all(not s.confirmation_required for s in report_only_steps())

    def test_report_only_twins_carry_no_acting_flag(self) -> None:
        by_name = {s.name: s for s in HOUSEKEEPING_STEPS}
        assert "--reap" not in by_name["worktree-reap"].cli_argv
        assert "--fix" not in by_name["check-permissions"].cli_argv
        assert "--reap" in by_name["worktree-reap-reap"].cli_argv
        assert "--fix" in by_name["check-permissions-fix"].cli_argv
        assert by_name["remote-docs-check"].cli_argv == ("remote-docs", "check")
        assert by_name["remote-docs-refresh"].cli_argv == ("remote-docs", "refresh")

    def test_optimise_runs_through_its_existing_skill_entry_point(self) -> None:
        optimise = HOUSEKEEPING_STEPS[-1]
        assert optimise.cli_argv == ()
        assert optimise.via_skill == "optimise"


class TestEveryCliStepIsAVerbTheParserAccepts:
    """A step naming a verb the CLI does not know is the drift this plan exists to stop."""

    @pytest.mark.parametrize(
        "step", [s for s in HOUSEKEEPING_STEPS if s.cli_argv], ids=lambda s: s.name
    )
    def test_verb_is_accepted(self, step: HousekeepingStep) -> None:
        assert _parser_accepts(step.cli_argv), f"{step.name} names unknown verb {step.cli_argv[0]}"


class TestPlanPass:
    def test_default_pass_runs_reports_and_formatters_and_holds_the_rest(self) -> None:
        planned = plan_pass(apply=())
        assert [p.step.name for p in planned] == list(step_names())
        held = {p.step.name for p in planned if p.disposition is Disposition.HELD}
        assert held == _MUTATING_EXPECTED - set(UNCONFIRMED_STEP_NAMES)
        run = {p.step.name for p in planned if p.disposition is Disposition.RUN}
        assert run == _REPORT_ONLY_EXPECTED | set(UNCONFIRMED_STEP_NAMES)

    def test_apply_releases_exactly_the_named_step(self) -> None:
        planned = plan_pass(apply=("prune-venvs",))
        by_name = {p.step.name: p.disposition for p in planned}
        assert by_name["prune-venvs"] is Disposition.RUN
        assert by_name["optimise"] is Disposition.HELD
        assert by_name["worktree-reap-reap"] is Disposition.HELD

    def test_apply_on_a_step_that_needs_no_confirmation_is_a_no_op(self) -> None:
        planned = plan_pass(apply=("plan-qa-sweep", "format-markdown"))
        assert all(
            p.disposition is Disposition.RUN
            for p in planned
            if p.step.name in {"plan-qa-sweep", "format-markdown"}
        )

    def test_unknown_apply_name_is_rejected_with_the_valid_names(self) -> None:
        with pytest.raises(UnknownStepError) as exc_info:
            plan_pass(apply=("nuke-everything",))
        assert "nuke-everything" in str(exc_info.value)
        assert "prune-venvs" in str(exc_info.value)

    def test_plan_never_reorders(self) -> None:
        planned = plan_pass(apply=tuple(_MUTATING_EXPECTED))
        assert [p.step.name for p in planned] == list(step_names())


class TestRenderProcedure:
    def test_names_every_step_in_order_with_its_command(self) -> None:
        text = render_procedure(plan_pass(apply=()), cli="/repo/bin/hooks-daemon")
        positions = [text.index(f"`{name}`") for name in step_names()]
        assert positions == sorted(positions)
        assert "/repo/bin/hooks-daemon plan-qa --sweep" in text
        assert "/repo/bin/hooks-daemon worktree-reap\n" in text or (
            "/repo/bin/hooks-daemon worktree-reap " in text
        )

    def test_held_steps_say_how_to_release_them(self) -> None:
        text = render_procedure(plan_pass(apply=()), cli="bin/hooks-daemon")
        assert "HELD" in text
        assert "--apply prune-venvs" in text

    def test_released_step_is_marked_run(self) -> None:
        text = render_procedure(plan_pass(apply=("prune-venvs",)), cli="bin/hooks-daemon")
        assert "--apply prune-venvs" not in text

    def test_sub_agent_contract_returns_what_changed_not_what_was_read(self) -> None:
        text = render_procedure(plan_pass(apply=()), cli="bin/hooks-daemon")
        assert "CHANGED" in text
        assert "sub-agent" in text.lower()

    def test_optimise_is_invoked_as_the_skill_not_a_slash_command(self) -> None:
        text = render_procedure(plan_pass(apply=("optimise",)), cli="bin/hooks-daemon")
        assert "skill=hooks-daemon, args=optimise" in text
        assert "/hooks-daemon optimise" not in text

    def test_reports_dir_is_named(self) -> None:
        text = render_procedure(
            plan_pass(apply=()), cli="bin/hooks-daemon", reports_dir="untracked/reports"
        )
        assert "untracked/reports" in text
