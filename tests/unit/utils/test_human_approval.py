"""Tests for the HUMAN-approval check (Plan 00634, umbrella 00630 DESIGN.md section 16).

Every refusal is a deny with a reason, never a pass. Peer lines, roles and
unreadable answers never count as a human's approval (invariants 1-3).

The ``verify`` fixtures follow the fedora-desktop issue 369 contract as its
peer seat relayed it (plan 00634 subagent-reports/261124-fedora-desktop-contract-
reply.md), unverified against a live teamchat from this repository.
"""

from __future__ import annotations

import builtins
import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.utils import human_approval
from claude_code_hooks_daemon.utils.human_approval import (
    ActClass,
    ApprovalCite,
    ApprovalRecords,
    BindingPolicy,
    CiteLedger,
    GoGrant,
    LedgerOutcome,
    Refusal,
    TeamchatVerifyCli,
    VerifiedLine,
    VerifyFailure,
    check_approval,
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
OTHER_ID = "$" + "another-human-line".ljust(43, "y")

ABSENT = SeatContext.absent(ProbeReason.NO_RUNTIME_SIGNAL)
UNRESOLVED = SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
COORDINATOR = parse_whoami(fx.COORDINATOR_ONLY)
WORKER = parse_whoami(fx.WORKER_ONLY)
MULTI = parse_whoami(fx.MULTI_TEAM)

#: Wall clock one minute after the synthetic line was sent (seconds).
ONE_MINUTE_LATER = fx.SENT_MS / 1000 + 60


class FakeRunner:
    def __init__(self, outcome: CommandOutcome | BaseException) -> None:
        self.outcome = outcome
        self.calls: list[tuple[tuple[str, ...], dict[str, str], float]] = []

    def __call__(
        self, args: Sequence[str], env_overlay: Mapping[str, str], timeout: float
    ) -> CommandOutcome:
        self.calls.append((tuple(args), dict(env_overlay), timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def answering(stdout: str) -> FakeRunner:
    return FakeRunner(CommandOutcome(CommandStatus.OK, stdout, 0))


def exiting(code: int) -> FakeRunner:
    return FakeRunner(CommandOutcome(CommandStatus.EXITED, exit_code=code))


def human_line(**overrides: Any) -> VerifiedLine:
    fields: dict[str, Any] = {
        "team": "alpha",
        "event_id": fx.HUMAN_ID,
        "room": "questions",
        "declared_human": True,
        "question": "Q7",
        "sent_ms": fx.SENT_MS,
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
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

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
    policy: BindingPolicy | None = None,
    ledger: CiteLedger | None = None,
    wall_clock: Clock | None = None,
    include_subagents: bool = False,
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
        policy=policy or BindingPolicy(),
        ledger=ledger,
        wall_clock=wall_clock or Clock(ONE_MINUTE_LATER),
        include_subagents=include_subagents,
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

    def test_subagent_is_not_armed_by_default(self) -> None:
        assert is_armed(SUBAGENT, COORDINATOR) is False

    def test_coordinator_in_any_held_team_arms(self) -> None:
        assert is_armed(MAIN, MULTI) is True

    def test_switch_arms_every_seat_on_the_main_thread(self) -> None:
        assert is_armed(MAIN, WORKER, coordinator_seats_only=False) is True

    def test_switch_never_arms_an_absent_team_or_a_subagent(self) -> None:
        assert is_armed(MAIN, ABSENT, coordinator_seats_only=False) is False
        assert is_armed(SUBAGENT, WORKER, coordinator_seats_only=False) is False


class TestArmingSubagents:
    """P2: with ``include_subagents`` a sub-agent of a DECLARED coordinator seat is armed.

    Owner ruling (plan 00634): never assume a team, role or duty exists, so an
    unreadable seat arms no sub-agent (the main thread is unchanged).
    """

    @pytest.mark.parametrize("context", [COORDINATOR, MULTI])
    def test_declared_coordinator_seats_subagent_is_armed(self, context: SeatContext) -> None:
        assert is_armed(SUBAGENT, context, include_subagents=True) is True

    @pytest.mark.parametrize("context", [WORKER, ABSENT, UNRESOLVED, parse_whoami(fx.ROLE_NULL)])
    def test_any_other_subagent_is_not_armed(self, context: SeatContext) -> None:
        assert is_armed(SUBAGENT, context, include_subagents=True) is False

    @pytest.mark.parametrize("context", [COORDINATOR, WORKER, ABSENT, UNRESOLVED])
    def test_main_thread_is_unchanged(self, context: SeatContext) -> None:
        assert is_armed(MAIN, context, include_subagents=True) is is_armed(MAIN, context)

    def test_the_q5_switch_never_arms_a_non_coordinator_subagent(self) -> None:
        for context in (WORKER, ABSENT, UNRESOLVED):
            assert not is_armed(
                SUBAGENT, context, coordinator_seats_only=False, include_subagents=True
            )


# --- the cite ------------------------------------------------------------------


class TestParseCite:
    def test_valid(self) -> None:
        assert parse_cite("Alpha", fx.HUMAN_ID) == ApprovalCite("alpha", fx.HUMAN_ID)

    def test_contract_alphabet_is_accepted(self) -> None:
        event_id = "$" + "A-z_9" * 8 + "abc"
        assert parse_cite("alpha", event_id) == ApprovalCite("alpha", event_id)

    @pytest.mark.parametrize(
        "team, event_id",
        [
            ("alpha", "-rf"),  # option injection
            ("alpha", "--team"),
            ("alpha", "--room"),
            ("alpha", "plain-id-without-dollar".ljust(44, "x")),
            ("alpha", "$"),
            ("alpha", "$" + "a" * 42),  # one short
            ("alpha", "$" + "a" * 44),  # one long
            ("alpha", "$" + "a" * 42 + "+"),  # `+` is not in the contract alphabet
            ("alpha", "$" + "a" * 42 + "="),
            ("alpha", "$" + "a" * 42 + " "),
            ("alpha", "$" + "a" * 42 + "\n"),
            ("alpha", "$" + "a" * 300),
            # Path-shaped ids (review finding 6): no `/`, `.` or `~` at all.
            ("alpha", "$" + "a" * 39 + "/../"),
            ("alpha", "$" + "a" * 42 + "."),
            ("alpha", "$" + "a" * 42 + "~"),
            ("", fx.HUMAN_ID),
            ("-x", fx.HUMAN_ID),
            ("al pha", fx.HUMAN_ID),
            (None, fx.HUMAN_ID),
            ("alpha", None),
        ],
    )
    def test_malformed_is_refused(self, team: Any, event_id: Any) -> None:
        assert parse_cite(team, event_id) is None


# --- the verify answer (issue 369 contract, peer-relayed) --------------------------


class TestParseVerifyAnswer:
    def test_human_questions_room_line(self) -> None:
        assert parse_verify_answer(fx.verify_answer(), CITE) == human_line()

    def test_trailing_newline_is_optional(self) -> None:
        assert parse_verify_answer(fx.verify_answer().rstrip("\n"), CITE) == human_line()

    @pytest.mark.parametrize("question", ["none", None])
    def test_no_question_reads_as_empty(self, question: Any) -> None:
        line = parse_verify_answer(fx.verify_answer(question=question), CITE)
        assert line == human_line(question="")

    def test_headline_may_be_a_string(self) -> None:
        line = parse_verify_answer(fx.verify_answer(headline="Ship it?"), CITE)
        assert isinstance(line, VerifiedLine)

    def test_peer_sender_is_refused_by_the_verifier(self) -> None:
        answer = parse_verify_answer(fx.verify_answer(human=False), CITE)
        assert answer == VerifyFailure(Refusal.NOT_HUMAN)

    @pytest.mark.parametrize(
        "overrides",
        [
            {"kind": "human"},
            {"kind": "record"},
            {"kind": None},
            {"v": 2},
            {"v": True},
            {"v": "1"},
            {"team": 7},
            {"id": None},
            {"item": None},
            {"from": ["@owner"]},
            {"room": ["questions"]},
            {"text": None},
            {"body_sha256": 0},
            {"sent_ms": "1795000000000"},
            {"sent_ms": 1.5},
            {"sent_ms": True},
            {"sent_ms": -1},
            {"human": 1},
            {"human": "true"},
            {"human": None},
            {"question": "Q"},
            {"question": "q7"},
            {"question": "Q7 "},
            {"question": "None"},
            {"question": 7},
            {"headline": 7},
            {"extra": "key"},
        ],
    )
    def test_off_contract_answer_is_unreadable(self, overrides: dict[str, Any]) -> None:
        answer = parse_verify_answer(fx.verify_answer(**overrides), CITE)
        assert answer == VerifyFailure(Refusal.ANSWER_UNREADABLE)

    @pytest.mark.parametrize("key", sorted(fx.verify_document()))
    def test_a_missing_key_is_unreadable(self, key: str) -> None:
        answer = parse_verify_answer(fx.verify_answer(drop=(key,)), CITE)
        assert answer == VerifyFailure(Refusal.ANSWER_UNREADABLE)

    @pytest.mark.parametrize(
        "text",
        [
            fx.NOT_JSON,
            "",
            "\n",
            '{"v": 1, "v": 1}',
            "[]",
            fx.verify_answer() + fx.verify_answer(),  # two records
            fx.verify_answer().rstrip("\n") + "\r\n",
            "\n" + fx.verify_answer(),
        ],
    )
    def test_not_one_record_line_is_unreadable(self, text: str) -> None:
        assert parse_verify_answer(text, CITE) == VerifyFailure(Refusal.ANSWER_UNREADABLE)

    @pytest.mark.parametrize("overrides", [{"id": OTHER_ID}, {"team": "beta"}])
    def test_another_line_or_team_is_a_mismatch(self, overrides: dict[str, Any]) -> None:
        answer = parse_verify_answer(fx.verify_answer(**overrides), CITE)
        assert answer == VerifyFailure(Refusal.ANSWER_MISMATCH)

    def test_text_is_never_kept(self) -> None:
        line = parse_verify_answer(fx.verify_answer(headline="headline-marker"), CITE)
        assert "go ahead" not in repr(line)
        assert "headline-marker" not in repr(line)


class TestTeamchatVerifyCli:
    def test_argv_and_env_follow_the_contract(self) -> None:
        runner = answering(fx.verify_answer())
        TeamchatVerifyCli(runner=runner, timeout=Timeout.TEAMCHAT_WHOAMI)(SIGNALS, CITE)
        assert runner.calls == [
            (
                (f"{KIT}/bin/teamchat", "verify", fx.HUMAN_ID, "--room", "questions"),
                {RUNTIME_ENV_VAR: RUNTIME},
                Timeout.TEAMCHAT_WHOAMI,
            )
        ]

    def test_default_timeout_is_the_verify_timeout(self) -> None:
        runner = answering(fx.verify_answer())
        TeamchatVerifyCli(runner=runner)(SIGNALS, CITE)
        assert runner.calls[0][2] == float(Timeout.TEAMCHAT_VERIFY)

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
            (CommandOutcome(CommandStatus.EXITED, exit_code=23), Refusal.LINE_NOT_FOUND),
            (CommandOutcome(CommandStatus.EXITED, exit_code=22), Refusal.VERIFY_UNTRUSTED),
            (CommandOutcome(CommandStatus.EXITED, exit_code=20), Refusal.VERIFY_UNREACHABLE),
            (CommandOutcome(CommandStatus.EXITED, exit_code=14), Refusal.VERIFY_RATE_LIMITED),
            (CommandOutcome(CommandStatus.EXITED, exit_code=1), Refusal.VERIFY_REFUSED),
            (CommandOutcome(CommandStatus.EXITED, exit_code=2), Refusal.VERIFY_REFUSED),
            (CommandOutcome(CommandStatus.EXITED, exit_code=65), Refusal.VERIFY_REFUSED),
            (CommandOutcome(CommandStatus.EXITED, exit_code=69), Refusal.VERIFY_REFUSED),
            (CommandOutcome(CommandStatus.EXITED, exit_code=-9), Refusal.VERIFY_REFUSED),
            (CommandOutcome(CommandStatus.EXITED, exit_code=None), Refusal.VERIFY_REFUSED),
            # A runner claiming success with a non-zero code is off contract.
            (CommandOutcome(CommandStatus.OK, fx.verify_answer(), 23), Refusal.ANSWER_UNREADABLE),
        ],
    )
    def test_every_failure_mode_refuses(self, outcome: CommandOutcome, refusal: Refusal) -> None:
        answer = TeamchatVerifyCli(runner=FakeRunner(outcome))(SIGNALS, CITE)
        assert answer == VerifyFailure(refusal)

    def test_oversized_ok_output_is_unreadable(self) -> None:
        padded = fx.verify_answer(text="x" * (128 * 1024))
        answer = TeamchatVerifyCli(runner=answering(padded))(SIGNALS, CITE)
        assert answer == VerifyFailure(Refusal.ANSWER_UNREADABLE)

    def test_non_text_stdout_is_unreadable(self) -> None:
        raw: Any = b"{}"
        runner = FakeRunner(CommandOutcome(CommandStatus.OK, raw, 0))
        assert TeamchatVerifyCli(runner=runner)(SIGNALS, CITE) == VerifyFailure(
            Refusal.ANSWER_UNREADABLE
        )

    @pytest.mark.parametrize(
        "error",
        [
            OSError("spawn failed"),
            subprocess.TimeoutExpired(cmd="teamchat", timeout=Timeout.TEAMCHAT_VERIFY),
            ValueError("bad"),
            RecursionError(),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        ],
    )
    def test_a_raising_runner_refuses_and_never_raises(self, error: BaseException) -> None:
        answer = TeamchatVerifyCli(runner=FakeRunner(error))(SIGNALS, CITE)
        assert answer == VerifyFailure(Refusal.VERIFY_UNAVAILABLE)

    @staticmethod
    def fake_kit(tmp_path: Path, script: str) -> SessionSignals:
        """A kit whose ``bin/teamchat`` is ``script``, run by the real default runner."""
        binary = tmp_path / "kit" / "bin" / "teamchat"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\n" + script + "\n", encoding="utf-8")
        binary.chmod(0o755)
        return SessionSignals(runtime=str(tmp_path / "runtime"), kit=str(tmp_path / "kit"))

    def test_the_real_runner_maps_a_not_found_exit_to_a_refusal(self, tmp_path: Path) -> None:
        signals = self.fake_kit(tmp_path, "exit 23")
        answer = TeamchatVerifyCli()(signals, CITE)
        assert answer == VerifyFailure(Refusal.LINE_NOT_FOUND)

    def test_the_real_runner_refuses_invalid_utf8_output(self, tmp_path: Path) -> None:
        signals = self.fake_kit(tmp_path, "printf '\\377\\376{}\\n'")
        answer = TeamchatVerifyCli()(signals, CITE)
        assert answer == VerifyFailure(Refusal.ANSWER_UNREADABLE)

    def test_the_real_runner_refuses_an_invalid_byte_in_the_event_id(self, tmp_path: Path) -> None:
        """An otherwise valid record whose id carries a non-UTF-8 byte names another line."""
        bad_id = fx.HUMAN_ID[:-1] + "XBADX"
        answer_line = fx.verify_answer(id=bad_id).rstrip("\n").replace("XBADX", "\\377")
        signals = self.fake_kit(tmp_path, f"printf '{answer_line}\\n'")
        answer = TeamchatVerifyCli()(signals, CITE)
        assert answer == VerifyFailure(Refusal.ANSWER_MISMATCH)

    def test_the_real_runner_passes_a_valid_answer(self, tmp_path: Path) -> None:
        """Control: the fake kit is trusted and its answer is read, so the refusals above
        come from the output, not from the kit being refused."""
        answer_line = fx.verify_answer().rstrip("\n").replace("'", "'\\''")
        signals = self.fake_kit(tmp_path, f"printf '%s\\n' '{answer_line}'")
        answer = TeamchatVerifyCli()(signals, CITE)
        assert isinstance(answer, VerifiedLine)

    def test_a_raising_parse_refuses_and_never_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(text: str, cite: ApprovalCite) -> VerifiedLine:
            raise RecursionError()

        monkeypatch.setattr(human_approval, "parse_verify_answer", explode)
        answer = TeamchatVerifyCli(runner=answering(fx.verify_answer()))(SIGNALS, CITE)
        assert answer == VerifyFailure(Refusal.ANSWER_UNREADABLE)

    @pytest.mark.parametrize(
        "cite",
        [
            ApprovalCite(team="alpha", event_id="--team"),
            ApprovalCite(team="alpha", event_id="--room"),
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

    def test_default_verifier_is_the_cli(self) -> None:
        assert isinstance(human_approval.DEFAULT_VERIFIER, TeamchatVerifyCli)


# --- the decision --------------------------------------------------------------


class TestCheckApproval:
    def test_verified_human_questions_line_from_a_coordinator_passes(self) -> None:
        verdict = check()
        assert verdict.passed is True
        assert verdict.refusal is None

    def test_end_to_end_through_the_cli_passes(self) -> None:
        verdict = check(verifier=TeamchatVerifyCli(runner=answering(fx.verify_answer())))
        assert verdict.passed is True

    def test_no_cite_denies(self) -> None:
        verdict = check(cite=None)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NO_CITE)

    def test_peer_sender_denies(self) -> None:
        verdict = check(verifier=FixedVerifier(human_line(declared_human=False)))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NOT_HUMAN)

    def test_main_room_line_denies(self) -> None:
        verdict = check(verifier=FixedVerifier(human_line(room="main")))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NOT_QUESTIONS_ROOM)

    def test_main_room_line_through_the_cli_denies(self) -> None:
        runner = answering(fx.verify_answer(room="main"))
        verdict = check(verifier=TeamchatVerifyCli(runner=runner))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NOT_QUESTIONS_ROOM)

    def test_answer_for_another_team_denies(self) -> None:
        verdict = check(verifier=FixedVerifier(human_line(team="beta")))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.ANSWER_MISMATCH)

    def test_answer_for_another_id_denies(self) -> None:
        verdict = check(verifier=FixedVerifier(human_line(event_id=OTHER_ID)))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.ANSWER_MISMATCH)

    @pytest.mark.parametrize(
        "refusal",
        [
            Refusal.VERIFY_UNAVAILABLE,
            Refusal.VERIFY_REFUSED,
            Refusal.ANSWER_UNREADABLE,
            Refusal.LINE_NOT_FOUND,
            Refusal.VERIFY_UNTRUSTED,
            Refusal.VERIFY_UNREACHABLE,
            Refusal.VERIFY_RATE_LIMITED,
        ],
    )
    def test_verifier_failure_denies(self, refusal: Refusal) -> None:
        verdict = check(verifier=FixedVerifier(VerifyFailure(refusal)))
        assert (verdict.passed, verdict.refusal) == (False, refusal)

    @pytest.mark.parametrize("code", [23, 22, 20, 14, 1, 99])
    def test_each_non_zero_exit_through_the_cli_denies(self, code: int) -> None:
        verdict = check(verifier=TeamchatVerifyCli(runner=exiting(code)))
        assert verdict.passed is False

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

    def test_subagent_never_passes_by_default(self) -> None:
        verdict = check(hook_input=SUBAGENT)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.SUBAGENT)

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
        verdict = check(verifier=TeamchatVerifyCli(runner=answering(fx.verify_answer(human=False))))
        assert verdict.passed is False
        assert "go ahead" not in verdict.reason


