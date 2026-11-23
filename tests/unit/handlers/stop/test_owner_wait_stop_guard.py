"""Tests for the coordinator owner-wait Stop guard (Plan 00636 Task 2.1a, 00630 DESIGN.md 20.1).

A coordinator seat that stops waiting on a human must have bumped every open
owner-facing thread it asked or owns with a NOTIFYING post recently; the team
chat is the only human surface. Deterministic: ids, timestamps, notify flag.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from tests.support.autonomy import awaiting_human_entry, pin_session_modes

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.handlers.stop import owner_wait_stop_guard as guard_module
from claude_code_hooks_daemon.handlers.stop.owner_wait_stop_guard import (
    DEFAULT_WINDOW_MINUTES,
    OwnerWaitStopGuardHandler,
)
from claude_code_hooks_daemon.utils.owner_wait_bus import BusUnreadable, TeamchatOwnerWaitBus
from claude_code_hooks_daemon.utils.owner_wait_check import (
    BusPost,
    BusSnapshot,
    OwnerThread,
    ThreadKind,
)
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ProbeReason,
    RoleKind,
    SeatContext,
    SeatState,
    SessionSignals,
    TeamSeat,
)

NOW = 1_000_000.0
SESSION = "sess-1"
WAITING = "STOPPING BECAUSE: waiting on the owner's answers to Q61 and Q64."
NOT_WAITING = "STOPPING BECAUSE: all tasks complete, QA passes."


def _seats(role: str | None = "coordinator", team: str = "alpha") -> SeatContext:
    kind = RoleKind.DECLARED if role is not None else RoleKind.UNKNOWN
    seat = TeamSeat(team=team, role_kind=kind, role=role or "", duty="lead" if role else "")
    return SeatContext(SeatState.RESOLVED, ProbeReason.RESOLVED, (seat,))


class _FakeBus:
    def __init__(self, result: BusSnapshot | BusUnreadable, *, flags: bool = True) -> None:
        self.result = result
        self.flags = flags
        self.reads: list[str] = []

    def flags_readable(self) -> bool:
        return self.flags

    def read(self, team: str, signals: SessionSignals) -> BusSnapshot | BusUnreadable:
        self.reads.append(team)
        return self.result

    def bump_command(self, team: str, thread_ids: Sequence[str]) -> str:
        return "teamchat bump " + " ".join(thread_ids)

    def notify_commands(self, team: str) -> tuple[str, str]:
        return (
            f"pingbus thread --team {team} Q<n> --ask",
            f"pingbus thread --team {team} --re <event id> --ask",
        )


class _Handler(OwnerWaitStopGuardHandler):
    def __init__(
        self, context: SeatContext | None, bus: _FakeBus, *, on_unreadable_bus: object = "refuse"
    ) -> None:
        super().__init__()
        self._on_unreadable_bus = on_unreadable_bus
        self._context = context
        self._bus = bus
        self._clock = lambda: NOW
        self.resolved = 0

    def _resolve_seats(self, signals: SessionSignals) -> SeatContext:
        self.resolved += 1
        if self._context is None:
            raise AssertionError("the probe must not run for this event")
        return self._context


def _question(thread_id: str = "Q61", *, open_: bool = True) -> OwnerThread:
    return OwnerThread(thread_id, f"${thread_id}root", ThreadKind.SEAT_QUESTION, is_open=open_)


def _bump(
    thread_id: str = "Q61", *, at: float = NOW - 60, notifying: bool | None = True
) -> BusPost:
    return BusPost(
        event_id="$p",
        timestamp=at,
        from_self=True,
        notifying=notifying,
        thread_root=f"${thread_id}root",
        body="still waiting: which branch to retire?",
    )


def _snapshot(*threads: OwnerThread, posts: tuple[BusPost, ...] = ()) -> BusSnapshot:
    return BusSnapshot(threads=threads, posts=posts)


def _assistant(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _feedback(reason: str) -> dict[str, Any]:
    """The transcript entry Claude Code writes after a Stop-hook deny."""
    return {
        "type": "user",
        "message": {"role": "user", "content": f"Stop hook feedback:\n{reason}"},
    }


OWN_BLOCK: Final[str] = f"BLOCKED [{RuleID.STOP_OWNER_WAIT_UNBUMPED}]: post a notifying reply"
OTHER_BLOCK: Final[str] = "BLOCKED [R-STOP-NO-REASON]: explain why you are stopping"


def _transcript(tmp_path: Path, text: str, before: Sequence[dict[str, Any]] = ()) -> str:
    path = tmp_path / "transcript.jsonl"
    entries = [*before, _assistant(text)]
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return str(path)


def _stop(
    tmp_path: Path,
    text: str = WAITING,
    *,
    before: Sequence[dict[str, Any]] = (),
    **extra: Any,
) -> dict[str, Any]:
    return {
        "hook_event_name": "Stop",
        "session_id": SESSION,
        "stop_hook_active": False,
        "transcript_path": _transcript(tmp_path, text, before),
        "teamchat_runtime": "/run/user/1000/teamchat/s1",
        "teamchat_kit": "/opt/teamchat",
        **extra,
    }


@pytest.fixture(autouse=True)
def _registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pin_session_modes(monkeypatch, tmp_path / "modes")


def _run(handler: _Handler, hook_input: dict[str, Any]) -> Any:
    if not handler.matches(hook_input):
        return None
    return handler.handle(hook_input)


class TestIdentity:
    def test_wiring(self) -> None:
        handler = OwnerWaitStopGuardHandler()
        assert handler.handler_id == HandlerID.OWNER_WAIT_STOP_GUARD
        assert handler.priority == Priority.OWNER_WAIT_STOP_GUARD
        assert handler.terminal is False
        assert handler.scope is HandlerScope.MAIN
        assert [rule.rule_id for rule in handler.get_rules()] == [RuleID.STOP_OWNER_WAIT_UNBUMPED]


class TestDeny:
    def test_unbumped_question_is_denied_with_one_bump_command(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question()))
        result = _run(_Handler(_seats(), bus), _stop(tmp_path))
        assert result.decision is Decision.DENY
        assert "Q61" in result.reason
        assert "teamchat bump Q61" in result.reason

    def test_several_stale_threads_produce_one_command(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question("Q61"), _question("Q64")))
        result = _run(_Handler(_seats(), bus), _stop(tmp_path))
        assert result.decision is Decision.DENY
        assert result.reason.count("teamchat bump") == 1
        assert "teamchat bump Q61 Q64" in result.reason

    def test_plain_post_does_not_satisfy(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question(), posts=(_bump(notifying=False),)))
        assert _run(_Handler(_seats(), bus), _stop(tmp_path)).decision is Decision.DENY

    def test_unreadable_notify_flag_counts_as_non_notifying(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question(), posts=(_bump(notifying=None),)))
        result = _run(_Handler(_seats(), bus), _stop(tmp_path))
        assert result.decision is Decision.DENY
        assert "notify" in result.reason

    def test_stale_bump_is_denied(self, tmp_path: Path) -> None:
        old = NOW - DEFAULT_WINDOW_MINUTES * 60 - 1
        bus = _FakeBus(_snapshot(_question(), posts=(_bump(at=old),)))
        assert _run(_Handler(_seats(), bus), _stop(tmp_path)).decision is Decision.DENY

    def test_owned_question_is_required_even_when_the_stop_names_none(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question("Q70")))
        text = "STOPPING BECAUSE: [awaiting-human] the owner must choose."
        result = _run(_Handler(_seats(), bus), _stop(tmp_path, text))
        assert result.decision is Decision.DENY
        assert "Q70" in result.reason

    def test_awaiting_human_mode_alone_is_detected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path / "modes2", awaiting_human_entry(SESSION))
        bus = _FakeBus(_snapshot(_question()))
        result = _run(_Handler(_seats(), bus), _stop(tmp_path, "done for now"))
        assert result.decision is Decision.DENY

    def test_deny_names_ids_only_and_never_bus_text(self, tmp_path: Path) -> None:
        post = BusPost("$p", NOW - 60, True, False, "$Q61root", body="SECRET-ASK-TEXT")
        bus = _FakeBus(_snapshot(_question(), posts=(post,)))
        result = _run(_Handler(_seats(), bus), _stop(tmp_path))
        assert "SECRET-ASK-TEXT" not in result.reason
        assert "Q61" in result.reason


class TestAllow:
    def test_recent_notifying_bump_passes(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question(), posts=(_bump(),)))
        assert _run(_Handler(_seats(), bus), _stop(tmp_path)).decision is Decision.ALLOW

    def test_stop_not_waiting_on_a_human_is_untouched(self, tmp_path: Path) -> None:
        handler = _Handler(None, _FakeBus(_snapshot(_question())))
        assert _run(handler, _stop(tmp_path, NOT_WAITING)) is None
        assert handler.resolved == 0

    def test_worker_seat_is_untouched(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question()))
        result = _run(_Handler(_seats("worker"), bus), _stop(tmp_path))
        assert result.decision is Decision.ALLOW
        assert bus.reads == []

    def test_unknown_role_is_untouched(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question()))
        result = _run(_Handler(_seats(None), bus), _stop(tmp_path))
        assert result.decision is Decision.ALLOW
        assert bus.reads == []

    def test_unresolved_probe_is_untouched(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question()))
        context = SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
        assert _run(_Handler(context, bus), _stop(tmp_path)).decision is Decision.ALLOW
        assert bus.reads == []

    def test_no_team_runs_no_probe(self, tmp_path: Path) -> None:
        handler = _Handler(None, _FakeBus(_snapshot(_question())))
        hook_input = _stop(tmp_path)
        del hook_input["teamchat_runtime"]
        assert _run(handler, hook_input) is None
        assert handler.resolved == 0

    def test_subagent_stop_is_untouched(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question()))
        result = _run(_Handler(_seats(), bus), _stop(tmp_path, agent_id="agent-123"))
        assert result is None or result.decision is Decision.ALLOW
        assert bus.reads == []

    def test_reentry_after_own_deny_passes(self, tmp_path: Path) -> None:
        handler = _Handler(None, _FakeBus(_snapshot(_question())))
        hook_input = _stop(tmp_path, before=[_feedback(OWN_BLOCK)], stop_hook_active=True)
        assert _run(handler, hook_input) is None
        assert handler.resolved == 0


class TestReentry:
    """F3: only THIS guard's own refusal earns the one-shot pass on a re-entered stop."""

    def test_another_handlers_deny_does_not_skip_the_check(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question()))
        hook_input = _stop(tmp_path, before=[_feedback(OTHER_BLOCK)], stop_hook_active=True)
        result = _run(_Handler(_seats(), bus), hook_input)
        assert result.decision is Decision.DENY

    def test_spurious_stop_hook_active_is_evaluated(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question()))
        result = _run(_Handler(_seats(), bus), _stop(tmp_path, stop_hook_active=True))
        assert result.decision is Decision.DENY

    def test_own_deny_then_another_deny_still_passes(self, tmp_path: Path) -> None:
        handler = _Handler(None, _FakeBus(_snapshot(_question())))
        before = [_feedback(OWN_BLOCK), _assistant("ok"), _feedback(OTHER_BLOCK)]
        assert _run(handler, _stop(tmp_path, before=before, stop_hook_active=True)) is None

    def test_own_deny_followed_by_a_long_bump_turn_still_passes(self, tmp_path: Path) -> None:
        handler = _Handler(None, _FakeBus(_snapshot(_question())))
        before = [_feedback(OWN_BLOCK), *([_assistant("posting bumps")] * 60)]
        assert _run(handler, _stop(tmp_path, before=before, stop_hook_active=True)) is None

    def test_unreadable_transcript_on_reentry_stands_down(self, tmp_path: Path) -> None:
        handler = _Handler(None, _FakeBus(_snapshot(_question())))
        hook_input = _stop(tmp_path, stop_hook_active=True)
        hook_input["transcript_path"] = str(tmp_path / "missing.jsonl")
        assert _run(handler, hook_input) is None

    def test_a_raising_reentry_check_stands_down(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_args: object, **_kwargs: object) -> tuple[str, ...]:
            raise OSError("disk")

        monkeypatch.setattr(guard_module, "recent_stop_hook_block_texts", _boom)
        handler = _Handler(None, _FakeBus(_snapshot(_question())))
        assert _run(handler, _stop(tmp_path, stop_hook_active=True)) is None

    def test_reentered_v1_stop_carries_no_repeat_advisory(self, tmp_path: Path) -> None:
        """The auto advisory continues one turn; re-emitting it on that re-stop would loop."""
        bus = _FakeBus(BusUnreadable("history timed out"), flags=False)
        handler = _Handler(_seats(), bus, on_unreadable_bus="auto")
        result = _run(handler, _stop(tmp_path, stop_hook_active=True))
        assert result is None or (result.decision is Decision.ALLOW and result.context == [])


