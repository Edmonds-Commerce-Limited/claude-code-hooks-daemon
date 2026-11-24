"""Plan 00636 Task 2.4 (s8 wind-down, advise-only part).

A coordinator that stops while its background agents run, with no
``STOPPING BECAUSE:`` line, is refused by ``R-STOP-NO-REASON`` and learns
nothing about why the wait is fine to declare. The refusal now carries a
wind-down note naming the running tasks and the one stop line that passes.

The note rides ONLY on that existing refusal: a Stop ALLOW that carries
context makes Claude Code continue the conversation (``hook_result``'s
loop-breaker), so a standalone advisory would itself cost a failed stop.
Nothing here adds an allow path or removes a deny.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import AutoContinueStopHandler
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ProbeReason,
    RoleKind,
    SeatContext,
    SeatState,
    SessionSignals,
    TeamSeat,
)
from claude_code_hooks_daemon.utils.wind_down import WIND_DOWN_HEADING, suggested_stop_line

_RUNNING = [
    {"id": "agent-a1", "type": "subagent", "status": "running"},
    {"id": "agent-a2", "type": "subagent", "status": "running"},
]


def _seats(role: str | None = "coordinator") -> SeatContext:
    kind = RoleKind.DECLARED if role is not None else RoleKind.UNKNOWN
    seat = TeamSeat(team="alpha", role_kind=kind, role=role or "", duty="lead" if role else "")
    return SeatContext(SeatState.RESOLVED, ProbeReason.RESOLVED, (seat,))


class _Resolver:
    def __init__(self, context: SeatContext | Exception) -> None:
        self.context = context
        self.calls = 0

    def resolve(self, signals: SessionSignals) -> SeatContext:
        self.calls += 1
        if isinstance(self.context, Exception):
            raise self.context
        return self.context


@pytest.fixture(autouse=True)
def _project(tmp_path: Path) -> Any:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "claude_code_hooks_daemon.handlers.stop.auto_continue_stop."
            "ProjectContext.daemon_untracked_dir",
            classmethod(lambda cls: tmp_path / "untracked"),
        )
        mp.setattr(
            "claude_code_hooks_daemon.handlers.stop.auto_continue_stop."
            "ProjectContext.project_root",
            classmethod(lambda cls: tmp_path),
        )
        yield


def _handler(context: SeatContext | Exception | None = None) -> AutoContinueStopHandler:
    handler = AutoContinueStopHandler()
    handler._resolver = _Resolver(context if context is not None else _seats())
    return handler


def _stop(tasks: Any = _RUNNING, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"hook_event_name": "Stop", "stop_hook_active": False}
    if tasks is not None:
        payload["background_tasks"] = tasks
    payload.update(extra)
    return payload


class TestCoordinatorStopAroundRunningAgents:
    def test_no_reason_refusal_carries_the_wind_down_note(self) -> None:
        result = _handler().handle(_stop())
        assert result.decision == Decision.DENY
        assert result.rule == RuleID.STOP_NO_REASON
        assert result.reason is not None
        assert WIND_DOWN_HEADING in result.reason
        assert "`agent-a1`" in result.reason
        assert "STOPPING BECAUSE: 2 background tasks are still running" in result.reason

    def test_the_note_follows_the_refusal_on_every_fire(self) -> None:
        handler = _handler()
        payload = _stop(transcript_path="/nonexistent/t.jsonl")
        handler.handle(payload)
        second = handler.handle(payload)
        assert second.reason is not None
        assert WIND_DOWN_HEADING in second.reason

    def test_unreadable_role_stays_armed(self) -> None:
        result = _handler(_seats(role=None)).handle(_stop())
        assert result.reason is not None
        assert WIND_DOWN_HEADING in result.reason

    def test_unresolved_probe_stays_armed(self) -> None:
        unresolved = SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
        result = _handler(unresolved).handle(_stop())
        assert result.reason is not None
        assert WIND_DOWN_HEADING in result.reason

    def test_a_raising_resolver_counts_as_armed(self) -> None:
        result = _handler(RuntimeError("probe broke")).handle(_stop())
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert WIND_DOWN_HEADING in result.reason


class TestUntouched:
    def test_absent_team_gets_the_unchanged_refusal(self) -> None:
        absent = SeatContext.absent(ProbeReason.NO_RUNTIME_SIGNAL)
        result = _handler(absent).handle(_stop())
        assert result.decision == Decision.DENY
        assert result.rule == RuleID.STOP_NO_REASON
        assert result.reason is not None
        assert WIND_DOWN_HEADING not in result.reason

    def test_declared_worker_gets_the_unchanged_refusal(self) -> None:
        result = _handler(_seats(role="worker")).handle(_stop())
        assert result.reason is not None
        assert WIND_DOWN_HEADING not in result.reason

    def test_sub_agent_payload_gets_no_note(self) -> None:
        result = _handler().handle(_stop(agent_id="a1b2c3d4e5f6a7b8c"))
        assert result.reason is not None
        assert WIND_DOWN_HEADING not in result.reason

    @pytest.mark.parametrize(
        "tasks",
        [None, [], "running", [{"id": "x", "status": "completed"}]],
        ids=["absent", "empty", "malformed", "none-running"],
    )
    def test_no_running_task_means_no_note_and_no_probe(self, tasks: Any) -> None:
        handler = _handler()
        result = handler.handle(_stop(tasks))
        assert result.reason is not None
        assert WIND_DOWN_HEADING not in result.reason
        assert isinstance(handler._resolver, _Resolver)
        assert handler._resolver.calls == 0

    def test_explained_stop_is_still_allowed_with_no_note(self, tmp_path: Path) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": "STOPPING BECAUSE: 2 background tasks are still running.",
                            }
                        ],
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        handler = _handler()
        result = handler.handle(_stop(transcript_path=str(transcript)))
        assert result.decision == Decision.ALLOW
        assert not result.context
        assert isinstance(handler._resolver, _Resolver)
        assert handler._resolver.calls == 0


class TestSuggestedLineIsAccepted:
    @pytest.mark.parametrize("count", [1, 2])
    def test_the_suggested_line_is_allowed_where_the_note_was_shown(
        self, tmp_path: Path, count: int
    ) -> None:
        tasks = [
            {"id": f"agent-{n}", "type": "subagent", "status": "running"} for n in range(count)
        ]
        handler = _handler()
        refused = handler.handle(_stop(tasks))
        assert refused.decision == Decision.DENY
        assert refused.reason is not None
        assert suggested_stop_line(count) in refused.reason

        transcript = tmp_path / "t.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": suggested_stop_line(count)}],
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        result = handler.handle(_stop(tasks, transcript_path=str(transcript)))
        assert result.decision == Decision.ALLOW