class TestCheckApprovalSubagents:
    """P2: a coordinator seat's sub-agent is judged as the seat."""

    def test_a_coordinator_seats_subagent_with_a_human_cite_passes(self) -> None:
        verdict = check(hook_input=SUBAGENT, include_subagents=True)
        assert verdict.passed is True

    def test_a_coordinator_seats_subagent_without_a_cite_is_refused(self) -> None:
        verdict = check(hook_input=SUBAGENT, include_subagents=True, cite=None)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NO_CITE)

    def test_a_coordinator_seats_subagent_citing_a_peer_is_refused(self) -> None:
        verdict = check(
            hook_input=SUBAGENT,
            include_subagents=True,
            verifier=FixedVerifier(human_line(declared_human=False)),
        )
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NOT_HUMAN)

    def test_a_worker_seats_subagent_is_not_coordinator(self) -> None:
        verdict = check(WORKER, hook_input=SUBAGENT, include_subagents=True)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NOT_COORDINATOR)

    def test_a_no_team_subagent_has_no_seat(self) -> None:
        verdict = check(ABSENT, hook_input=SUBAGENT, include_subagents=True)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NO_TEAM_SEAT)

    def test_a_go_covers_a_coordinator_seats_subagent(self) -> None:
        go = GoGrant(team="alpha", classes=PUSH, window_end=5000.0)
        verdict = check(cite=None, go=go, hook_input=SUBAGENT, include_subagents=True)
        assert verdict.passed is True


