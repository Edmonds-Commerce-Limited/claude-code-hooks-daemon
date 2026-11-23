"""Tests for the teamchat v2 role probe (Plan 00631).

The absent case comes first: no membership signal must mean no subprocess, no
file probe, no error and no role -- the "aware, not dependent" promise.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import teamchat_seat
from claude_code_hooks_daemon.utils.teamchat_seat import (
    MEMBERSHIP_ENV_VAR,
    WHOAMI_COMMAND,
    CommandOutcome,
    CommandStatus,
    PathState,
    ProbeReason,
    RoleKind,
    SeatContextResolver,
    SeatState,
    default_command_runner,
    default_path_probe,
    membership_from_environ,
    parse_whoami,
    probe_seat_context,
)
from tests.support import teamchat as fx

MEMBERSHIP = "/run/teamchat/session-a"


class FakeRunner:
    """Records each call; answers with a fixed outcome."""

    def __init__(self, outcome: CommandOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[tuple[str, ...], dict[str, str], float]] = []

    def __call__(
        self, args: Sequence[str], env_overlay: Mapping[str, str], timeout: float
    ) -> CommandOutcome:
        self.calls.append((tuple(args), dict(env_overlay), timeout))
        return self.outcome


class FakePaths:
    def __init__(self, state: PathState = PathState.PRESENT) -> None:
        self.state = state
        self.probed: list[Path] = []

    def __call__(self, path: Path) -> PathState:
        self.probed.append(path)
        return self.state


def ok(stdout: str) -> FakeRunner:
    return FakeRunner(CommandOutcome(CommandStatus.OK, stdout))


def probe(stdout: str, *, paths: FakePaths | None = None) -> teamchat_seat.SeatContext:
    return probe_seat_context(MEMBERSHIP, runner=ok(stdout), path_probe=paths or FakePaths())


# --- absent ---------------------------------------------------------------


class TestAbsent:
    @pytest.mark.parametrize("membership", ["", "   "])
    def test_no_signal_is_absent_and_touches_nothing(self, membership: str) -> None:
        runner, paths = ok(fx.COORDINATOR_ONLY), FakePaths()
        context = probe_seat_context(membership, runner=runner, path_probe=paths)
        assert context.state is SeatState.ABSENT
        assert context.reason is ProbeReason.NO_MEMBERSHIP_SIGNAL
        assert context.teams_held() == ()
        assert runner.calls == []
        assert paths.probed == []

    def test_detection_off_is_absent_even_with_signal(self) -> None:
        runner, paths = ok(fx.COORDINATOR_ONLY), FakePaths()
        context = probe_seat_context(
            MEMBERSHIP, detection_enabled=False, runner=runner, path_probe=paths
        )
        assert context.state is SeatState.ABSENT
        assert context.reason is ProbeReason.DETECTION_OFF
        assert runner.calls == []

    def test_absent_answers_no_team_for_any_team(self) -> None:
        answer = probe_seat_context("", runner=ok(""), path_probe=FakePaths()).role_for_team("a")
        assert answer.kind is RoleKind.NO_TEAM
        assert answer.guards_armed is False
        assert answer.holds_role("coordinator") is False

    def test_absent_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger=teamchat_seat.__name__)
        probe_seat_context("", runner=ok(""), path_probe=FakePaths())
        assert caplog.records == []

    def test_membership_from_environ(self) -> None:
        assert membership_from_environ({}) == ""
        assert membership_from_environ({MEMBERSHIP_ENV_VAR: MEMBERSHIP}) == MEMBERSHIP


# --- degraded: present but unreadable -> unknown, armed -------------------


class TestDegraded:
    @pytest.mark.parametrize(
        ("state", "reason"),
        [
            (PathState.MISSING, ProbeReason.MEMBERSHIP_MISSING),
            (PathState.UNREADABLE, ProbeReason.MEMBERSHIP_UNREADABLE),
        ],
    )
    def test_membership_path_problem_is_unknown(
        self, state: PathState, reason: ProbeReason
    ) -> None:
        runner = ok(fx.COORDINATOR_ONLY)
        context = probe_seat_context(MEMBERSHIP, runner=runner, path_probe=FakePaths(state))
        assert context.state is SeatState.UNRESOLVED
        assert context.reason is reason
        assert runner.calls == []

    def test_relative_membership_is_unknown(self) -> None:
        context = probe_seat_context("relative/x", runner=ok(""), path_probe=FakePaths())
        assert context.reason is ProbeReason.MEMBERSHIP_NOT_A_PATH

    @pytest.mark.parametrize("membership", ["/x/alpha/token", "/x/token/membership"])
    def test_token_path_is_never_probed(self, membership: str) -> None:
        paths, runner = FakePaths(), ok(fx.COORDINATOR_ONLY)
        context = probe_seat_context(membership, runner=runner, path_probe=paths)
        assert context.reason is ProbeReason.CREDENTIAL_PATH_REFUSED
        assert paths.probed == []
        assert runner.calls == []

    @pytest.mark.parametrize(
        ("status", "reason"),
        [
            (CommandStatus.NOT_FOUND, ProbeReason.COMMAND_NOT_FOUND),
            (CommandStatus.TIMEOUT, ProbeReason.COMMAND_TIMEOUT),
            (CommandStatus.FAILED, ProbeReason.COMMAND_FAILED),
        ],
    )
    def test_command_failure_is_unknown(self, status: CommandStatus, reason: ProbeReason) -> None:
        context = probe_seat_context(
            MEMBERSHIP, runner=FakeRunner(CommandOutcome(status)), path_probe=FakePaths()
        )
        assert context.state is SeatState.UNRESOLVED
        assert context.reason is reason

    @pytest.mark.parametrize(
        ("stdout", "reason"),
        [
            (fx.NOT_JSON, ProbeReason.NOT_JSON),
            (fx.FUTURE_VERSION, ProbeReason.VERSION_MISMATCH),
            (fx.SEATS_NOT_A_LIST, ProbeReason.SHAPE_MISMATCH),
            (fx.ROW_WITHOUT_TEAM, ProbeReason.SHAPE_MISMATCH),
            (fx.NO_SEATS, ProbeReason.NO_SEATS),
            ('"a string"', ProbeReason.SHAPE_MISMATCH),
            ('{"v": true, "seats": []}', ProbeReason.VERSION_MISMATCH),
        ],
    )
    def test_bad_document_is_unknown(self, stdout: str, reason: ProbeReason) -> None:
        context = probe(stdout)
        assert context.state is SeatState.UNRESOLVED
        assert context.reason is reason

    def test_unresolved_answers_unknown_and_armed_for_any_team(self) -> None:
        answer = probe(fx.NOT_JSON).role_for_team("anything")
        assert answer.kind is RoleKind.UNKNOWN
        assert answer.guards_armed is True
        assert answer.holds_role("coordinator") is False

    def test_degraded_log_carries_reason_not_output(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger=teamchat_seat.__name__)
        probe('{"v": 99, "token": "SYNTHETIC-SECRET-VALUE"}')
        text = caplog.text
        assert "version_mismatch" in text
        assert "SYNTHETIC-SECRET-VALUE" not in text


# --- roles ----------------------------------------------------------------


class TestRoles:
    def test_worker(self) -> None:
        answer = probe(fx.WORKER_ONLY).role_for_team("alpha")
        assert answer.kind is RoleKind.DECLARED
        assert answer.role == "worker"
        assert answer.holds_role("worker")
        assert not answer.holds_role("coordinator")
        assert answer.guards_armed is True

    def test_coordinator(self) -> None:
        assert probe(fx.COORDINATOR_ONLY).role_for_team("alpha").holds_role("coordinator")

    def test_multi_team_roles_are_per_team(self) -> None:
        context = probe(fx.MULTI_TEAM)
        assert context.state is SeatState.RESOLVED
        assert context.teams_held() == ("alpha", "beta")
        assert context.role_for_team("alpha").role == "coordinator"
        assert context.role_for_team("beta").role == "worker"

    def test_team_not_held_is_no_seat(self) -> None:
        answer = probe(fx.MULTI_TEAM).role_for_team("gamma")
        assert answer.kind is RoleKind.NO_SEAT
        assert answer.holds_role("coordinator") is False

    def test_unknown_declared_role_passes_through_and_matches_nothing_known(self) -> None:
        answer = probe(fx.UNKNOWN_ROLE).role_for_team("alpha")
        assert answer.kind is RoleKind.DECLARED
        assert answer.role == "deployer"
        assert answer.duty == "host"
        assert not answer.holds_role("coordinator")
        assert not answer.holds_role("worker")

    def test_holds_role_is_case_insensitive(self) -> None:
        context = probe(fx.whoami(fx.seat("alpha", "Coordinator")))
        assert context.role_for_team("alpha").holds_role("coordinator")

    def test_duty_and_handle_are_carried(self) -> None:
        context = probe(
            fx.whoami(fx.seat("alpha", "worker", handle="@r.2+local.host:x", duty="deploy"))
        )
        seat = context.seats[0]
        assert seat.handle == "@r.2+local.host:x"
        assert seat.duty == "deploy"

    def test_extra_fields_ignored_and_secret_never_kept(self) -> None:
        context = probe(fx.EXTRA_FIELDS)
        assert context.role_for_team("alpha").holds_role("coordinator")
        assert "SYNTHETIC-SECRET-VALUE" not in repr(context)

    def test_version_absent_is_accepted(self) -> None:
        stdout = '{"seats": [{"team": "alpha", "role": "worker"}]}'
        assert probe(stdout).role_for_team("alpha").holds_role("worker")

    def test_bare_list_of_rows_is_accepted(self) -> None:
        stdout = '[{"team": "alpha", "role": "worker"}]'
        assert probe(stdout).role_for_team("alpha").holds_role("worker")

    @pytest.mark.parametrize(
        "stdout",
        [fx.CONFLICTING_ROWS, fx.ROLE_NOT_A_STRING, fx.ROLE_WITH_CONTROL_CHARACTERS],
    )
    def test_bad_role_makes_that_team_unknown(self, stdout: str) -> None:
        answer = probe(stdout).role_for_team("alpha")
        assert answer.kind is RoleKind.UNKNOWN
        assert answer.guards_armed is True

    def test_bad_role_in_one_team_leaves_other_team_resolved(self) -> None:
        stdout = fx.whoami(fx.seat("alpha", 7), fx.seat("beta", "coordinator"))
        context = probe(stdout)
        assert context.role_for_team("alpha").kind is RoleKind.UNKNOWN
        assert context.role_for_team("beta").holds_role("coordinator")

    def test_duplicate_rows_agreeing_resolve(self) -> None:
        stdout = fx.whoami(fx.seat("alpha", "worker"), fx.seat("alpha", "worker"))
        context = probe(stdout)
        assert context.teams_held() == ("alpha",)
        assert context.role_for_team("alpha").holds_role("worker")

    def test_bad_handle_and_duty_are_dropped_not_fatal(self) -> None:
        stdout = fx.whoami(fx.seat("alpha", "worker", handle="bad handle\n", duty=["x"]))
        answer = probe(stdout).role_for_team("alpha")
        assert answer.holds_role("worker")
        assert answer.duty == ""

    def test_missing_role_key_is_unknown(self) -> None:
        answer = probe('{"v": 1, "seats": [{"team": "alpha"}]}').role_for_team("alpha")
        assert answer.kind is RoleKind.UNKNOWN

    def test_parse_whoami_direct(self) -> None:
        assert parse_whoami(fx.WORKER_ONLY).state is SeatState.RESOLVED


# --- subprocess call shape --------------------------------------------------


class TestCommandCall:
    def test_whoami_gets_the_session_membership_and_a_timeout(self) -> None:
        runner = ok(fx.WORKER_ONLY)
        probe_seat_context(MEMBERSHIP, runner=runner, path_probe=FakePaths(), timeout=1.5)
        assert runner.calls == [(WHOAMI_COMMAND, {MEMBERSHIP_ENV_VAR: MEMBERSHIP}, 1.5)]

    def test_command_never_names_token(self) -> None:
        assert all("token" not in part for part in WHOAMI_COMMAND)


class TestDefaultSeams:
    def test_runner_not_found(self) -> None:
        outcome = default_command_runner(("teamchat-does-not-exist-00631",), {}, 1.0)
        assert outcome.status is CommandStatus.NOT_FOUND

    def test_runner_ok_and_env_overlay(self) -> None:
        outcome = default_command_runner(
            ("sh", "-c", f'printf %s "${MEMBERSHIP_ENV_VAR}"'), {MEMBERSHIP_ENV_VAR: "/m"}, 5.0
        )
        assert outcome.status is CommandStatus.OK
        assert outcome.stdout == "/m"

    def test_runner_nonzero_exit_is_failed(self) -> None:
        assert default_command_runner(("false",), {}, 5.0).status is CommandStatus.FAILED

    def test_runner_timeout(self) -> None:
        assert default_command_runner(("sleep", "5"), {}, 0.1).status is CommandStatus.TIMEOUT

    def test_path_probe(self, tmp_path: Path) -> None:
        assert default_path_probe(tmp_path) is PathState.PRESENT
        assert default_path_probe(tmp_path / "nope") is PathState.MISSING

    def test_path_probe_unreadable(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        def denied(self: Path) -> bool:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "exists", denied)
        assert default_path_probe(tmp_path / "x") is PathState.UNREADABLE


# --- TTL cache ---------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestResolver:
    def _resolver(self, runner: FakeRunner, clock: Clock) -> SeatContextResolver:
        return SeatContextResolver(
            ttl_seconds=60, clock=clock, runner=runner, path_probe=FakePaths()
        )

    def test_role_change_lands_within_one_ttl(self) -> None:
        runner, clock = ok(fx.WORKER_ONLY), Clock()
        resolver = self._resolver(runner, clock)
        assert resolver.resolve(MEMBERSHIP).role_for_team("alpha").holds_role("worker")
        runner.outcome = CommandOutcome(CommandStatus.OK, fx.COORDINATOR_ONLY)
        clock.now += 30
        assert resolver.resolve(MEMBERSHIP).role_for_team("alpha").holds_role("worker")
        assert len(runner.calls) == 1
        clock.now += 31
        assert resolver.resolve(MEMBERSHIP).role_for_team("alpha").holds_role("coordinator")
        assert len(runner.calls) == 2

    def test_cache_is_keyed_by_membership(self) -> None:
        runner, clock = ok(fx.WORKER_ONLY), Clock()
        resolver = self._resolver(runner, clock)
        resolver.resolve(MEMBERSHIP)
        resolver.resolve("/run/teamchat/session-b")
        assert len(runner.calls) == 2

    def test_absent_is_not_cached_and_runs_nothing(self) -> None:
        runner, clock = ok(fx.WORKER_ONLY), Clock()
        resolver = self._resolver(runner, clock)
        assert resolver.resolve("").state is SeatState.ABSENT
        assert runner.calls == []

    def test_detection_off(self) -> None:
        runner = ok(fx.WORKER_ONLY)
        resolver = SeatContextResolver(
            ttl_seconds=60, clock=Clock(), runner=runner, path_probe=FakePaths()
        )
        assert resolver.resolve(MEMBERSHIP, detection_enabled=False).state is SeatState.ABSENT
        assert runner.calls == []


# --- invariants ---------------------------------------------------------------


class TestInvariants:
    def test_module_has_no_v1_path(self) -> None:
        source = inspect.getsource(teamchat_seat).lower()
        assert "pingbus" not in source

    def test_module_opens_no_file(self) -> None:
        source = inspect.getsource(teamchat_seat)
        for opener in ("open(", "read_text(", "read_bytes("):
            assert opener not in source
