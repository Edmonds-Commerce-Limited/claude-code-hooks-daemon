"""Tests for the HUMAN-approval check (Plan 00634, umbrella 00630 DESIGN.md section 16).

Every refusal is a deny with a reason, never a pass. Peer lines, roles and
unreadable answers never count as a human's approval (invariants 1-3).
"""

from __future__ import annotations

import builtins
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.utils import human_approval
from claude_code_hooks_daemon.utils.human_approval import (
    ActClass,
    ApprovalCite,
    ApprovalRecords,
    GoGrant,
    Refusal,
    TeamchatVerifyCli,
    VerifiedLine,
    VerifyFailure,
    check_approval,
    contract_unconfirmed_verifier,
    is_armed,
    parse_cite,
    parse_verify_answer,
)
from claude_code_hooks_daemon.utils.teamchat_seat import (
    RUNTIME_ENV_VAR,
    CommandOutcome,
    CommandStatus,
    ProbeReason,
    SeatContext,
    SessionSignals,
    parse_whoami,
)
from tests.support import teamchat as fx

MAIN: dict[str, Any] = {"hook_event_name": "PreToolUse", "session_id": "s1"}
SUBAGENT: dict[str, Any] = {**MAIN, "agent_id": "a1b2c3d4e5f6a7b8c"}
RUNTIME = "/tmp/teamchat/run-a"
KIT = "/opt/teamchat-kit"
SIGNALS = SessionSignals(runtime=RUNTIME, kit=KIT)
CITE = ApprovalCite(team="alpha", event_id=fx.HUMAN_ID)
PUSH = frozenset({ActClass.PUSH})

ABSENT = SeatContext.absent(ProbeReason.NO_RUNTIME_SIGNAL)
UNRESOLVED = SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
COORDINATOR = parse_whoami(fx.COORDINATOR_ONLY)
WORKER = parse_whoami(fx.WORKER_ONLY)
MULTI = parse_whoami(fx.MULTI_TEAM)


class FakeRunner:
    def __init__(self, outcome: CommandOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[tuple[str, ...], dict[str, str], float]] = []

    def __call__(
        self, args: Sequence[str], env_overlay: Mapping[str, str], timeout: float
    ) -> CommandOutcome:
        self.calls.append((tuple(args), dict(env_overlay), timeout))
        return self.outcome


def answering(stdout: str) -> FakeRunner:
    return FakeRunner(CommandOutcome(CommandStatus.OK, stdout, 0))


def human_line(**overrides: Any) -> VerifiedLine:
    fields: dict[str, Any] = {
        "team": "alpha",
        "event_id": fx.HUMAN_ID,
        "room": "questions",
        "declared_human": True,
        "question": "Q7",
    }
    fields.update(overrides)
    return VerifiedLine(**fields)


class FixedVerifier:
    def __init__(self, answer: VerifiedLine | VerifyFailure) -> None:
        self.answer = answer
        self.calls: list[ApprovalCite] = []

    def __call__(self, signals: SessionSignals, cite: ApprovalCite) -> VerifiedLine | VerifyFailure:
        self.calls.append(cite)
        return self.answer


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def check(
    context: SeatContext = COORDINATOR,
    *,
    cite: ApprovalCite | None = CITE,
    acts: frozenset[ActClass] = PUSH,
    verifier: Any = None,
    go: GoGrant | None = None,
    records: ApprovalRecords | None = None,
    hook_input: dict[str, Any] | None = None,
    clock: Clock | None = None,
) -> human_approval.ApprovalVerdict:
    clock = clock or Clock()
    return check_approval(
        hook_input if hook_input is not None else MAIN,
        context,
        SIGNALS,
        acts=acts,
        cite=cite,
        verifier=verifier or FixedVerifier(human_line()),
        go=go,
        records=records or ApprovalRecords(clock=clock),
        clock=clock,
    )


# --- arming (Q5 provisional: coordinator seats, unknown role stays armed) --------