# --- the binding switches (P1, owner question O4: all OFF by default) ----------------


class TestBindingPolicyDefaults:
    def test_default_policy_is_all_off(self) -> None:
        policy = BindingPolicy()
        assert (policy.require_question, policy.max_line_age_seconds, policy.single_use) == (
            False,
            None,
            False,
        )

    def test_off_a_line_with_no_question_passes(self) -> None:
        assert check(verifier=FixedVerifier(human_line(question=""))).passed is True

    def test_off_an_old_line_passes(self) -> None:
        verdict = check(wall_clock=Clock(fx.SENT_MS / 1000 + 365 * 86400))
        assert verdict.passed is True

    def test_off_a_cite_is_reusable(self) -> None:
        records = ApprovalRecords(clock=Clock(), ttl_seconds=0)
        verifier = FixedVerifier(human_line())
        assert check(verifier=verifier, records=records).passed
        assert check(verifier=verifier, records=records).passed


class TestRequireQuestion:
    POLICY = BindingPolicy(require_question=True)

    def test_a_line_answering_a_question_passes(self) -> None:
        assert check(policy=self.POLICY).passed is True

    def test_a_line_answering_no_question_is_refused(self) -> None:
        verdict = check(policy=self.POLICY, verifier=FixedVerifier(human_line(question="")))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NO_QUESTION)

    @pytest.mark.parametrize("question", ["none", None])
    def test_none_or_null_through_the_cli_is_refused(self, question: Any) -> None:
        runner = answering(fx.verify_answer(question=question))
        verdict = check(policy=self.POLICY, verifier=TeamchatVerifyCli(runner=runner))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NO_QUESTION)

    def test_a_malformed_question_on_a_hand_built_line_is_refused(self) -> None:
        verdict = check(policy=self.POLICY, verifier=FixedVerifier(human_line(question="Qx")))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.NO_QUESTION)


