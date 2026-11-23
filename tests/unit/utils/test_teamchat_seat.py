"""Tests for the teamchat v2 role probe (Plan 00631).

The absent cases come first: no ``TEAMCHAT_RUNTIME``, ``whoami`` exit 69 and
an empty ``teams`` list must all mean no team -- no error, no role, no log
line -- the "aware, not dependent" promise.
"""

from __future__ import annotations

import builtins
import logging
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import TeamSeatConfig
from claude_code_hooks_daemon.utils import teamchat_seat
from claude_code_hooks_daemon.utils.teamchat_seat import (
    KIT_ENV_VAR,
    RUNTIME_ENV_VAR,
    UNKNOWN,
    CommandOutcome,
    CommandStatus,
    ProbeReason,
    RoleKind,
    SeatContextResolver,
    SeatState,
    SessionSignals,
    default_command_runner,
    parse_whoami,
    probe_seat_context,
    whoami_argv,
)
from tests.support import teamchat as fx

RUNTIME = "/tmp/teamchat/run-a"
KIT = "/opt/teamchat-kit"
SIGNALS = SessionSignals(runtime=RUNTIME, kit=KIT)


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


def ok(stdout: str) -> FakeRunner:
    return FakeRunner(CommandOutcome(CommandStatus.OK, stdout, 0))


def exited(code: int, stdout: str = "") -> FakeRunner:
    return FakeRunner(CommandOutcome(CommandStatus.EXITED, stdout, code))


def probe(stdout: str) -> teamchat_seat.SeatContext:
    return probe_seat_context(SIGNALS, runner=ok(stdout))


# --- absent ---------------------------------------------------------------


class TestAbsent:
    @pytest.mark.parametrize("runtime", ["", "   "])
    def test_no_runtime_is_absent_and_runs_nothing(self, runtime: str) -> None:
        runner = ok(fx.COORDINATOR_ONLY)
        signals = SessionSignals.from_environ({RUNTIME_ENV_VAR: runtime, KIT_ENV_VAR: KIT})
        context = probe_seat_context(signals, runner=runner)
        assert context.state is SeatState.ABSENT
        assert context.reason is ProbeReason.NO_RUNTIME_SIGNAL
        assert context.teams_held() == ()
        assert runner.calls == []

    def test_detection_off_is_absent_even_with_signal(self) -> None:
        runner = ok(fx.COORDINATOR_ONLY)
        context = probe_seat_context(SIGNALS, detection_enabled=False, runner=runner)
        assert context.state is SeatState.ABSENT
        assert context.reason is ProbeReason.DETECTION_OFF
        assert runner.calls == []

    def test_exit_69_is_no_team_not_an_error(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger=teamchat_seat.__name__)
        context = probe_seat_context(SIGNALS, runner=exited(fx.EXIT_NO_SESSION, fx.WORKER_ONLY))
        assert context.state is SeatState.ABSENT
        assert context.reason is ProbeReason.NO_SESSION
        assert context.teams_held() == ()
        assert caplog.records == []

    def test_empty_teams_is_absent(self) -> None:
        context = probe(fx.NO_TEAMS)
        assert context.state is SeatState.ABSENT
        assert context.reason is ProbeReason.NO_TEAMS

    def test_absent_answers_no_team_for_any_team(self) -> None:
        context = probe_seat_context(SessionSignals(), runner=ok(""))
        answer = context.role_for_team("a")
        assert answer.kind is RoleKind.NO_TEAM
        assert answer.guards_armed is False
        assert answer.holds_role("coordinator") is False
        assert context.role_in("a") is None
        assert context.duty_in("a") is None
        assert context.any_duty("coordinator") is False
        assert context.duty_unknown() is False

    def test_absent_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger=teamchat_seat.__name__)
        probe_seat_context(SessionSignals(), runner=ok(""))
        assert caplog.records == []

    def test_signals_from_environ(self) -> None:
        assert SessionSignals.from_environ({}) == SessionSignals()
        environ = {RUNTIME_ENV_VAR: f" {RUNTIME} ", KIT_ENV_VAR: KIT, "OTHER": "x"}
        assert SessionSignals.from_environ(environ) == SIGNALS

    def test_signals_from_hook_input(self) -> None:
        """The daemon reads the SESSION's signals from the stamped payload fields."""
        payload = {
            "hook_event_name": "Stop",
            "teamchat_runtime": f" {RUNTIME} ",
            "teamchat_kit": KIT,
        }
        assert SessionSignals.from_hook_input(payload) == SIGNALS
        assert SessionSignals.from_hook_input({"hook_event_name": "Stop"}) == SessionSignals()

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            ["teamchat_runtime"],
            "teamchat_runtime",
            {"teamchat_runtime": 7, "teamchat_kit": KIT},
            {"teamchat_runtime": RUNTIME, "teamchat_kit": ["x"]},
        ],
    )
    def test_signals_from_a_malformed_payload_never_raise(self, payload: Any) -> None:
        signals = SessionSignals.from_hook_input(payload)
        assert isinstance(signals, SessionSignals)
        if isinstance(payload, dict) and isinstance(payload.get("teamchat_runtime"), str):
            assert signals == SessionSignals(runtime=RUNTIME)
        else:
            assert signals.runtime == ""

    def test_v2_only_ignores_pingbus_off(self) -> None:
        """A v2 launch sets PINGBUS_MEMBERSHIP=off; the answer comes from whoami alone."""
        environ = {"PINGBUS_MEMBERSHIP": "off", RUNTIME_ENV_VAR: RUNTIME, KIT_ENV_VAR: KIT}
        context = probe_seat_context(
            SessionSignals.from_environ(environ), runner=ok(fx.WORKER_ONLY)
        )
        assert context.role_in("alpha") == "worker"