class TestArming:
    def test_absent_team_is_never_armed(self) -> None:
        assert is_armed(MAIN, ABSENT) is False

    def test_coordinator_main_thread_is_armed(self) -> None:
        assert is_armed(MAIN, COORDINATOR) is True

    def test_unresolved_probe_stays_armed(self) -> None:
        assert is_armed(MAIN, UNRESOLVED) is True

    def test_role_null_stays_armed(self) -> None:
        assert is_armed(MAIN, parse_whoami(fx.ROLE_NULL)) is True

    def test_worker_seat_is_not_armed(self) -> None:
        assert is_armed(MAIN, WORKER) is False

    def test_subagent_is_not_armed(self) -> None:
        assert is_armed(SUBAGENT, COORDINATOR) is False

    def test_coordinator_in_any_held_team_arms(self) -> None:
        assert is_armed(MAIN, MULTI) is True

    def test_switch_arms_every_seat_on_the_main_thread(self) -> None:
        assert is_armed(MAIN, WORKER, coordinator_seats_only=False) is True

    def test_switch_never_arms_an_absent_team_or_a_subagent(self) -> None:
        assert is_armed(MAIN, ABSENT, coordinator_seats_only=False) is False
        assert is_armed(SUBAGENT, WORKER, coordinator_seats_only=False) is False


# --- the cite ------------------------------------------------------------------


class TestParseCite:
    def test_valid(self) -> None:
        assert parse_cite("Alpha", fx.HUMAN_ID) == ApprovalCite("alpha", fx.HUMAN_ID)

    @pytest.mark.parametrize(
        "team, event_id",
        [
            ("alpha", "-rf"),  # option injection
            ("alpha", "--team"),
            ("alpha", "plain-id-without-dollar"),
            ("alpha", "$"),
            ("alpha", "$bad id"),
            ("alpha", "$bad\nid"),
            ("alpha", "$" + "a" * 300),
            # Path-shaped ids (review finding 6): no `/`, `.` or `~` at all.
            ("alpha", "$abc/../../x"),
            ("alpha", "$abc/def"),
            ("alpha", "$.."),
            ("alpha", "$a.b"),
            ("alpha", "$~user"),
            ("", fx.HUMAN_ID),
            ("-x", fx.HUMAN_ID),
            ("al pha", fx.HUMAN_ID),
            (None, fx.HUMAN_ID),
            ("alpha", None),
        ],
    )
    def test_malformed_is_refused(self, team: Any, event_id: Any) -> None:
        assert parse_cite(team, event_id) is None


# --- the verify answer (provisional contract, unverified here) -------------------


class TestParseVerifyAnswer:
    def test_human_questions_room_line(self) -> None:
        line = parse_verify_answer(fx.verify_answer(), CITE)
        assert line == human_line()

    def test_peer_sender_is_not_human(self) -> None:
        line = parse_verify_answer(fx.verify_answer(kind="agent"), CITE)
        assert isinstance(line, VerifiedLine)
        assert line.declared_human is False

    @pytest.mark.parametrize(
        "text",
        [
            fx.verify_answer(version=2),
            fx.verify_answer(version=True),
            fx.verify_answer(event_id="$some-other-line"),
            fx.verify_answer(team="beta"),
            fx.NOT_JSON,
            '{"v": 1, "v": 1}',
            "[]",
            fx.verify_answer(room=["questions"]),
            fx.verify_answer(kind=None),
        ],
    )
    def test_unreadable_or_mismatched_answer_is_a_failure(self, text: str) -> None:
        assert isinstance(parse_verify_answer(text, CITE), VerifyFailure)

    def test_text_is_never_kept(self) -> None:
        line = parse_verify_answer(fx.verify_answer(), CITE)
        assert "go ahead" not in repr(line)


class TestContractUnconfirmedDefault:
    def test_always_refuses_and_runs_nothing(self) -> None:
        answer = contract_unconfirmed_verifier(SIGNALS, CITE)
        assert answer == VerifyFailure(Refusal.CONTRACT_UNCONFIRMED)

    def test_default_verifier_is_the_unconfirmed_one(self) -> None:
        assert human_approval.DEFAULT_VERIFIER is contract_unconfirmed_verifier


