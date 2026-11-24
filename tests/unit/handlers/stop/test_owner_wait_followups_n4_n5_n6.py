"""Plan 00636 Task 2.1d: follow-ups N4, N5 and N6 from the PR 226 delta review.

N4: the guard asks for the stand-in cron only where auto_continue_stop would
(the stop line carries the ``STOPPING BECAUSE:`` prefix, a real session id).
N5: the guard's own refusal earns the re-entry pass only within the CURRENT stop
chain (after the last real user prompt), not from an earlier chain.
N6: an unreadable stop message is not announced as a wait on a human.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.support.autonomy import pin_session_modes
from tests.unit.handlers.stop.test_owner_wait_stand_in_cooperation import (
    AWAITING,
    ENABLED,
    STAND_IN_HEADLINE,
    _assistant,
    _Bus,
    _chain,
    _feedback,
    _Guard,
    _run,
    _stale,
)

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.utils.owner_wait_bus import BusUnreadable
from claude_code_hooks_daemon.utils.stop_hook_helpers import recent_stop_hook_block_texts_this_chain

NO_PREFIX = "I am blocked only on human input: the owner has to choose between A and B (Q61)."
OWN_BLOCK = "BLOCKED [R-STOP-OWNER-WAIT-UNBUMPED]: post a notifying reply"


@pytest.fixture(autouse=True)
def _registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pin_session_modes(monkeypatch, tmp_path / "modes")


def _prompt(text: str = "carry on") -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _tool_result() -> dict[str, Any]:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
        },
    }


class TestN4StandInGateMatchesAutoContinue:
    def test_a_token_without_the_stop_prefix_asks_for_no_stand_in(self, tmp_path: Path) -> None:
        result = _run(_chain(_Bus(_stale())), tmp_path, [_assistant(NO_PREFIX)])
        assert result.decision is Decision.DENY
        assert "Q61" in result.reason
        assert STAND_IN_HEADLINE not in result.reason

    def test_a_prefixed_declaration_still_asks_for_it(self, tmp_path: Path) -> None:
        result = _run(_chain(_Bus(_stale())), tmp_path, [_assistant(AWAITING)])
        assert STAND_IN_HEADLINE in result.reason

    def test_a_stop_with_no_session_id_asks_for_no_stand_in(self, tmp_path: Path) -> None:
        # auto_continue_stop records no marker without a session id, so it asks for no stand-in.
        guard = _Guard(_Bus(_stale()), ENABLED)
        path = tmp_path / "t.jsonl"
        path.write_text(json.dumps(_assistant(AWAITING)) + "\n", encoding="utf-8")
        hook_input = {
            "hook_event_name": "Stop",
            "transcript_path": str(path),
            "stop_hook_active": False,
            "teamchat_runtime": "/run/user/1000/teamchat/s1",
            "teamchat_kit": "/opt/teamchat",
            "session_crons": [],
        }
        result = guard.handle(hook_input)
        assert result.decision is Decision.DENY
        assert STAND_IN_HEADLINE not in (result.reason or "")


class TestN5RefusalIsScopedToTheCurrentChain:
    def test_helper_ignores_blocks_before_the_last_real_prompt(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        entries = [_feedback(OWN_BLOCK), _prompt(), _assistant("x"), _feedback("BLOCKED [R-X]: y")]
        path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
        texts = recent_stop_hook_block_texts_this_chain(str(path), lookback=200)
        assert len(texts) == 1
        assert "R-X" in texts[0]

    def test_tool_results_and_feedback_are_not_prompts(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        entries = [_prompt(), _feedback(OWN_BLOCK), _tool_result(), _assistant("bump")]
        path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
        texts = recent_stop_hook_block_texts_this_chain(str(path), lookback=200)
        assert len(texts) == 1
        assert "R-STOP-OWNER-WAIT-UNBUMPED" in texts[0]

    def test_no_prompt_in_the_window_keeps_the_whole_window(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        path.write_text(json.dumps(_feedback(OWN_BLOCK)) + "\n", encoding="utf-8")
        assert len(recent_stop_hook_block_texts_this_chain(str(path), lookback=200)) == 1

    def test_an_earlier_chains_deny_does_not_pass_a_later_chain(self, tmp_path: Path) -> None:
        chain = _chain(_Bus(_stale()))
        first = _run(chain, tmp_path, [_assistant(AWAITING)])
        entries = [
            _assistant(AWAITING),
            _feedback(first.reason),
            _assistant(AWAITING),
            _prompt("a new task"),
            _feedback("BLOCKED [R-STOP-NO-REASON]: explain why you are stopping"),
            _assistant(AWAITING),
        ]
        result = _run(chain, tmp_path, entries, active=True)
        assert result.decision is Decision.DENY
        assert "R-STOP-OWNER-WAIT-UNBUMPED" in result.reason

    def test_the_same_chain_still_passes(self, tmp_path: Path) -> None:
        chain = _chain(_Bus(_stale()))
        first = _run(chain, tmp_path, [_assistant(AWAITING)])
        entries = [
            _prompt("start"),
            _assistant(AWAITING),
            _feedback(first.reason),
            _tool_result(),
            _assistant(AWAITING),
        ]
        result = _run(chain, tmp_path, entries, active=True)
        assert result.decision is Decision.ALLOW


class TestN6UnreadableStopMessageIsNotAnnouncedAsAWait:
    def test_v1_unreadable_message_carries_no_advisory(self, tmp_path: Path) -> None:
        class _V1(_Bus):
            def flags_readable(self) -> bool:
                return False

        guard = _Guard(_V1(BusUnreadable("x")), ENABLED)
        guard._on_unreadable_bus = "auto"
        hook_input: dict[str, Any] = {
            "hook_event_name": "Stop",
            "session_id": "lead",
            "transcript_path": str(tmp_path / "missing.jsonl"),
            "stop_hook_active": False,
            "teamchat_runtime": "/run/user/1000/teamchat/s1",
            "teamchat_kit": "/opt/teamchat",
        }
        assert guard.matches(hook_input) is True
        result = guard.handle(hook_input)
        assert result.decision is Decision.ALLOW
        assert result.context == []

    def test_unreadable_message_is_still_refused_where_flags_are_readable(
        self, tmp_path: Path
    ) -> None:
        guard = _Guard(_Bus(BusUnreadable("x")), ENABLED)
        guard._on_unreadable_bus = "auto"
        hook_input: dict[str, Any] = {
            "hook_event_name": "Stop",
            "session_id": "lead",
            "transcript_path": str(tmp_path / "missing.jsonl"),
            "stop_hook_active": False,
            "teamchat_runtime": "/run/user/1000/teamchat/s1",
            "teamchat_kit": "/opt/teamchat",
        }
        assert guard.handle(hook_input).decision is Decision.DENY


def _tool_use(i: int) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {}}],
        },
    }


def _write(path: Path, entries: list[dict[str, Any]]) -> str:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return str(path)


class TestN5OnlyTheGuardsOwnLatestBlockEarnsThePass:
    """Review of PR 234: a goal continuation after the guard's refusal closes the chain."""

    def _entries(self, first_reason: str | None) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = [_assistant(AWAITING)]
        if first_reason is not None:
            entries += [_feedback(first_reason), _tool_use(0), _tool_result(), _assistant(AWAITING)]
        entries.append(_feedback("[ccy-supervisor] automated goal -- Work on Plan 00636"))
        for i in range(1, 20):
            entries += [_tool_use(i), _tool_result()]
        entries.append(_assistant(AWAITING))
        return entries

    def test_a_goal_continuation_after_the_refusal_does_not_pass_a_new_wait(
        self, tmp_path: Path
    ) -> None:
        chain = _chain(_Bus(_stale()))
        first = _run(chain, tmp_path, [_assistant(AWAITING)])
        assert first.decision is Decision.DENY
        result = _run(chain, tmp_path, self._entries(first.reason), active=True)
        assert result.decision is Decision.DENY
        assert "R-STOP-OWNER-WAIT-UNBUMPED" in result.reason

    def test_the_new_refusal_becomes_the_latest_block_so_the_next_restop_passes(
        self, tmp_path: Path
    ) -> None:
        chain = _chain(_Bus(_stale()))
        first = _run(chain, tmp_path, [_assistant(AWAITING)])
        entries = [*self._entries(first.reason), _feedback(first.reason), _assistant(AWAITING)]
        assert _run(chain, tmp_path, entries, active=True).decision is Decision.ALLOW

    def test_a_queued_prompt_attachment_closes_the_chain(self, tmp_path: Path) -> None:
        queued = {
            "type": "attachment",
            "attachment": {"type": "queued_command", "commandMode": "prompt", "prompt": "hi"},
        }
        path = _write(tmp_path / "t.jsonl", [_feedback(OWN_BLOCK), queued, _assistant("x")])
        assert recent_stop_hook_block_texts_this_chain(path, lookback=200) == ()

    def test_a_queued_non_prompt_attachment_does_not_close_the_chain(self, tmp_path: Path) -> None:
        queued = {
            "type": "attachment",
            "attachment": {"type": "queued_command", "commandMode": "bash", "prompt": "ls"},
        }
        path = _write(tmp_path / "t.jsonl", [_feedback(OWN_BLOCK), queued])
        assert len(recent_stop_hook_block_texts_this_chain(path, lookback=200)) == 1

    def test_an_attachment_only_own_refusal_before_a_prompt_is_dropped(self, tmp_path: Path) -> None:
        attachment = {
            "type": "attachment",
            "attachment": {
                "type": "hook_blocking_error",
                "hookEvent": "Stop",
                "blockingError": {"blockingError": OWN_BLOCK},
            },
        }
        path = _write(tmp_path / "t.jsonl", [attachment, _prompt(), _assistant("x")])
        assert recent_stop_hook_block_texts_this_chain(path, lookback=200) == ()

    def test_a_compaction_summary_is_not_a_prompt(self, tmp_path: Path) -> None:
        summary = {
            "type": "user",
            "isCompactSummary": True,
            "message": {"role": "user", "content": "This session is being continued"},
        }
        path = _write(tmp_path / "t.jsonl", [_feedback(OWN_BLOCK), summary, _assistant("x")])
        assert len(recent_stop_hook_block_texts_this_chain(path, lookback=200)) == 1


class TestN6AllowPolicyOnAnUnreadableStopMessage:
    def test_allow_policy_allows_with_no_context(self, tmp_path: Path) -> None:
        guard = _Guard(_Bus(BusUnreadable("x")), ENABLED)
        guard._on_unreadable_bus = "allow"
        hook_input: dict[str, Any] = {
            "hook_event_name": "Stop",
            "session_id": "lead",
            "transcript_path": str(tmp_path / "missing.jsonl"),
            "stop_hook_active": False,
            "teamchat_runtime": "/run/user/1000/teamchat/s1",
            "teamchat_kit": "/opt/teamchat",
        }
        result = guard.handle(hook_input)
        assert result.decision is Decision.ALLOW
        assert result.context == []
