"""Tests for AgentDispatchRecorderHandler: it records name -> subagent_type, never decides."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.agent_dispatch_recorder import (
    AgentDispatchRecorderHandler,
)
from claude_code_hooks_daemon.utils.agent_dispatch_registry import (
    dispatch_budget,
    effective_agent_type,
)
from claude_code_hooks_daemon.utils.spend_ledger import read_dispatch_rows, read_events


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

    def test_unnamed_dispatch_matches_for_its_tier_row(
        self, handler: AgentDispatchRecorderHandler
    ) -> None:
        """Plan 00472 Task 3.3: every dispatch gets a ledger row, named or not."""
        assert handler.matches(_dispatch(subagent_type="qa-runner")) is True

    def test_other_tool_does_not_match(self, handler: AgentDispatchRecorderHandler) -> None:
        assert handler.matches(_dispatch("Bash", name="w")) is False

    def test_non_dict_tool_input_does_not_match(
        self, handler: AgentDispatchRecorderHandler
    ) -> None:
        payload = _dispatch()
        payload["tool_input"] = "x"
        assert handler.matches(payload) is False

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

    def test_non_string_name_writes_no_registry_record(
        self, handler: AgentDispatchRecorderHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(_dispatch(name=5, subagent_type="qa-runner"))
        assert result.decision == Decision.ALLOW
        assert not (tmp_path / "agent-dispatch-registry").exists()

    def test_unwritable_registry_still_allows(
        self, handler: AgentDispatchRecorderHandler, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "agent-dispatch-registry"
        blocker.write_text("a file where the directory should be", encoding="utf-8")
        result = handler.handle(_dispatch(name="w", subagent_type="qa-runner"))
        assert result.decision == Decision.ALLOW


class TestBudgetOverride:
    """Plan 00471 Q4: a ``budget: <N>k`` line in a named dispatch's prompt."""

    def test_budget_line_is_recorded_and_ledgered(
        self, handler: AgentDispatchRecorderHandler, tmp_path: Path
    ) -> None:
        prompt = "Do the migration.\nbudget: 400k\nReport to the plan folder."
        handler.handle(_dispatch(name="w", subagent_type="python-developer", prompt=prompt))
        assert dispatch_budget(tmp_path, "s1", "w") == 400_000
        events = read_events(tmp_path, "s1")
        assert events[-1]["kind"] == "budget-override"
        assert events[-1]["name"] == "w"
        assert events[-1]["requested_tokens"] == 400_000

    def test_no_line_records_no_budget_and_no_event(
        self, handler: AgentDispatchRecorderHandler, tmp_path: Path
    ) -> None:
        handler.handle(_dispatch(name="w", subagent_type="qa-runner", prompt="budget is tight"))
        assert dispatch_budget(tmp_path, "s1", "w") is None
        assert read_events(tmp_path, "s1") == []

    def test_a_later_dispatch_of_the_name_replaces_the_budget(
        self, handler: AgentDispatchRecorderHandler, tmp_path: Path
    ) -> None:
        handler.handle(_dispatch(name="w", prompt="budget: 400k"))
        handler.handle(_dispatch(name="w", prompt="no override"))
        assert dispatch_budget(tmp_path, "s1", "w") is None


def _main_transcript(tmp_path: Path, model: str) -> Path:
    transcript = tmp_path / "s1.jsonl"
    transcript.write_text(
        json.dumps({"type": "assistant", "message": {"model": model, "usage": {"input_tokens": 1}}})
        + "\n"
    )
    return transcript


def _tier_dispatch(tmp_path: Path, tool_use_id: str = "toolu_1", **tool_input: Any) -> dict:
    payload = _dispatch(**tool_input)
    payload["tool_use_id"] = tool_use_id
    payload["transcript_path"] = str(_main_transcript(tmp_path, "claude-opus-5-5"))
    return payload