class TestMaxLineAge:
    POLICY = BindingPolicy(max_line_age_seconds=600)

    def test_a_fresh_line_passes(self) -> None:
        assert check(policy=self.POLICY, wall_clock=Clock(ONE_MINUTE_LATER)).passed is True

    def test_a_line_at_exactly_the_limit_passes(self) -> None:
        assert check(policy=self.POLICY, wall_clock=Clock(fx.SENT_MS / 1000 + 600)).passed

    def test_a_line_past_the_limit_is_refused(self) -> None:
        verdict = check(policy=self.POLICY, wall_clock=Clock(fx.SENT_MS / 1000 + 601))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.LINE_OUT_OF_WINDOW)

    def test_a_line_dated_in_the_future_is_refused(self) -> None:
        verdict = check(policy=self.POLICY, wall_clock=Clock(fx.SENT_MS / 1000 - 3600))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.LINE_OUT_OF_WINDOW)

    def test_small_clock_skew_is_tolerated(self) -> None:
        assert check(policy=self.POLICY, wall_clock=Clock(fx.SENT_MS / 1000 - 5)).passed

    def test_a_live_record_does_not_outlive_the_line_age(self) -> None:
        clock = Clock()
        records = ApprovalRecords(clock=clock)
        assert check(policy=self.POLICY, records=records, clock=clock).passed
        verdict = check(
            policy=self.POLICY,
            records=records,
            clock=clock,
            wall_clock=Clock(fx.SENT_MS / 1000 + 3600),
        )
        assert verdict.passed is False