# --- no answer: present but unreadable -> unknown, armed ---------------------


class TestNoAnswer:
    def test_kit_missing_is_unknown_and_runs_nothing(self) -> None:
        runner = ok(fx.COORDINATOR_ONLY)
        context = probe_seat_context(SessionSignals(runtime=RUNTIME), runner=runner)
        assert context.state is SeatState.UNRESOLVED
        assert context.reason is ProbeReason.KIT_MISSING
        assert runner.calls == []

    @pytest.mark.parametrize(
        "signals",
        [
            SessionSignals(runtime="relative/run", kit=KIT),
            SessionSignals(runtime=RUNTIME, kit="kit"),
        ],
    )
    def test_relative_signal_is_unknown(self, signals: SessionSignals) -> None:
        runner = ok(fx.COORDINATOR_ONLY)
        context = probe_seat_context(signals, runner=runner)
        assert context.reason is ProbeReason.SIGNAL_NOT_A_PATH
        assert runner.calls == []

    @pytest.mark.parametrize(
        ("outcome", "reason"),
        [
            (CommandOutcome(CommandStatus.NOT_FOUND), ProbeReason.COMMAND_NOT_FOUND),
            (CommandOutcome(CommandStatus.TIMEOUT), ProbeReason.COMMAND_TIMEOUT),
            (
                CommandOutcome(CommandStatus.EXITED, exit_code=fx.EXIT_UNREADABLE),
                ProbeReason.SEAT_UNREADABLE,
            ),
            (CommandOutcome(CommandStatus.EXITED, exit_code=1), ProbeReason.COMMAND_FAILED),
            (CommandOutcome(CommandStatus.EXITED, exit_code=None), ProbeReason.COMMAND_FAILED),
        ],
    )
    def test_command_failure_is_unknown(self, outcome: CommandOutcome, reason: ProbeReason) -> None:
        context = probe_seat_context(SIGNALS, runner=FakeRunner(outcome))
        assert context.state is SeatState.UNRESOLVED
        assert context.reason is reason

    @pytest.mark.parametrize(
        ("stdout", "reason"),
        [
            (fx.NOT_JSON, ProbeReason.NOT_JSON),
            (fx.FUTURE_VERSION, ProbeReason.VERSION_MISMATCH),
            (fx.NO_VERSION, ProbeReason.VERSION_MISMATCH),
            ('{"v": true, "teams": []}', ProbeReason.VERSION_MISMATCH),
            ('{"v": "1", "teams": []}', ProbeReason.VERSION_MISMATCH),
            (fx.TEAMS_NOT_A_LIST, ProbeReason.SHAPE_MISMATCH),
            (fx.BARE_LIST, ProbeReason.SHAPE_MISMATCH),
            (fx.ROW_WITHOUT_TEAM, ProbeReason.SHAPE_MISMATCH),
            ('{"v": 1, "seats": []}', ProbeReason.SHAPE_MISMATCH),
            ('"a string"', ProbeReason.SHAPE_MISMATCH),
        ],
    )
    def test_bad_document_is_unknown(self, stdout: str, reason: ProbeReason) -> None:
        context = probe(stdout)
        assert context.state is SeatState.UNRESOLVED
        assert context.reason is reason

    def test_unresolved_answers_unknown_and_armed_for_any_team(self) -> None:
        context = probe(fx.NOT_JSON)
        answer = context.role_for_team("anything")
        assert answer.kind is RoleKind.UNKNOWN
        assert answer.guards_armed is True
        assert answer.holds_role("coordinator") is False
        assert context.role_in("anything") == UNKNOWN
        assert context.duty_in("anything") == UNKNOWN
        assert context.any_duty("host") is False
        assert context.duty_unknown() is True

    def test_no_answer_log_carries_reason_not_output(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG, logger=teamchat_seat.__name__)
        probe('{"v": 99, "password": "SYNTHETIC-SECRET-VALUE"}')
        text = caplog.text
        assert "version_mismatch" in text
        assert "SYNTHETIC-SECRET-VALUE" not in text