class TestTierRow:
    """Plan 00472 Task 3.3: the classifier's output, one ledger row per dispatch."""

    @pytest.fixture
    def recorder(self, tmp_path: Path) -> Any:
        instance = AgentDispatchRecorderHandler()
        with (
            patch.object(AgentDispatchRecorderHandler, "_untracked_dir", return_value=tmp_path),
            patch.object(AgentDispatchRecorderHandler, "_project_root", return_value=tmp_path),
        ):
            yield instance

    def _row(self, tmp_path: Path) -> dict[str, Any]:
        (row,) = read_dispatch_rows(tmp_path, "s1")
        return row

    def test_inherited_row(self, recorder: AgentDispatchRecorderHandler, tmp_path: Path) -> None:
        recorder.handle(
            _tier_dispatch(
                tmp_path, name="impl-1", subagent_type="general-purpose", description="Implement"
            )
        )
        row = self._row(tmp_path)
        assert row["tool_use_id"] == "toolu_1"
        assert row["subagent_type"] == "general-purpose"
        assert row["name"] == "impl-1"
        assert row["model_param"] == ""
        assert row["definition_model"] == ""
        assert row["source"] == "inherited"
        assert row["predicted_family"] == "opus"
        assert row["spawner_model"] == "claude-opus-5-5"
        assert row["spawner"] == "main"
        assert row["role"] == "implement"
        assert row["tier_reason"] == ""
        assert row["pre_recorded"] is True

    def test_explicit_row(self, recorder: AgentDispatchRecorderHandler, tmp_path: Path) -> None:
        recorder.handle(_tier_dispatch(tmp_path, subagent_type="general-purpose", model="sonnet"))
        row = self._row(tmp_path)
        assert (row["source"], row["model_param"], row["predicted_family"]) == (
            "explicit",
            "sonnet",
            "sonnet",
        )

    def test_definition_row(self, recorder: AgentDispatchRecorderHandler, tmp_path: Path) -> None:
        agents = tmp_path / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "python-developer.md").write_text(
            "---\nname: python-developer\nmodel: sonnet\n---\nbody\n"
        )
        recorder.handle(_tier_dispatch(tmp_path, subagent_type="python-developer"))
        row = self._row(tmp_path)
        assert (row["source"], row["definition_model"], row["predicted_family"]) == (
            "definition",
            "sonnet",
            "sonnet",
        )

    def test_fork_row(self, recorder: AgentDispatchRecorderHandler, tmp_path: Path) -> None:
        recorder.handle(_tier_dispatch(tmp_path, subagent_type="fork"))
        assert self._row(tmp_path)["source"] == "fork"

    def test_explore_capped_row(
        self, recorder: AgentDispatchRecorderHandler, tmp_path: Path
    ) -> None:
        payload = _tier_dispatch(tmp_path, subagent_type="Explore")
        payload["transcript_path"] = str(_main_transcript(tmp_path, "claude-fable-5-1"))
        recorder.handle(payload)
        row = self._row(tmp_path)
        assert (row["source"], row["predicted_family"]) == ("inherited-capped", "opus")

    def test_tier_token_reason_is_recorded(
        self, recorder: AgentDispatchRecorderHandler, tmp_path: Path
    ) -> None:
        recorder.handle(
            _tier_dispatch(tmp_path, subagent_type="general-purpose", prompt="x\ntier: hard line\n")
        )
        assert self._row(tmp_path)["tier_reason"] == "hard line"

    def test_no_tool_use_id_writes_no_row(
        self, recorder: AgentDispatchRecorderHandler, tmp_path: Path
    ) -> None:
        payload = _tier_dispatch(tmp_path, subagent_type="general-purpose")
        del payload["tool_use_id"]
        assert recorder.handle(payload).decision == Decision.ALLOW
        assert read_dispatch_rows(tmp_path, "s1") == []

    def test_classifier_failure_still_allows(
        self, recorder: AgentDispatchRecorderHandler, tmp_path: Path
    ) -> None:
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.agent_dispatch_recorder.dispatch_facts",
            side_effect=OSError("unreadable agents dir"),
        ):
            result = recorder.handle(_tier_dispatch(tmp_path, subagent_type="general-purpose"))
        assert result.decision == Decision.ALLOW
        assert read_dispatch_rows(tmp_path, "s1") == []


class TestMetadata:
    def test_is_non_terminal(self) -> None:
        assert AgentDispatchRecorderHandler().terminal is False

    def test_has_guidance_and_acceptance_tests(self) -> None:
        instance = AgentDispatchRecorderHandler()
        assert instance.get_claude_md() is None or isinstance(instance.get_claude_md(), str)
        assert isinstance(instance.get_acceptance_tests(), list)