class _Broken(_FakeBus):
    def read(self, team: str, signals: SessionSignals) -> BusSnapshot | BusUnreadable:
        raise OSError("boom")


def _multi_seats() -> SeatContext:
    seats = (
        TeamSeat(team="alpha", role_kind=RoleKind.DECLARED, role="coordinator", duty="lead"),
        TeamSeat(team="beta", role_kind=RoleKind.DECLARED, role="worker", duty="lead"),
    )
    return SeatContext(SeatState.RESOLVED, ProbeReason.RESOLVED, seats)


class TestUnreadableBusAllow:
    """``on_unreadable_bus: allow`` -- the escape hatch: fail open, loudly."""

    def test_unreadable_bus_passes_with_a_loud_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"))
        with caplog.at_level(logging.WARNING):
            result = _run(_Handler(_seats(), bus, on_unreadable_bus="allow"), _stop(tmp_path))
        assert result.decision is Decision.ALLOW
        assert any("history timed out" in rec.getMessage() for rec in caplog.records)
        assert any(rec.levelno >= logging.WARNING for rec in caplog.records)

    def test_a_raising_bus_passes(self, tmp_path: Path) -> None:
        handler = _Handler(_seats(), _Broken(BusSnapshot()), on_unreadable_bus="allow")
        assert _run(handler, _stop(tmp_path)).decision is Decision.ALLOW


