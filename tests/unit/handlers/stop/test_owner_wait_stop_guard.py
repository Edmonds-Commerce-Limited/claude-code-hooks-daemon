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
from typing import Any

import pytest
from tests.support.autonomy import awaiting_human_entry, pin_session_modes

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.handlers.stop.owner_wait_stop_guard import (
    DEFAULT_WINDOW_MINUTES,
    OwnerWaitStopGuardHandler,
)
from claude_code_hooks_daemon.utils.owner_wait_bus import BusUnreadable
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
    def __init__(self, result: BusSnapshot | BusUnreadable) -> None:
        self.result = result
        self.reads: list[str] = []

    def read(self, team: str, signals: SessionSignals) -> BusSnapshot | BusUnreadable:
        self.reads.append(team)
        return self.result

    def bump_command(self, team: str, thread_ids: Sequence[str]) -> str:
        return "teamchat bump " + " ".join(thread_ids)


class _Handler(OwnerWaitStopGuardHandler):
    def __init__(self, context: SeatContext | None, bus: _FakeBus) -> None:
        super().__init__()
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


def _bump(thread_id: str = "Q61", *, at: float = NOW - 60, notifying: bool | None = True) -> BusPost:
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


def _transcript(tmp_path: Path, text: str) -> str:
    path = tmp_path / "transcript.jsonl"
    message = {
        "type": "message",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }
    path.write_text(json.dumps(message) + "\n", encoding="utf-8")
    return str(path)


def _stop(tmp_path: Path, text: str = WAITING, **extra: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "Stop",
        "session_id": SESSION,
        "stop_hook_active": False,
        "transcript_path": _transcript(tmp_path, text),
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
        assert handler.handler_id == HandlerID.OWNER_WAIT_STOP_GUARD.config_key
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

    def test_owned_question_is_required_even_when_the_stop_names_none(
        self, tmp_path: Path
    ) -> None:
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

    def test_reentry_after_a_deny_passes(self, tmp_path: Path) -> None:
        handler = _Handler(None, _FakeBus(_snapshot(_question())))
        hook_input = _stop(tmp_path, stop_hook_active=True)
        assert _run(handler, hook_input) is None
        assert handler.resolved == 0

    def test_unreadable_bus_passes_with_a_loud_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        bus = _FakeBus(BusUnreadable("history timed out"))
        with caplog.at_level(logging.WARNING):
            result = _run(_Handler(_seats(), bus), _stop(tmp_path))
        assert result.decision is Decision.ALLOW
        assert any("history timed out" in rec.getMessage() for rec in caplog.records)
        assert any(rec.levelno >= logging.WARNING for rec in caplog.records)

    def test_a_raising_bus_fails_open(self, tmp_path: Path) -> None:
        class _Broken(_FakeBus):
            def read(self, team: str, signals: SessionSignals) -> BusSnapshot | BusUnreadable:
                raise OSError("boom")

        result = _run(_Handler(_seats(), _Broken(BusSnapshot())), _stop(tmp_path))
        assert result.decision is Decision.ALLOW


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

    def test_waiting_phrase_inside_a_code_fence_is_not_a_declaration(
        self, tmp_path: Path
    ) -> None:
        text = "STOPPING BECAUSE: done.\n```\nSTOPPING BECAUSE: waiting on the owner\n```"
        handler = _Handler(None, _FakeBus(_snapshot(_question())))
        assert _run(handler, _stop(tmp_path, text)) is None