# --- hostile output: never raises, always unknown (review F1) -----------------------


class TestHostileOutput:
    def test_deep_nesting_never_raises(self) -> None:
        context = parse_whoami("[" * 200000)
        assert context.state is SeatState.UNRESOLVED

    def test_depth_guard_rejects_a_small_deep_document(self) -> None:
        text = '{"v": 1, "teams": ' + "[" * 40 + "]" * 40 + "}"
        context = parse_whoami(text)
        assert context.state is SeatState.UNRESOLVED
        assert context.reason is ProbeReason.NOT_JSON

    def test_brackets_inside_strings_do_not_count_as_depth(self) -> None:
        deep_text = "[" * 200 + '\\"{' * 50
        context = parse_whoami(fx.whoami(fx.seat("alpha", "worker"), note=deep_text))
        assert context.role_for_team("alpha").holds_role("worker")

    def test_recursion_error_from_the_decoder_is_caught(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*_args: Any, **_kwargs: Any) -> Any:
            raise RecursionError("maximum recursion depth exceeded")

        monkeypatch.setattr(teamchat_seat.json, "loads", explode)
        context = parse_whoami(fx.WORKER_ONLY)
        assert context.state is SeatState.UNRESOLVED
        assert context.reason is ProbeReason.NOT_JSON

    def test_oversized_output_is_unknown(self) -> None:
        padding = "x" * teamchat_seat.MAX_OUTPUT_BYTES
        context = parse_whoami(fx.whoami(fx.seat("alpha", "worker"), pad=padding))
        assert context.state is SeatState.UNRESOLVED
        assert context.reason is ProbeReason.OUTPUT_TOO_LARGE

    def test_probe_of_deep_output_never_raises(self) -> None:
        context = probe("[" * 200000)
        assert context.state is SeatState.UNRESOLVED


# --- roles and duties ------------------------------------------------------------


