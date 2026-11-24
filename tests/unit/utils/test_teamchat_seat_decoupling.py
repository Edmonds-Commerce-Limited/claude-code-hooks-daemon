"""Arm on evidence, not on absence of it (Plan 00474 decoupling, audit R1-R4).

Owner rulings (2026-11-24): duty is a teams-only, optional field; null or
absent duty arms nothing (D1); a coordinator needs ``duty != host``, not a
declared duty (D2); an unreadable probe arms only after this session resolved
a seat earlier (D3); a role null in a resolved seat stays unknown (D5).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

import pytest

from claude_code_hooks_daemon.config.models import TeamSeatConfig
from claude_code_hooks_daemon.utils import teamchat_seat
from claude_code_hooks_daemon.utils.team_role_gate import GateVerdict, duty_gate, role_gate
from claude_code_hooks_daemon.utils.teamchat_seat import (
    CommandOutcome,
    CommandStatus,
    ProbeReason,
    RoleKind,
    SeatContextResolver,
    SeatState,
    SessionSignals,
    parse_whoami,
    reset_shared_resolvers,
    shared_resolver,
)
from tests.support import teamchat as fx

RUNTIME = "/tmp/teamchat/run-a"
SIGNALS = SessionSignals(runtime=RUNTIME, kit="/opt/teamchat-kit")
MAIN: dict[str, object] = {}


class Runner:
    def __init__(self, outcome: CommandOutcome) -> None:
        self.outcome = outcome
        self.calls = 0

    def __call__(
        self, args: Sequence[str], env_overlay: Mapping[str, str], timeout: float
    ) -> CommandOutcome:
        self.calls += 1
        return self.outcome


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _ok(text: str) -> CommandOutcome:
    return CommandOutcome(CommandStatus.OK, text, 0)


FAILED = CommandOutcome(CommandStatus.NOT_FOUND)


# --- R1: a null or absent duty is undeclared, not unknown --------------------------


class TestUndeclaredDuty:
    @pytest.mark.parametrize("duty", [None, ""])
    def test_null_duty_is_not_unknown(self, duty: object) -> None:
        row = fx.seat("alpha", "worker")
        row["duty"] = duty
        context = parse_whoami(fx.whoami(row))
        assert context.duty_unknown() is False

    def test_absent_duty_key_is_not_unknown(self) -> None:
        row = fx.seat("alpha", "worker")
        del row["duty"]
        assert parse_whoami(fx.whoami(row)).duty_unknown() is False

    def test_null_duty_gate_on_host_is_not_applicable(self) -> None:
        context = parse_whoami(fx.whoami(fx.seat("alpha", "worker", duty=None)))
        assert duty_gate(MAIN, context, duty="host").verdict is GateVerdict.NOT_APPLICABLE

    def test_declared_host_still_applies_beside_a_null_duty(self) -> None:
        context = parse_whoami(
            fx.whoami(fx.seat("alpha", "worker", duty="host"), fx.seat("beta", "worker", duty=None))
        )
        assert duty_gate(MAIN, context, duty="host").verdict is GateVerdict.APPLIES

    def test_unresolved_probe_keeps_duty_unknown(self) -> None:
        context = teamchat_seat.SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
        assert context.duty_unknown() is True
        assert duty_gate(MAIN, context, duty="host").verdict is GateVerdict.ROLE_UNKNOWN


# --- R2: a coordinator needs duty != host, not a declared duty ---------------------


class TestCoordinatorWithoutDuty:
    def test_coordinator_with_null_duty_is_declared(self) -> None:
        context = parse_whoami(fx.whoami(fx.seat("alpha", "coordinator", duty=None)))
        answer = context.role_for_team("alpha")
        assert answer.kind is RoleKind.DECLARED
        assert answer.holds_role("coordinator")
        assert role_gate(MAIN, context, team="alpha", role="coordinator").verdict is (
            GateVerdict.APPLIES
        )

    def test_coordinator_with_host_duty_stays_unknown(self) -> None:
        context = parse_whoami(fx.HOST_AS_COORDINATOR)
        assert context.role_for_team("alpha").kind is RoleKind.UNKNOWN

    def test_coordinator_rows_one_host_stays_unknown(self) -> None:
        context = parse_whoami(
            fx.whoami(
                fx.seat("alpha", "coordinator", duty=None),
                fx.seat("alpha", "coordinator", duty="host"),
            )
        )
        assert context.role_for_team("alpha").kind is RoleKind.UNKNOWN

    def test_role_null_stays_unknown(self) -> None:
        """D5: role is a required part of a seat, so null stays unknown (armed)."""
        context = parse_whoami(fx.ROLE_NULL)
        assert context.role_for_team("alpha").kind is RoleKind.UNKNOWN


# --- R3: an unreadable probe arms only after a seat was resolved this session ------


class TestTeamConfirmation:
    def _resolver(self, runner: Runner, clock: Clock) -> SeatContextResolver:
        return SeatContextResolver(ttl_seconds=60, clock=clock, runner=runner)

    def test_failed_probe_never_resolved_reads_as_no_team(self) -> None:
        resolver = self._resolver(Runner(FAILED), Clock())
        context = resolver.resolve(SIGNALS)
        assert context.state is SeatState.ABSENT
        assert context.reason is ProbeReason.TEAM_UNCONFIRMED

    def test_unconfirmed_logs_one_line(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, logger=teamchat_seat.__name__)
        self._resolver(Runner(FAILED), Clock()).resolve(SIGNALS)
        lines = [r for r in caplog.records if "no seat resolved" in r.getMessage()]
        assert len(lines) == 1

    def test_failed_probe_after_a_resolved_seat_stays_unresolved(self) -> None:
        runner, clock = Runner(_ok(fx.WORKER_ONLY)), Clock()
        resolver = self._resolver(runner, clock)
        assert resolver.resolve(SIGNALS).state is SeatState.RESOLVED
        runner.outcome = FAILED
        clock.now += 61
        context = resolver.resolve(SIGNALS)
        assert context.state is SeatState.UNRESOLVED
        assert context.reason is ProbeReason.COMMAND_NOT_FOUND

    def test_confirmation_is_keyed_on_runtime_not_kit(self) -> None:
        runner, clock = Runner(_ok(fx.WORKER_ONLY)), Clock()
        resolver = self._resolver(runner, clock)
        resolver.resolve(SIGNALS)
        runner.outcome = FAILED
        no_kit = SessionSignals(runtime=RUNTIME, kit="")
        assert resolver.resolve(no_kit).state is SeatState.UNRESOLVED

    def test_confirmation_outlives_the_ttl_cache(self) -> None:
        runner, clock = Runner(_ok(fx.WORKER_ONLY)), Clock()
        resolver = self._resolver(runner, clock)
        resolver.resolve(SIGNALS)
        runner.outcome = FAILED
        clock.now += 600
        assert resolver.resolve(SIGNALS).state is SeatState.UNRESOLVED

    @pytest.mark.parametrize(
        "answer",
        [CommandOutcome(CommandStatus.EXITED, "", fx.EXIT_NO_SESSION), _ok(fx.NO_TEAMS)],
    )
    def test_a_definitive_no_team_answer_clears_confirmation(self, answer: CommandOutcome) -> None:
        runner, clock = Runner(_ok(fx.WORKER_ONLY)), Clock()
        resolver = self._resolver(runner, clock)
        resolver.resolve(SIGNALS)
        runner.outcome = answer
        clock.now += 61
        assert resolver.resolve(SIGNALS).state is SeatState.ABSENT
        runner.outcome = FAILED
        clock.now += 61
        assert resolver.resolve(SIGNALS).reason is ProbeReason.TEAM_UNCONFIRMED

    def test_confirmed_memory_is_bounded(self) -> None:
        runner, clock = Runner(_ok(fx.WORKER_ONLY)), Clock()
        resolver = SeatContextResolver(ttl_seconds=60, clock=clock, runner=runner, max_entries=2)
        for index in range(5):
            resolver.resolve(SessionSignals(runtime=f"/tmp/teamchat/run-{index}", kit="/k"))
        assert resolver.confirmed_count() <= 2

    def test_team_confirmed_seam(self) -> None:
        runner = Runner(_ok(fx.WORKER_ONLY))
        resolver = self._resolver(runner, Clock())
        assert resolver.team_confirmed(SIGNALS) is False
        resolver.resolve(SIGNALS)
        assert resolver.team_confirmed(SIGNALS) is True


# --- R4: one shared resolver per team_seat config -------------------------------------


class TestSharedResolver:
    def test_none_and_default_config_share_one_resolver(self) -> None:
        assert shared_resolver(None) is shared_resolver(TeamSeatConfig())

    def test_a_different_ttl_gets_its_own_resolver(self) -> None:
        other = TeamSeatConfig(resolve_ttl_seconds=5)
        assert shared_resolver(other) is not shared_resolver(None)

    def test_detection_off_is_honoured(self) -> None:
        resolver = shared_resolver(TeamSeatConfig(detection="off"))
        assert resolver.resolve(SIGNALS).reason is ProbeReason.DETECTION_OFF

    def test_reset_gives_a_fresh_resolver(self) -> None:
        before = shared_resolver(None)
        reset_shared_resolvers()
        assert shared_resolver(None) is not before


class TestTeamsDeclared:
    """D4: team guidance is written only where the project declares a team."""

    def test_no_block_declares_no_team(self) -> None:
        assert teamchat_seat.teams_declared(None) is False

    def test_the_default_block_declares_no_team(self) -> None:
        assert teamchat_seat.teams_declared(TeamSeatConfig()) is False

    def test_a_declared_team_with_detection_on(self) -> None:
        assert teamchat_seat.teams_declared(TeamSeatConfig(teams_in_use=True)) is True

    def test_detection_off_never_fires_so_declares_nothing(self) -> None:
        config = TeamSeatConfig(teams_in_use=True, detection="off")
        assert teamchat_seat.teams_declared(config) is False

    def test_relevance_names_the_key_either_way(self) -> None:
        assert teamchat_seat.team_seat_relevance(True).applicable is True
        absent = teamchat_seat.team_seat_relevance(False)
        assert absent.applicable is False
        assert "teams_in_use" in absent.reason
