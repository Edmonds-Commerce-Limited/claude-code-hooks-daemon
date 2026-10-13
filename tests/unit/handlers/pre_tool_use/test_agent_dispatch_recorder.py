"""Tests for AgentDispatchRecorderHandler: it records name -> subagent_type, never decides."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.agent_dispatch_recorder import (
    AgentDispatchRecorderHandler,
)
from claude_code_hooks_daemon.utils.agent_dispatch_registry import effective_agent_type


def _dispatch(tool_name: str = "Agent", **tool_input: Any) -> dict[str, Any]:
    return {"tool_name": tool_name, "session_id": "s1", "tool_input": tool_input}


@pytest.fixture
def handler(tmp_path: Path) -> Any:
    instance = AgentDispatchRecorderHandler()
    with patch.object(AgentDispatchRecorderHandler, "_untracked_dir", return_value=tmp_path):
        yield instance


class TestMatches:
    def test_named_agent_dispatch_matches(self, handler: AgentDispatchRecorderHandler) -> None:
        assert handler.matches(_dispatch(name="w", subagent_type="qa-runner")) is True

    def test_task_tool_matches(self, handler: AgentDispatchRecorderHandler) -> None:
        assert handler.matches(_dispatch("Task", name="w", subagent_type="qa-runner")) is True

    def test_unnamed_dispatch_does_not_match(self, handler: AgentDispatchRecorderHandler) -> None:
        assert handler.matches(_dispatch(subagent_type="qa-runner")) is False

    def test_other_tool_does_not_match(self, handler: AgentDispatchRecorderHandler) -> None:
        assert handler.matches(_dispatch("Bash", name="w")) is False

    def test_non_string_name_does_not_match(self, handler: AgentDispatchRecorderHandler) -> None:
        assert handler.matches(_dispatch(name=5)) is False

    def test_missing_session_does_not_match(self, handler: AgentDispatchRecorderHandler) -> None:
        payload = _dispatch(name="w")
        del payload["session_id"]
        assert handler.matches(payload) is False


class TestHandle:
    def test_records_and_allows(
        self, handler: AgentDispatchRecorderHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(_dispatch(name="w", subagent_type="qa-runner"))
        assert result.decision == Decision.ALLOW
        assert effective_agent_type(tmp_path, "s1", "w") == "qa-runner"

    def test_dispatch_without_type_records_empty(
        self, handler: AgentDispatchRecorderHandler, tmp_path: Path
    ) -> None:
        handler.handle(_dispatch(name="w"))
        assert effective_agent_type(tmp_path, "s1", "w") == ""

    def test_unwritable_registry_still_allows(
        self, handler: AgentDispatchRecorderHandler, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "agent-dispatch-registry"
        blocker.write_text("a file where the directory should be", encoding="utf-8")
        result = handler.handle(_dispatch(name="w", subagent_type="qa-runner"))
        assert result.decision == Decision.ALLOW


class TestMetadata:
    def test_is_non_terminal(self) -> None:
        assert AgentDispatchRecorderHandler().terminal is False

    def test_has_guidance_and_acceptance_tests(self) -> None:
        instance = AgentDispatchRecorderHandler()
        assert instance.get_claude_md() is None or isinstance(instance.get_claude_md(), str)
        assert isinstance(instance.get_acceptance_tests(), list)