class TestRolesAndDuties:
    def test_worker(self) -> None:
        context = probe(fx.WORKER_ONLY)
        answer = context.role_for_team("alpha")
        assert answer.kind is RoleKind.DECLARED
        assert answer.holds_role("worker")
        assert not answer.holds_role("coordinator")
        assert answer.guards_armed is True
        assert context.role_in("alpha") == "worker"
        assert context.duty_in("alpha") == "worker"

    def test_coordinator(self) -> None:
        context = probe(fx.COORDINATOR_ONLY)
        assert context.role_for_team("alpha").holds_role("coordinator")
        assert context.any_duty("coordinator") is True

    def test_multi_team_roles_are_per_team(self) -> None:
        context = probe(fx.MULTI_TEAM)
        assert context.state is SeatState.RESOLVED
        assert context.teams_held() == ("alpha", "beta")
        assert context.role_in("alpha") == "coordinator"
        assert context.role_in("beta") == "worker"

    def test_team_not_held(self) -> None:
        context = probe(fx.MULTI_TEAM)
        assert context.role_for_team("gamma").kind is RoleKind.NO_SEAT
        assert context.role_in("gamma") is None
        assert context.duty_in("gamma") is None

    def test_host_duty_in_one_team(self) -> None:
        context = probe(fx.HOST_DUTY)
        assert context.duty_in("alpha") == "host"
        assert context.duty_in("beta") == "worker"
        assert context.any_duty("host") is True
        assert context.any_duty("coordinator") is False

    def test_host_is_never_coordinator(self) -> None:
        context = probe(fx.HOST_AS_COORDINATOR)
        answer = context.role_for_team("alpha")
        assert answer.kind is RoleKind.UNKNOWN
        assert answer.guards_armed is True
        assert not answer.holds_role("coordinator")
        assert context.any_duty("coordinator") is False
        assert context.duty_in("alpha") == "host"

    @pytest.mark.parametrize(
        "rows",
        [
            # Review F2: a host row merged with a null-duty row.
            [("alpha", "host"), ("alpha", None)],
            # Review F2: a duty that fails the grammar might be host.
            [("alpha", "Host!")],
            [("alpha", None)],
            [("alpha", " HOST ")],
            [("alpha", "Host")],
            [("alpha", "coordinator"), ("alpha", "host")],
            [("alpha", "coordinator"), ("alpha", "worker")],
            [("alpha", ["host"])],
            # A host row under another spelling of the same team name.
            [("Alpha", "host"), ("alpha", "coordinator")],
            [(" alpha", "host"), ("alpha", "coordinator")],
        ],
    )
    def test_coordinator_needs_a_readable_non_host_duty(self, rows: list[tuple[str, Any]]) -> None:
        seats = [fx.seat(team, "coordinator", duty=duty) for team, duty in rows]
        context = probe(fx.whoami(*seats))
        answer = context.role_for_team("alpha")
        assert answer.kind is RoleKind.UNKNOWN
        assert not answer.holds_role("coordinator")
        assert answer.guards_armed is True

    @pytest.mark.parametrize("duty", ["host", " host ", "HOST", "Host"])
    def test_any_host_row_makes_the_team_host(self, duty: str) -> None:
        context = probe(
            fx.whoami(
                fx.seat("alpha", "worker", duty="worker"), fx.seat("alpha", "worker", duty=duty)
            )
        )
        assert context.duty_in("alpha") == "host"
        assert context.any_duty("host") is True
        assert context.role_for_team("alpha").holds_role("worker")

    def test_conflicting_non_host_duties_are_unknown(self) -> None:
        context = probe(
            fx.whoami(
                fx.seat("alpha", "worker", duty="worker"),
                fx.seat("alpha", "worker", duty="reviewer"),
            )
        )
        assert context.duty_in("alpha") == UNKNOWN
        assert context.duty_unknown() is True

    def test_role_and_duty_are_normalised(self) -> None:
        context = probe(fx.whoami(fx.seat("alpha", " Worker ", duty=" WORKER")))
        assert context.role_in("alpha") == "worker"
        assert context.duty_in("alpha") == "worker"

    def test_team_names_match_case_insensitively(self) -> None:
        """Review F9: a caller's ``Alpha`` finds teamchat's ``alpha``."""
        context = probe(fx.whoami(fx.seat("Alpha", "coordinator")))
        assert context.teams_held() == ("alpha",)
        for team in ("alpha", "ALPHA", " Alpha "):
            assert context.role_for_team(team).holds_role("coordinator")
            assert context.role_in(team) == "coordinator"
            assert context.duty_in(team) == "coordinator"

    def test_team_spellings_merge_into_one_team(self) -> None:
        context = probe(fx.whoami(fx.seat("Alpha", "worker"), fx.seat("alpha", "worker")))
        assert context.teams_held() == ("alpha",)
        assert context.duplicate_teams == ("alpha",)

    def test_role_null_is_unknown(self) -> None:
        context = probe(fx.ROLE_NULL)
        assert context.role_for_team("alpha").kind is RoleKind.UNKNOWN
        assert context.role_in("alpha") == UNKNOWN
        assert context.duty_in("alpha") == UNKNOWN
        assert context.duty_unknown() is True

    def test_probe_role_switches_nothing_on(self) -> None:
        answer = probe(fx.ROLE_PROBE).role_for_team("alpha")
        assert answer.role == "probe"
        assert not answer.holds_role("coordinator")
        assert not answer.holds_role("worker")

    def test_unknown_duty_switches_nothing_on(self) -> None:
        context = probe(fx.UNKNOWN_DUTY)
        assert context.duty_in("alpha") == "reviewer"
        for duty in ("coordinator", "worker", "host"):
            assert context.any_duty(duty) is False

    def test_role_outside_wire_set_is_declared_and_inert(self) -> None:
        answer = probe(fx.whoami(fx.seat("alpha", "deployer", duty="worker"))).role_for_team(
            "alpha"
        )
        assert answer.kind is RoleKind.DECLARED
        assert not answer.holds_role("coordinator")

    def test_holds_role_and_any_duty_are_case_insensitive(self) -> None:
        context = probe(fx.whoami(fx.seat("alpha", "Coordinator", duty="Coordinator")))
        assert context.role_for_team("alpha").holds_role("coordinator")
        assert context.any_duty("coordinator")

    def test_handle_is_carried(self) -> None:
        context = probe(fx.whoami(fx.seat("alpha", "worker", handle="@r.2+local.host:x")))
        assert context.seats[0].handle == "@r.2+local.host:x"

    def test_extra_keys_ignored_and_secret_never_kept(self) -> None:
        context = probe(fx.EXTRA_FIELDS)
        assert context.role_for_team("alpha").holds_role("coordinator")
        assert "SYNTHETIC-SECRET-VALUE" not in repr(context)

    @pytest.mark.parametrize(
        "stdout",
        [fx.CONFLICTING_ROWS, fx.ROLE_NOT_A_STRING, fx.ROLE_WITH_CONTROL_CHARACTERS],
    )
    def test_bad_role_makes_that_team_unknown(self, stdout: str) -> None:
        answer = probe(stdout).role_for_team("alpha")
        assert answer.kind is RoleKind.UNKNOWN
        assert answer.guards_armed is True

    def test_team_listed_twice_is_flagged(self) -> None:
        context = probe(fx.CONFLICTING_ROWS)
        assert context.duplicate_teams == ("alpha",)
        assert probe(fx.MULTI_TEAM).duplicate_teams == ()

    def test_bad_role_in_one_team_leaves_other_team_resolved(self) -> None:
        context = probe(fx.whoami(fx.seat("alpha", 7), fx.seat("beta", "coordinator")))
        assert context.role_for_team("alpha").kind is RoleKind.UNKNOWN
        assert context.role_for_team("beta").holds_role("coordinator")

    def test_duplicate_rows_agreeing_resolve(self) -> None:
        context = probe(fx.whoami(fx.seat("alpha", "worker"), fx.seat("alpha", "worker")))
        assert context.teams_held() == ("alpha",)
        assert context.role_for_team("alpha").holds_role("worker")
        assert context.duplicate_teams == ("alpha",)

    def test_bad_handle_and_duty_are_dropped_not_fatal(self) -> None:
        context = probe(fx.whoami(fx.seat("alpha", "worker", handle="bad handle\n", duty=["x"])))
        assert context.role_for_team("alpha").holds_role("worker")
        assert context.duty_in("alpha") == UNKNOWN

    def test_missing_role_key_is_unknown(self) -> None:
        answer = probe('{"v": 1, "teams": [{"team": "alpha"}]}').role_for_team("alpha")
        assert answer.kind is RoleKind.UNKNOWN

    def test_parse_whoami_direct(self) -> None:
        assert parse_whoami(fx.WORKER_ONLY).state is SeatState.RESOLVED