class TestTeamchatVerifyCli:
    def test_argv_and_env(self) -> None:
        runner = answering(fx.verify_answer())
        TeamchatVerifyCli(runner=runner, timeout=3.0)(SIGNALS, CITE)
        assert runner.calls == [
            (
                (f"{KIT}/bin/teamchat", "verify", "--json", "--team", "alpha", fx.HUMAN_ID),
                {RUNTIME_ENV_VAR: RUNTIME},
                3.0,
            )
        ]

    def test_human_line_parses(self) -> None:
        answer = TeamchatVerifyCli(runner=answering(fx.verify_answer()))(SIGNALS, CITE)
        assert answer == human_line()

    @pytest.mark.parametrize(
        "outcome, refusal",
        [
            (CommandOutcome(CommandStatus.NOT_FOUND), Refusal.VERIFY_UNAVAILABLE),
            (CommandOutcome(CommandStatus.TIMEOUT), Refusal.VERIFY_UNAVAILABLE),
            (CommandOutcome(CommandStatus.UNTRUSTED), Refusal.VERIFY_UNAVAILABLE),
            (CommandOutcome(CommandStatus.TOO_LARGE), Refusal.ANSWER_UNREADABLE),
            (CommandOutcome(CommandStatus.EXITED, exit_code=1), Refusal.VERIFY_REFUSED),
            (CommandOutcome(CommandStatus.EXITED, exit_code=65), Refusal.VERIFY_REFUSED),
            (CommandOutcome(CommandStatus.EXITED, exit_code=69), Refusal.VERIFY_REFUSED),
            (CommandOutcome(CommandStatus.EXITED, exit_code=2), Refusal.VERIFY_REFUSED),
        ],
    )
    def test_every_failure_mode_refuses(self, outcome: CommandOutcome, refusal: Refusal) -> None:
        answer = TeamchatVerifyCli(runner=FakeRunner(outcome))(SIGNALS, CITE)
        assert answer == VerifyFailure(refusal)

    @pytest.mark.parametrize(
        "cite",
        [
            ApprovalCite(team="alpha", event_id="--team"),
            ApprovalCite(team="-x", event_id=fx.HUMAN_ID),
            ApprovalCite(team="alpha", event_id=fx.HUMAN_ID + "\n"),
        ],
    )
    def test_a_cite_built_without_parse_cite_is_still_checked(self, cite: ApprovalCite) -> None:
        runner = answering(fx.verify_answer())
        answer = TeamchatVerifyCli(runner=runner)(SIGNALS, cite)
        assert answer == VerifyFailure(Refusal.NO_CITE)
        assert runner.calls == []

    def test_kit_missing_refuses_without_running(self) -> None:
        runner = answering(fx.verify_answer())
        answer = TeamchatVerifyCli(runner=runner)(SessionSignals(runtime=RUNTIME), CITE)
        assert answer == VerifyFailure(Refusal.VERIFY_UNAVAILABLE)
        assert runner.calls == []


# --- the decision --------------------------------------------------------------