class _V1Broken(_Broken):
    def flags_readable(self) -> bool:
        return False


class _FlagsRaise(_FakeBus):
    def flags_readable(self) -> bool:
        raise OSError("probe failed")


def _advisory(result: Any) -> str:
    return "\n".join(result.context)


class TestUnreadableBusAuto:
    """``on_unreadable_bus: auto`` (the default): refuse only where the adapter can read flags.

    On pingbus v1 the adapter cannot read the notify flag at all, so ``refuse``
    would refuse every waiting coordinator stop. ``auto`` allows there, with an
    advisory naming the team and the thread classes it could not check (v1
    cannot list thread ids), and refuses once the adapter reports flags readable.
    """

    def test_default_is_auto(self) -> None:
        assert OwnerWaitStopGuardHandler()._on_unreadable_bus == "auto"

    def test_production_adapter_reports_flags_unreadable(self) -> None:
        assert TeamchatOwnerWaitBus().flags_readable() is False

    def test_flags_readable_adapter_refuses(self, tmp_path: Path) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"), flags=True)
        result = _run(_Handler(_seats(), bus, on_unreadable_bus="auto"), _stop(tmp_path))
        assert result.decision is Decision.DENY
        assert "--team alpha" in result.reason

    def test_v1_adapter_allows_with_an_advisory(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"), flags=False)
        with caplog.at_level(logging.WARNING):
            result = _run(_Handler(_seats(), bus, on_unreadable_bus="auto"), _stop(tmp_path))
        assert result.decision is Decision.ALLOW
        advisory = _advisory(result)
        assert "team alpha" in advisory
        assert "owner-started" in advisory
        assert "open question" in advisory
        assert "pingbus thread --team alpha Q<n> --ask" in advisory
        assert "pingbus thread --team alpha --re <event id> --ask" in advisory
        assert any(rec.levelno >= logging.WARNING for rec in caplog.records)

    def test_v1_advisory_does_not_restate_the_waits(self, tmp_path: Path) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"), flags=False)
        result = _run(_Handler(_seats(), bus, on_unreadable_bus="auto"), _stop(tmp_path))
        advisory = _advisory(result)
        assert "Q61" not in advisory
        assert "owner's answers" not in advisory

    def test_v1_raising_bus_allows_with_an_advisory(self, tmp_path: Path) -> None:
        handler = _Handler(_seats(), _V1Broken(BusSnapshot()), on_unreadable_bus="auto")
        result = _run(handler, _stop(tmp_path))
        assert result.decision is Decision.ALLOW
        assert "team alpha" in _advisory(result)
        assert "boom" not in _advisory(result)

    def test_a_raising_flags_probe_is_treated_as_unreadable_flags(self, tmp_path: Path) -> None:
        bus = _FlagsRaise(BusUnreadable("history timed out"))
        result = _run(_Handler(_seats(), bus, on_unreadable_bus="auto"), _stop(tmp_path))
        assert result.decision is Decision.ALLOW
        assert "team alpha" in _advisory(result)

    def test_v1_stale_threads_on_a_readable_team_still_deny(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question("Q61")), flags=False)
        result = _run(_Handler(_seats(), bus, on_unreadable_bus="auto"), _stop(tmp_path))
        assert result.decision is Decision.DENY
        assert "teamchat bump Q61" in result.reason

    def test_readable_and_notified_carries_no_advisory(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question(), posts=(_bump(),)), flags=False)
        result = _run(_Handler(_seats(), bus, on_unreadable_bus="auto"), _stop(tmp_path))
        assert result.decision is Decision.ALLOW
        assert result.context == []

    def test_a_deny_also_carries_the_unchecked_team_advisory(self, tmp_path: Path) -> None:
        class _PerTeam(_FakeBus):
            def read(self, team: str, signals: SessionSignals) -> BusSnapshot | BusUnreadable:
                if team == "alpha":
                    return _snapshot(_question("Q61"))
                return BusUnreadable("history timed out")

        seats = (
            TeamSeat(team="alpha", role_kind=RoleKind.DECLARED, role="coordinator"),
            TeamSeat(team="gamma", role_kind=RoleKind.DECLARED, role="coordinator"),
        )
        context = SeatContext(SeatState.RESOLVED, ProbeReason.RESOLVED, seats)
        bus = _PerTeam(BusSnapshot(), flags=False)
        result = _run(_Handler(context, bus, on_unreadable_bus="auto"), _stop(tmp_path))
        assert result.decision is Decision.DENY
        assert "teamchat bump Q61" in result.reason
        assert "team gamma" in result.reason

    def test_explicit_refuse_still_refuses_on_v1(self, tmp_path: Path) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"), flags=False)
        result = _run(_Handler(_seats(), bus, on_unreadable_bus="refuse"), _stop(tmp_path))
        assert result.decision is Decision.DENY

    @pytest.mark.parametrize("flags", [True, False])
    @pytest.mark.parametrize("bad", ["deny", "", None, 1, True])
    def test_invalid_value_falls_back_to_auto_and_logs(
        self, bad: object, flags: bool, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"), flags=flags)
        with caplog.at_level(logging.WARNING):
            result = _run(_Handler(_seats(), bus, on_unreadable_bus=bad), _stop(tmp_path))
        assert result.decision is (Decision.DENY if flags else Decision.ALLOW)
        assert any("on_unreadable_bus" in rec.getMessage() for rec in caplog.records)

    def test_example_config_writes_no_literal_refuse(self) -> None:
        example = Path(__file__).parents[4] / ".claude" / "hooks-daemon.yaml.example"
        assert "on_unreadable_bus: refuse" not in example.read_text(encoding="utf-8")


class TestUnreadableBusRefuse:
    """``on_unreadable_bus: refuse`` -- an unverifiable wait fails closed, whatever the adapter."""

    def test_unreadable_bus_is_refused_with_a_loud_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"))
        with caplog.at_level(logging.WARNING):
            result = _run(_Handler(_seats(), bus), _stop(tmp_path))
        assert result.decision is Decision.DENY
        assert any("history timed out" in rec.getMessage() for rec in caplog.records)
        assert any(rec.levelno >= logging.WARNING for rec in caplog.records)

    def test_refusal_text_names_the_notifying_reply_and_the_restop(self, tmp_path: Path) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"))
        reason = _run(_Handler(_seats(), bus), _stop(tmp_path)).reason
        assert "pingbus thread --team alpha Q<n> --ask" in reason
        assert "pingbus thread --team alpha --re <event id> --ask" in reason
        assert "stop again" in reason

    def test_refusal_text_says_why_it_could_not_be_confirmed(self, tmp_path: Path) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"))
        reason = _run(_Handler(_seats(), bus), _stop(tmp_path)).reason
        assert "history timed out" in reason
        assert "notify flag" in reason
        assert "m.thread" in reason
        assert "unverified" in reason

    def test_refusal_text_does_not_restate_the_waits(self, tmp_path: Path) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"))
        reason = _run(_Handler(_seats(), bus), _stop(tmp_path)).reason
        assert "Q61" not in reason
        assert "Q64" not in reason
        assert "owner's answers" not in reason
        assert "teamchat bump" not in reason

    def test_a_raising_bus_is_refused(self, tmp_path: Path) -> None:
        result = _run(_Handler(_seats(), _Broken(BusSnapshot())), _stop(tmp_path))
        assert result.decision is Decision.DENY
        assert "boom" not in result.reason

    def test_only_a_coordinator_team_can_refuse(self, tmp_path: Path) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"))
        result = _run(_Handler(_multi_seats(), bus), _stop(tmp_path))
        assert result.decision is Decision.DENY
        assert bus.reads == ["alpha"]
        assert "--team beta" not in result.reason

    def test_worker_seat_is_untouched(self, tmp_path: Path) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"))
        result = _run(_Handler(_seats("worker"), bus), _stop(tmp_path))
        assert result.decision is Decision.ALLOW
        assert bus.reads == []

    def test_no_team_seat_is_untouched(self, tmp_path: Path) -> None:
        handler = _Handler(None, _FakeBus(BusUnreadable("history timed out")))
        hook_input = _stop(tmp_path)
        del hook_input["teamchat_runtime"]
        assert _run(handler, hook_input) is None

    def test_reentry_is_never_trapped(self, tmp_path: Path) -> None:
        handler = _Handler(None, _FakeBus(BusUnreadable("history timed out")))
        hook_input = _stop(tmp_path, before=[_feedback(OWN_BLOCK)], stop_hook_active=True)
        assert _run(handler, hook_input) is None

    def test_the_real_deny_text_is_recognised_on_reentry(self, tmp_path: Path) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"))
        first = _run(_Handler(_seats(), bus), _stop(tmp_path))
        assert first.decision is Decision.DENY
        handler = _Handler(None, bus)
        hook_input = _stop(tmp_path, before=[_feedback(first.reason)], stop_hook_active=True)
        assert _run(handler, hook_input) is None

    def test_stale_threads_and_an_unreadable_team_are_both_reported(self, tmp_path: Path) -> None:
        class _PerTeam(_FakeBus):
            def read(self, team: str, signals: SessionSignals) -> BusSnapshot | BusUnreadable:
                self.reads.append(team)
                if team == "alpha":
                    return _snapshot(_question("Q61"))
                return BusUnreadable("history timed out")

        seats = (
            TeamSeat(team="alpha", role_kind=RoleKind.DECLARED, role="coordinator"),
            TeamSeat(team="gamma", role_kind=RoleKind.DECLARED, role="coordinator"),
        )
        context = SeatContext(SeatState.RESOLVED, ProbeReason.RESOLVED, seats)
        reason = _run(_Handler(context, _PerTeam(BusSnapshot())), _stop(tmp_path)).reason
        assert "teamchat bump Q61" in reason
        assert "--team gamma" in reason

    @pytest.mark.parametrize("bad", ["deny", "", None, 1, True])
    def test_invalid_value_falls_back_to_refuse_and_logs(
        self, bad: object, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"))
        with caplog.at_level(logging.WARNING):
            result = _run(_Handler(_seats(), bus, on_unreadable_bus=bad), _stop(tmp_path))
        assert result.decision is Decision.DENY
        assert any("on_unreadable_bus" in rec.getMessage() for rec in caplog.records)


class TestWindowOption:
    def test_window_is_read_from_config(self, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question(), posts=(_bump(at=NOW - 5 * 60),)))
        handler = _Handler(_seats(), bus)
        handler._window_minutes = 2
        assert _run(handler, _stop(tmp_path)).decision is Decision.DENY

    @pytest.mark.parametrize("bad", [0, -5, "ten", True, 100_000])
    def test_invalid_window_falls_back_to_default_and_logs(
        self, bad: object, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        bus = _FakeBus(_snapshot(_question(), posts=(_bump(at=NOW - 60),)))
        handler = _Handler(_seats(), bus)
        handler._window_minutes = bad
        with caplog.at_level(logging.WARNING):
            result = _run(handler, _stop(tmp_path))
        assert result.decision is Decision.ALLOW
        assert any("window_minutes" in rec.getMessage() for rec in caplog.records)


class TestWaitingDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "STOPPING BECAUSE: waiting for answers on the open questions.",
            "STOPPING BECAUSE: awaiting the owner's decision.",
            "STOPPING BECAUSE: [awaiting-human] owner must pick.",
        ],
    )
    def test_waiting_texts_are_detected(self, text: str, tmp_path: Path) -> None:
        bus = _FakeBus(_snapshot(_question()))
        assert _run(_Handler(_seats(), bus), _stop(tmp_path, text)).decision is Decision.DENY

    def test_waiting_phrase_inside_a_code_fence_is_not_a_declaration(self, tmp_path: Path) -> None:
        text = "STOPPING BECAUSE: done.\n```\nSTOPPING BECAUSE: waiting on the owner\n```"
        handler = _Handler(None, _FakeBus(_snapshot(_question())))
        assert _run(handler, _stop(tmp_path, text)) is None