# --- subprocess call shape --------------------------------------------------


class TestCommandCall:
    def test_whoami_is_the_kit_binary_with_the_session_runtime(self) -> None:
        runner = ok(fx.WORKER_ONLY)
        probe_seat_context(SIGNALS, runner=runner, timeout=1.5)
        assert runner.calls == [
            ((f"{KIT}/bin/teamchat", "whoami", "--json"), {RUNTIME_ENV_VAR: RUNTIME}, 1.5)
        ]

    def test_argv_tolerates_trailing_slash(self) -> None:
        assert whoami_argv(f"{KIT}/")[0] == f"{KIT}/bin/teamchat"

    def test_command_never_names_the_credential(self) -> None:
        assert all("password" not in part for part in whoami_argv(KIT))


class TestDefaultRunner:
    def test_not_found(self) -> None:
        outcome = default_command_runner(("/nonexistent-00631/bin/teamchat",), {}, 1.0)
        assert outcome.status is CommandStatus.NOT_FOUND

    def test_ok_and_env_overlay(self) -> None:
        outcome = default_command_runner(
            ("sh", "-c", f'printf %s "${RUNTIME_ENV_VAR}"'), {RUNTIME_ENV_VAR: "/m"}, 5.0
        )
        assert outcome.status is CommandStatus.OK
        assert outcome.stdout == "/m"

    def test_env_is_an_allowlist_not_the_daemons_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Review F3: the daemon's own (possibly stale) teamchat seat must not leak."""
        monkeypatch.setenv("TEAMCHAT_HANDLE", "@stale.1+local.x:old")
        monkeypatch.setenv(KIT_ENV_VAR, "/stale/kit")
        monkeypatch.setenv(RUNTIME_ENV_VAR, "/stale/run")
        monkeypatch.setenv("SYNTHETIC_DAEMON_ONLY_VAR", "x")
        outcome = default_command_runner(("/bin/sh", "-c", "env"), {RUNTIME_ENV_VAR: "/m"}, 5.0)
        assert outcome.status is CommandStatus.OK
        names = {
            line.split("=", 1)[0]: line.split("=", 1)[1]
            for line in outcome.stdout.splitlines()
            if "=" in line
        }
        assert {name for name in names if name.startswith("TEAMCHAT_")} == {RUNTIME_ENV_VAR}
        assert names[RUNTIME_ENV_VAR] == "/m"
        assert "SYNTHETIC_DAEMON_ONLY_VAR" not in names
        assert "PATH" in names
        assert set(names) <= set(teamchat_seat.PROBE_ENV_ALLOWLIST) | {
            RUNTIME_ENV_VAR,
            "PWD",
            "SHLVL",
            "_",
        }

    def test_nonzero_exit_carries_the_code(self) -> None:
        outcome = default_command_runner(("sh", "-c", "exit 69"), {}, 5.0)
        assert outcome.status is CommandStatus.EXITED
        assert outcome.exit_code == 69

    def test_timeout(self) -> None:
        assert default_command_runner(("sleep", "5"), {}, 0.1).status is CommandStatus.TIMEOUT

    def test_permission_denied_is_not_found(self, tmp_path: Path) -> None:
        binary = tmp_path / "teamchat"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o600)
        outcome = default_command_runner((str(binary),), {}, 1.0)
        assert outcome.status is CommandStatus.NOT_FOUND