class TestCheckApproval:
    def test_verified_human_questions_line_from_a_coordinator_passes(self) -> None:
        verdict = check()
        assert verdict.passed is True
        assert verdict.refusal is None

    def test_no_cite_denies(self) -> None:
        verdict = check(cite=None)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NO_CITE)

    def test_peer_sender_denies(self) -> None:
        verdict = check(verifier=FixedVerifier(human_line(declared_human=False)))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NOT_HUMAN)

    def test_main_room_line_denies(self) -> None:
        verdict = check(verifier=FixedVerifier(human_line(room="main")))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NOT_QUESTIONS_ROOM)

    def test_answer_for_another_team_denies(self) -> None:
        verdict = check(verifier=FixedVerifier(human_line(team="beta")))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.ANSWER_MISMATCH)

    def test_answer_for_another_id_denies(self) -> None:
        verdict = check(verifier=FixedVerifier(human_line(event_id="$other-line-0001")))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.ANSWER_MISMATCH)

    @pytest.mark.parametrize(
        "refusal",
        [
            Refusal.VERIFY_UNAVAILABLE,
            Refusal.VERIFY_REFUSED,
            Refusal.ANSWER_UNREADABLE,
            Refusal.CONTRACT_UNCONFIRMED,
        ],
    )
    def test_verifier_failure_denies(self, refusal: Refusal) -> None:
        verdict = check(verifier=FixedVerifier(VerifyFailure(refusal)))
        assert (verdict.passed, verdict.refusal) == (False, refusal)

    def test_production_default_denies_a_real_looking_cite(self) -> None:
        verdict = check(verifier=contract_unconfirmed_verifier)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.CONTRACT_UNCONFIRMED)
        assert "unverified here" in verdict.reason

    def test_cite_for_a_team_where_seat_is_worker_denies_without_verifying(self) -> None:
        verifier = FixedVerifier(human_line(team="beta"))
        verdict = check(MULTI, cite=ApprovalCite("beta", fx.HUMAN_ID), verifier=verifier)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NOT_COORDINATOR)
        assert verifier.calls == []

    def test_cite_for_a_team_not_held_denies(self) -> None:
        verdict = check(cite=ApprovalCite("gamma", fx.HUMAN_ID))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NOT_COORDINATOR)

    def test_unreadable_role_denies(self) -> None:
        verifier = FixedVerifier(human_line())
        verdict = check(UNRESOLVED, verifier=verifier)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.ROLE_UNKNOWN)
        assert verifier.calls == []

    def test_subagent_never_passes(self) -> None:
        verdict = check(hook_input=SUBAGENT)
        assert verdict.passed is False

    def test_absent_team_never_passes_and_never_verifies(self) -> None:
        verifier = FixedVerifier(human_line())
        verdict = check(ABSENT, verifier=verifier)
        assert verdict.passed is False
        assert verifier.calls == []

    def test_no_acts_never_passes(self) -> None:
        verdict = check(acts=frozenset())
        assert verdict.passed is False

    def test_a_verifier_answering_anything_else_denies(self) -> None:
        verdict = check(verifier=lambda signals, cite: True)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.ANSWER_UNREADABLE)

    def test_reason_never_carries_the_line_text(self) -> None:
        verdict = check(
            verifier=TeamchatVerifyCli(runner=answering(fx.verify_answer(kind="agent")))
        )
        assert verdict.passed is False
        assert "go ahead" not in verdict.reason


class TestApprovalRecord:
    def test_a_pass_is_recorded_and_reused_inside_its_ttl(self) -> None:
        clock = Clock()
        records = ApprovalRecords(clock=clock, ttl_seconds=60)
        verifier = FixedVerifier(human_line())
        assert check(verifier=verifier, records=records, clock=clock).passed
        clock.now += 30
        assert check(verifier=verifier, records=records, clock=clock).passed
        assert len(verifier.calls) == 1

    def test_the_record_expires(self) -> None:
        clock = Clock()
        records = ApprovalRecords(clock=clock, ttl_seconds=60)
        verifier = FixedVerifier(human_line())
        check(verifier=verifier, records=records, clock=clock)
        clock.now += 61
        check(verifier=verifier, records=records, clock=clock)
        assert len(verifier.calls) == 2

    def test_the_record_lapses_exactly_at_its_ttl(self) -> None:
        clock = Clock()
        records = ApprovalRecords(clock=clock, ttl_seconds=60)
        verifier = FixedVerifier(human_line())
        check(verifier=verifier, records=records, clock=clock)
        clock.now += 60
        check(verifier=verifier, records=records, clock=clock)
        assert len(verifier.calls) == 2

    def test_a_go_covered_act_is_not_recorded_as_cited(self) -> None:
        clock = Clock()
        records = ApprovalRecords(clock=clock)
        go = GoGrant(team="alpha", classes=frozenset({ActClass.PUSH}), window_end=5000.0)
        verifier = FixedVerifier(human_line())
        check(
            go=go,
            acts=frozenset({ActClass.PUSH, ActClass.DELETE}),
            verifier=verifier,
            records=records,
            clock=clock,
        )
        refusing = FixedVerifier(VerifyFailure(Refusal.VERIFY_REFUSED))
        assert check(verifier=refusing, records=records, clock=clock).passed is False

    def test_the_record_is_per_act_class(self) -> None:
        clock = Clock()
        records = ApprovalRecords(clock=clock)
        verifier = FixedVerifier(human_line())
        check(verifier=verifier, records=records, clock=clock, acts=PUSH)
        check(
            verifier=verifier,
            records=records,
            clock=clock,
            acts=frozenset({ActClass.DELETE}),
        )
        assert len(verifier.calls) == 2

    def test_a_record_never_outlives_a_role_change(self) -> None:
        clock = Clock()
        records = ApprovalRecords(clock=clock)
        assert check(records=records, clock=clock).passed
        verdict = check(WORKER, records=records, clock=clock)
        assert verdict.passed is False

    def test_a_refusal_is_never_recorded(self) -> None:
        clock = Clock()
        records = ApprovalRecords(clock=clock)
        check(
            verifier=FixedVerifier(human_line(declared_human=False)), records=records, clock=clock
        )
        assert (
            check(
                verifier=FixedVerifier(VerifyFailure(Refusal.VERIFY_REFUSED)),
                records=records,
                clock=clock,
            ).passed
            is False
        )