class TestSingleUse:
    POLICY = BindingPolicy(single_use=True)

    def ledger(self, tmp_path: Path) -> CiteLedger:
        return CiteLedger(lambda: tmp_path / "state" / "human-approval-cites.json")

    def test_first_use_passes_and_second_is_refused(self, tmp_path: Path) -> None:
        ledger = self.ledger(tmp_path)
        records = ApprovalRecords(clock=Clock())
        assert check(policy=self.POLICY, ledger=ledger, records=records).passed
        verdict = check(policy=self.POLICY, ledger=ledger, records=records)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.CITE_ALREADY_USED)

    def test_use_is_per_act_class(self, tmp_path: Path) -> None:
        ledger = self.ledger(tmp_path)
        assert check(policy=self.POLICY, ledger=ledger, acts=PUSH).passed
        assert check(policy=self.POLICY, ledger=ledger, acts=frozenset({ActClass.DELETE})).passed

    def test_any_used_class_refuses_the_whole_command(self, tmp_path: Path) -> None:
        ledger = self.ledger(tmp_path)
        assert check(policy=self.POLICY, ledger=ledger, acts=PUSH).passed
        verdict = check(
            policy=self.POLICY, ledger=ledger, acts=frozenset({ActClass.PUSH, ActClass.DELETE})
        )
        assert (verdict.passed, verdict.refusal) == (False, Refusal.CITE_ALREADY_USED)

    def test_use_is_per_cite(self, tmp_path: Path) -> None:
        ledger = self.ledger(tmp_path)
        assert check(policy=self.POLICY, ledger=ledger).passed
        other = FixedVerifier(human_line(event_id=OTHER_ID))
        cite = ApprovalCite("alpha", OTHER_ID)
        assert check(policy=self.POLICY, ledger=ledger, cite=cite, verifier=other).passed

    def test_use_persists_across_ledger_instances(self, tmp_path: Path) -> None:
        assert check(policy=self.POLICY, ledger=self.ledger(tmp_path)).passed
        verdict = check(policy=self.POLICY, ledger=self.ledger(tmp_path))
        assert verdict.refusal is Refusal.CITE_ALREADY_USED

    def test_a_used_cite_never_reaches_the_verifier(self, tmp_path: Path) -> None:
        ledger = self.ledger(tmp_path)
        check(policy=self.POLICY, ledger=ledger)
        verifier = FixedVerifier(human_line())
        check(policy=self.POLICY, ledger=ledger, verifier=verifier)
        assert verifier.calls == []

    def test_a_refused_line_is_not_consumed(self, tmp_path: Path) -> None:
        ledger = self.ledger(tmp_path)
        peer = FixedVerifier(human_line(declared_human=False))
        assert check(policy=self.POLICY, ledger=ledger, verifier=peer).passed is False
        assert check(policy=self.POLICY, ledger=ledger).passed is True

    def test_a_go_covered_act_is_not_consumed(self, tmp_path: Path) -> None:
        ledger = self.ledger(tmp_path)
        go = GoGrant(team="alpha", classes=PUSH, window_end=5000.0)
        assert check(policy=self.POLICY, ledger=ledger, go=go).passed
        assert check(policy=self.POLICY, ledger=ledger).passed

    def test_no_ledger_refuses(self) -> None:
        verdict = check(policy=self.POLICY, ledger=None)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.LEDGER_UNAVAILABLE)

    def test_a_path_that_cannot_be_resolved_refuses(self) -> None:
        def no_path() -> Path:
            raise RuntimeError("project context not initialised")

        verdict = check(policy=self.POLICY, ledger=CiteLedger(no_path))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.LEDGER_UNAVAILABLE)

    @pytest.mark.parametrize(
        "content",
        [
            "not json",
            "[]",
            '{"v": 2, "used": []}',
            '{"v": 1, "used": "x"}',
            '{"v": 1, "used": [["alpha", "$x"]]}',
            '{"v": 1, "used": [[1, 2, 3]]}',
        ],
    )
    def test_an_unreadable_ledger_refuses(self, tmp_path: Path, content: str) -> None:
        path = tmp_path / "ledger.json"
        path.write_text(content, encoding="utf-8")
        verdict = check(policy=self.POLICY, ledger=CiteLedger(lambda: path))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.LEDGER_UNAVAILABLE)

    @staticmethod
    def padded_ledger(path: Path, rows: list[list[str]], size: int) -> None:
        body = json.dumps({"v": 1, "used": rows})
        path.write_text(body + " " * (size - len(body)), encoding="utf-8")

    @staticmethod
    def seeded_rows(count: int) -> list[list[str]]:
        return [["alpha", "$" + f"{n:043d}", "push"] for n in range(count)]

    def test_the_documented_cap_is_256_kib(self) -> None:
        assert human_approval.MAX_LEDGER_BYTES == 256 * 1024

    def test_a_ledger_exactly_at_the_cap_is_read(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.json"
        self.padded_ledger(path, [], human_approval.MAX_LEDGER_BYTES)
        verifier = FixedVerifier(human_line())
        verdict = check(policy=self.POLICY, ledger=CiteLedger(lambda: path), verifier=verifier)
        assert verdict.passed is True

    def test_an_oversized_ledger_refuses(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.json"
        self.padded_ledger(path, [], human_approval.MAX_LEDGER_BYTES + 1)
        verdict = check(policy=self.POLICY, ledger=CiteLedger(lambda: path))
        assert (verdict.passed, verdict.refusal) == (False, Refusal.LEDGER_UNAVAILABLE)

    def test_a_full_ledger_evicts_its_oldest_entries_and_keeps_accepting(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "ledger.json"
        row_bytes = len(json.dumps(self.seeded_rows(1)[0])) + 2  # the row and its ", "
        rows = self.seeded_rows((human_approval.MAX_LEDGER_BYTES - 32) // row_bytes)
        path.write_text(json.dumps({"v": 1, "used": rows}), encoding="utf-8")
        assert path.stat().st_size > human_approval.MAX_LEDGER_BYTES - 2 * row_bytes
        ledger = CiteLedger(lambda: path)
        fresh = [ApprovalCite("beta", "$" + f"{n:043d}") for n in range(10)]
        for cite in fresh:
            assert ledger.consume(cite, PUSH) is LedgerOutcome.CONSUMED
            assert path.stat().st_size <= human_approval.MAX_LEDGER_BYTES
        for cite in fresh:
            assert ledger.used(cite, PUSH) is LedgerOutcome.ALREADY_USED
        oldest = ApprovalCite("alpha", rows[0][1])
        newest_seeded = ApprovalCite("alpha", rows[-1][1])
        assert ledger.used(oldest, PUSH) is LedgerOutcome.UNUSED
        assert ledger.used(newest_seeded, PUSH) is LedgerOutcome.ALREADY_USED

    def test_a_use_that_alone_cannot_fit_refuses_and_writes_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.json"
        huge = ApprovalCite("a" * human_approval.MAX_LEDGER_BYTES, fx.HUMAN_ID)
        assert CiteLedger(lambda: path).consume(huge, PUSH) is LedgerOutcome.UNAVAILABLE
        assert not path.exists()

    def test_new_entries_are_appended_in_use_order(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.json"
        ledger = CiteLedger(lambda: path)
        first, second = CITE, ApprovalCite("alpha", OTHER_ID)
        assert sorted([first.event_id, second.event_id]) == [second.event_id, first.event_id]
        assert ledger.consume(first, PUSH) is LedgerOutcome.CONSUMED
        assert ledger.consume(second, PUSH) is LedgerOutcome.CONSUMED
        stored = json.loads(path.read_text(encoding="utf-8"))["used"]
        assert stored == [["alpha", fx.HUMAN_ID, "push"], ["alpha", OTHER_ID, "push"]]

    def test_a_failed_rename_leaves_no_temporary_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = tmp_path / "state"
        path = state / "ledger.json"

        def refuse(self: Path, target: Any) -> Path:
            raise OSError("rename refused")

        monkeypatch.setattr(Path, "replace", refuse)
        assert CiteLedger(lambda: path).consume(CITE, PUSH) is LedgerOutcome.UNAVAILABLE
        assert list(state.iterdir()) == []

    def test_a_ledger_under_a_file_is_unreadable_and_refuses(self, tmp_path: Path) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("", encoding="utf-8")
        ledger = CiteLedger(lambda: blocker / "ledger.json")  # parent is a file
        verdict = check(policy=self.POLICY, ledger=ledger)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.LEDGER_UNAVAILABLE)

    def test_a_ledger_that_reads_but_cannot_be_written_refuses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("", encoding="utf-8")
        monkeypatch.setattr(human_approval, "unique_temp_path", lambda path: blocker / "x.tmp")
        path = tmp_path / "ledger.json"
        verifier = FixedVerifier(human_line())
        verdict = check(policy=self.POLICY, ledger=CiteLedger(lambda: path), verifier=verifier)
        assert (verdict.passed, verdict.refusal) == (False, Refusal.LEDGER_UNAVAILABLE)
        assert len(verifier.calls) == 1  # the read succeeded; the write is what failed
        assert not path.exists()

    def test_the_ledger_never_holds_the_line_text(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.json"
        verifier = TeamchatVerifyCli(runner=answering(fx.verify_answer()))
        assert check(policy=self.POLICY, ledger=CiteLedger(lambda: path), verifier=verifier).passed
        stored = path.read_text(encoding="utf-8")
        assert "go ahead" not in stored
        assert json.loads(stored) == {"v": 1, "used": [["alpha", fx.HUMAN_ID, "push"]]}

    def test_consume_is_check_and_set(self, tmp_path: Path) -> None:
        ledger = self.ledger(tmp_path)
        assert ledger.consume(CITE, PUSH) is LedgerOutcome.CONSUMED
        assert ledger.consume(CITE, PUSH) is LedgerOutcome.ALREADY_USED
        assert ledger.used(CITE, PUSH) is LedgerOutcome.ALREADY_USED
        assert ledger.used(CITE, frozenset({ActClass.DELETE})) is LedgerOutcome.UNUSED


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

    def test_go_does_not_cover_a_subagent_by_default(self) -> None:
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
        """Invariant 5: with the ledger off, no file anywhere is touched by a check."""
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
        for answer in (fx.verify_answer(), fx.verify_answer(human=False), fx.NOT_JSON):
            check(verifier=TeamchatVerifyCli(runner=answering(answer)))
        assert touched == []

    def test_the_ledger_is_never_resolved_while_single_use_is_off(self) -> None:
        resolved: list[bool] = []

        def path() -> Path:
            resolved.append(True)
            raise AssertionError("ledger path resolved with single_use off")

        assert check(ledger=CiteLedger(path)).passed is True
        assert resolved == []

    def test_no_refusal_reason_is_built_from_answer_content(self) -> None:
        marker = "answer-content-marker"
        cases: list[dict[str, Any]] = [
            {"text": marker, "human": False},
            {"text": marker, "room": "main"},
            {"headline": marker, "team": "beta"},
        ]
        for overrides in cases:
            runner = answering(fx.verify_answer(**overrides))
            verdict = check(verifier=TeamchatVerifyCli(runner=runner))
            assert marker not in verdict.reason

    def test_module_has_no_v1_or_history_path(self) -> None:
        source = Path(human_approval.__file__).read_text(encoding="utf-8").lower()
        assert "pingbus" not in source
        assert "history" not in source
        assert "password" not in source
