"""Tests for DispatchModelRecorderHandler: the PostToolUse half of the tier row (Plan 00472 Task 3.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.dispatch_model_recorder import (
    DispatchModelRecorderHandler,
)
from claude_code_hooks_daemon.utils.spend_ledger import read_dispatch_rows, write_dispatch_row


def _post(response: Any, tool_name: str = "Agent", tool_use_id: str = "toolu_1") -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "session_id": "s1",
        "tool_use_id": tool_use_id,
        "tool_input": {"subagent_type": "general-purpose"},
        "tool_response": response,
    }


@pytest.fixture
def handler(tmp_path: Path) -> Any:
    instance = DispatchModelRecorderHandler()
    with patch.object(DispatchModelRecorderHandler, "_untracked_dir", return_value=tmp_path):
        yield instance


class TestMatches:
    def test_agent_and_task_match(self, handler: DispatchModelRecorderHandler) -> None:
        assert handler.matches(_post({"resolvedModel": "x"})) is True
        assert handler.matches(_post({"resolvedModel": "x"}, tool_name="Task")) is True

    def test_other_tool_does_not_match(self, handler: DispatchModelRecorderHandler) -> None:
        assert handler.matches(_post({}, tool_name="Bash")) is False

    def test_no_tool_use_id_does_not_match(self, handler: DispatchModelRecorderHandler) -> None:
        assert handler.matches(_post({}, tool_use_id="")) is False


class TestJoin:
    def test_completed_response_joins_the_pre_row(
        self, handler: DispatchModelRecorderHandler, tmp_path: Path
    ) -> None:
        write_dispatch_row(tmp_path, "s1", "toolu_1", {"source": "inherited"})
        result = handler.handle(
            _post(
                {
                    "status": "completed",
                    "agentId": "a0123456789abcdef",
                    "resolvedModel": "claude-opus-5-5",
                    "modelsUsed": ["claude-opus-5-5", "claude-opus-4-8"],
                }
            )
        )
        assert result.decision == Decision.ALLOW
        (row,) = read_dispatch_rows(tmp_path, "s1")
        assert row["source"] == "inherited"
        assert row["resolved_model"] == "claude-opus-5-5"
        assert row["models_used"] == ["claude-opus-5-5", "claude-opus-4-8"]
        assert row["agent_id"] == "a0123456789abcdef"
        assert row["status"] == "completed"
        assert row["pre_recorded"] is True

    def test_async_launched_response_joins(
        self, handler: DispatchModelRecorderHandler, tmp_path: Path
    ) -> None:
        write_dispatch_row(tmp_path, "s1", "toolu_1", {"source": "explicit"})
        handler.handle(_post({"status": "async_launched", "resolvedModel": "claude-sonnet-5-5"}))
        (row,) = read_dispatch_rows(tmp_path, "s1")
        assert row["resolved_model"] == "claude-sonnet-5-5"
        assert row["models_used"] == []

    def test_a_fixture_session_has_no_unjoined_rows(
        self, handler: DispatchModelRecorderHandler, tmp_path: Path
    ) -> None:
        for index in range(5):
            write_dispatch_row(tmp_path, "s1", f"toolu_{index}", {"source": "inherited"})
            handler.handle(_post({"resolvedModel": "claude-opus-5-5"}, tool_use_id=f"toolu_{index}"))
        rows = read_dispatch_rows(tmp_path, "s1")
        assert len(rows) == 5
        assert all(row["pre_recorded"] and row["resolved_model"] for row in rows)

    def test_non_dict_response_still_allows(
        self, handler: DispatchModelRecorderHandler, tmp_path: Path
    ) -> None:
        write_dispatch_row(tmp_path, "s1", "toolu_1", {"source": "inherited"})
        assert handler.handle(_post("text")).decision == Decision.ALLOW
        (row,) = read_dispatch_rows(tmp_path, "s1")
        assert row["resolved_model"] == ""

    def test_no_project_context_still_allows(self) -> None:
        with patch.object(
            DispatchModelRecorderHandler, "_untracked_dir", side_effect=RuntimeError("no ctx")
        ):
            result = DispatchModelRecorderHandler().handle(_post({"resolvedModel": "x"}))
        assert result.decision == Decision.ALLOW


class TestMetadata:
    def test_is_a_silent_non_terminal_sensor(self) -> None:
        instance = DispatchModelRecorderHandler()
        assert instance.terminal is False
        assert instance.get_claude_md() is None
        assert len(instance.get_acceptance_tests()) == 1