# --- a verified readiness GO as the cite (M-8) ----------------------------------


class TestGoAsCite:
    def grant(self, *classes: ActClass, window_end: float = 2000.0, team: str = "alpha") -> GoGrant:
        return GoGrant(team=team, classes=frozenset(classes), window_end=window_end)

    def test_go_covers_its_authorised_class_inside_the_window(self) -> None:
        verifier = FixedVerifier(VerifyFailure(Refusal.VERIFY_REFUSED))
        verdict = check(cite=None, go=self.grant(ActClass.PUSH), verifier=verifier)
        assert verdict.passed is True
        assert verifier.calls == []

    def test_go_never_covers_a_class_it_did_not_authorise(self) -> None:
        verdict = check(cite=None, go=self.grant(ActClass.PUSH), acts=frozenset({ActClass.DELETE}))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NO_CITE)

    def test_go_must_cover_every_act_in_the_command(self) -> None:
        verdict = check(
            cite=None,
            go=self.grant(ActClass.PUSH),
            acts=frozenset({ActClass.PUSH, ActClass.DELETE}),
        )
        assert verdict.passed is False

    def test_go_lapses_at_the_window_end(self) -> None:
        clock = Clock()
        clock.now = 2000.0
        verdict = check(cite=None, go=self.grant(ActClass.PUSH, window_end=2000.0), clock=clock)
        assert verdict.passed is False

    def test_go_for_a_team_where_the_seat_is_not_coordinator_does_not_cover(self) -> None:
        verdict = check(MULTI, cite=None, go=self.grant(ActClass.PUSH, team="beta"))
        assert verdict.passed is False

    def test_go_does_not_cover_a_subagent(self) -> None:
        verdict = check(cite=None, go=self.grant(ActClass.PUSH), hook_input=SUBAGENT)
        assert verdict.passed is False

    def test_go_and_cite_combine_per_class(self) -> None:
        verdict = check(
            go=self.grant(ActClass.PUSH),
            acts=frozenset({ActClass.PUSH, ActClass.DELETE}),
        )
        assert verdict.passed is True


# --- invariants ------------------------------------------------------------------


class TestInvariants:
    def test_check_opens_and_stats_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invariant 5: no file anywhere is touched by a check (seat store, run dir...)."""
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
        for answer in (fx.verify_answer(), fx.verify_answer(kind="agent"), fx.NOT_JSON):
            check(verifier=TeamchatVerifyCli(runner=answering(answer)))
        check(verifier=contract_unconfirmed_verifier)
        assert touched == []

    def test_module_has_no_v1_or_history_path(self) -> None:
        source = Path(human_approval.__file__).read_text(encoding="utf-8").lower()
        assert "pingbus" not in source
        assert "history" not in source
        assert "password" not in source