# --- TTL cache ---------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestResolver:
    def _resolver(self, runner: FakeRunner, clock: Clock) -> SeatContextResolver:
        return SeatContextResolver(ttl_seconds=60, clock=clock, runner=runner)

    def test_role_change_lands_within_one_ttl(self) -> None:
        runner, clock = ok(fx.WORKER_ONLY), Clock()
        resolver = self._resolver(runner, clock)
        assert resolver.resolve(SIGNALS).role_in("alpha") == "worker"
        runner.outcome = CommandOutcome(CommandStatus.OK, fx.COORDINATOR_ONLY, 0)
        clock.now += 30
        assert resolver.resolve(SIGNALS).role_in("alpha") == "worker"
        assert len(runner.calls) == 1
        clock.now += 31
        assert resolver.resolve(SIGNALS).role_in("alpha") == "coordinator"
        assert len(runner.calls) == 2

    def test_seat_link_appearing_lands_within_one_ttl(self) -> None:
        runner, clock = exited(fx.EXIT_NO_SESSION), Clock()
        resolver = self._resolver(runner, clock)
        assert resolver.resolve(SIGNALS).state is SeatState.ABSENT
        runner.outcome = CommandOutcome(CommandStatus.OK, fx.WORKER_ONLY, 0)
        clock.now += 61
        assert resolver.resolve(SIGNALS).role_in("alpha") == "worker"

    def test_cache_is_keyed_by_session_signals(self) -> None:
        runner, clock = ok(fx.WORKER_ONLY), Clock()
        resolver = self._resolver(runner, clock)
        resolver.resolve(SIGNALS)
        resolver.resolve(SessionSignals(runtime="/tmp/teamchat/run-b", kit=KIT))
        assert len(runner.calls) == 2

    def test_absent_runs_nothing(self) -> None:
        runner = ok(fx.WORKER_ONLY)
        resolver = self._resolver(runner, Clock())
        assert resolver.resolve(SessionSignals()).state is SeatState.ABSENT
        assert resolver.resolve(SIGNALS, detection_enabled=False).state is SeatState.ABSENT
        assert runner.calls == []

    def test_from_config_takes_the_ttl(self) -> None:
        runner, clock = ok(fx.WORKER_ONLY), Clock()
        config = TeamSeatConfig(resolve_ttl_seconds=10)
        resolver = SeatContextResolver.from_config(config, clock=clock, runner=runner)
        resolver.resolve(SIGNALS)
        clock.now += 9
        resolver.resolve(SIGNALS)
        assert len(runner.calls) == 1
        clock.now += 2
        resolver.resolve(SIGNALS)
        assert len(runner.calls) == 2

    def test_from_config_detection_off_probes_nothing(self) -> None:
        runner = ok(fx.WORKER_ONLY)
        resolver = SeatContextResolver.from_config(
            TeamSeatConfig(detection="off"), clock=Clock(), runner=runner
        )
        context = resolver.resolve(SIGNALS)
        assert context.state is SeatState.ABSENT
        assert context.reason is ProbeReason.DETECTION_OFF
        assert runner.calls == []


# --- invariants ---------------------------------------------------------------


class TestInvariants:
    def test_resolve_opens_and_stats_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invariant 5: no file under the run directory (or anywhere) is touched."""
        touched: list[Any] = []

        def record(name: str, real: Any) -> Any:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                touched.append((name, args[:1]))
                return real(*args, **kwargs)

            return wrapper

        monkeypatch.setattr(builtins, "open", record("open", builtins.open))
        monkeypatch.setattr(os, "stat", record("stat", os.stat))
        monkeypatch.setattr(os, "lstat", record("lstat", os.lstat))
        monkeypatch.setattr(os, "scandir", record("scandir", os.scandir))
        for stdout in (fx.MULTI_TEAM, fx.NOT_JSON, fx.NO_TEAMS):
            probe(stdout)
        probe_seat_context(SIGNALS, runner=exited(fx.EXIT_NO_SESSION))
        assert touched == []

    def test_module_has_no_v1_path(self) -> None:
        source = Path(teamchat_seat.__file__).read_text(encoding="utf-8").lower()
        assert "pingbus" not in source
        assert "teamchat_membership" not in source
