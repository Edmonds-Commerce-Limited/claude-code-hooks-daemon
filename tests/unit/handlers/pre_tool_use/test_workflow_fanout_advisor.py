"""Tests for WorkflowFanoutAdvisorHandler (Plan 00472 Task 3.6, rulings 2(a), 2(c), 3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.daemon.verdict_log import VERDICT_LOG_FILENAME
from claude_code_hooks_daemon.handlers.pre_tool_use.workflow_fanout_advisor import (
    DEFAULT_CEILINGS,
    WorkflowFanoutAdvisorHandler,
)

FANOUT_60 = "await pipeline(args, async (f) => agent(`Fix ${f}`));"
EXPLICIT_SMALL = "await parallel(['a','b'].map(x => () => agent(x, { model: 'sonnet' })));"
COMPUTED = "const xs = await agent('list', { model: 'haiku' });\nawait pipeline(xs, (x) => agent(x, { model: 'sonnet' }));"


@pytest.fixture
def handler(tmp_path: Path) -> WorkflowFanoutAdvisorHandler:
    instance = WorkflowFanoutAdvisorHandler()
    instance._untracked_override = tmp_path
    return instance


def call(tmp_path: Path, tool_input: Any, main_model: str = "claude-fable-5-1") -> dict:
    transcript = tmp_path / "s1.jsonl"
    record = {"type": "assistant", "message": {"model": main_model, "usage": {"x": 1}}}
    transcript.write_text(json.dumps(record) + "\n" if main_model else "")
    return {
        "tool_name": "Workflow",
        "session_id": "s1",
        "transcript_path": str(transcript),
        "tool_input": tool_input,
    }


def verdicts(tmp_path: Path) -> list[dict]:
    path = tmp_path / "logs" / "hooks" / VERDICT_LOG_FILENAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def shape_file(tmp_path: Path) -> Path:
    return tmp_path / "payload-capture" / "workflow-shape.json"


class TestAdvice:
    def test_args_driven_fanout_is_resolved_exactly_and_over_the_ceiling(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path
    ) -> None:
        tool_input = {"script": FANOUT_60, "args": [f"f{i}" for i in range(60)]}
        result = handler.handle(call(tmp_path, tool_input))
        assert result.decision == Decision.ALLOW
        (message,) = result.context
        assert "starts 60 agents" in message
        assert "at least" not in message
        assert "1 of 1 agent() sites" in message
        assert "fable" in message
        assert "over the fable fan-out ceiling of 10" in message

    def test_args_as_a_json_string_resolves_too(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path
    ) -> None:
        tool_input = {"script": FANOUT_60, "args": json.dumps(["a", "b"])}
        (message,) = handler.handle(call(tmp_path, tool_input)).context
        assert "starts 2 agents" in message

    def test_unknown_fanout_says_at_least_and_counts_as_at_the_ceiling(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path
    ) -> None:
        (message,) = handler.handle(call(tmp_path, {"script": COMPUTED})).context
        assert "at least 2 agents" in message
        assert "counted as at the fable ceiling of 10" in message

    def test_explicit_models_within_the_ceiling_are_silent(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(call(tmp_path, {"script": EXPLICIT_SMALL}))
        assert result.context == []
        assert verdicts(tmp_path)[-1]["verdict"] == "within-ceiling"

    def test_unknown_session_model_is_silent(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path
    ) -> None:
        tool_input = {"script": FANOUT_60, "args": ["a"] * 60}
        assert handler.handle(call(tmp_path, tool_input, main_model="")).context == []

    def test_script_path_is_read_when_absolute_and_present(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path
    ) -> None:
        script = tmp_path / "wf.js"
        script.write_text(FANOUT_60)
        tool_input = {"scriptPath": str(script), "args": ["a"] * 30}
        (message,) = handler.handle(call(tmp_path, tool_input)).context
        assert "starts 30 agents" in message

    def test_sonnet_session_has_the_sonnet_ceiling(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path
    ) -> None:
        tool_input = {"script": FANOUT_60, "args": ["a"] * 30}
        (message,) = handler.handle(call(tmp_path, tool_input, "claude-sonnet-5-5")).context
        assert "over" not in message
        assert "inherit the session's sonnet" in message


class TestUnparsed:
    @pytest.mark.parametrize(
        "tool_input",
        [
            "a bare string",
            {"name": "saved-workflow"},
            {"scriptPath": "relative/path.js"},
            {"scriptPath": "/does/not/exist.js"},
            {"script": 42},
        ],
    )
    def test_allows_with_one_unparsed_verdict(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path, tool_input: Any
    ) -> None:
        result = handler.handle(call(tmp_path, tool_input))
        assert result.decision == Decision.ALLOW
        assert result.context == []
        (verdict,) = [line for line in verdicts(tmp_path) if line["verdict"] == "unparsed"]
        assert verdict["handler"] == "workflow-fanout-advisor"


class TestShapeProbe:
    def test_writes_key_names_and_types_never_values(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path
    ) -> None:
        tool_input = {"script": "agent('SECRET-SCRIPT-TEXT')", "args": ["x"], "name": "n"}
        handler.handle(call(tmp_path, tool_input))
        text = shape_file(tmp_path).read_text()
        assert "SECRET-SCRIPT-TEXT" not in text
        shape = json.loads(text)
        assert shape["session_id"] == "s1"
        assert shape["tool_input_type"] == "object"
        assert shape["keys"] == {"args": "array", "name": "string", "script": "string"}

    def test_written_once_per_session(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path
    ) -> None:
        handler.handle(call(tmp_path, {"script": "agent('x')"}))
        first = shape_file(tmp_path).read_text()
        handler.handle(call(tmp_path, {"script": "agent('x')", "extra": 1}))
        assert shape_file(tmp_path).read_text() == first

    def test_records_a_non_object_shape(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path
    ) -> None:
        handler.handle(call(tmp_path, ["not", "an", "object"]))
        shape = json.loads(shape_file(tmp_path).read_text())
        assert (shape["tool_input_type"], shape["keys"]) == ("array", {})


class TestNeverDenies:
    @pytest.mark.parametrize(
        "tool_input",
        [None, {}, {"script": ""}, {"script": FANOUT_60}, {"script": "agent(", "args": "{bad"}],
    )
    def test_allow(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path, tool_input: Any
    ) -> None:
        assert handler.handle(call(tmp_path, tool_input)).decision == Decision.ALLOW


class TestOptions:
    def test_default_ceilings_are_the_ruled_table(self) -> None:
        assert DEFAULT_CEILINGS == {"fable": 10, "opus": 25, "sonnet": 60, "haiku": 60}

    def test_validate(self) -> None:
        assert WorkflowFanoutAdvisorHandler.validate_options({"ceilings": {"opus": 5}}) == {}
        assert "ceilings" in WorkflowFanoutAdvisorHandler.validate_options({"ceilings": {"gpt": 5}})
        assert "ceilings" in WorkflowFanoutAdvisorHandler.validate_options(
            {"ceilings": {"opus": 0}}
        )

    def test_configured_ceiling_is_used(
        self, handler: WorkflowFanoutAdvisorHandler, tmp_path: Path
    ) -> None:
        handler._ceilings = {"fable": 100}
        tool_input = {"script": FANOUT_60, "args": ["a"] * 60}
        (message,) = handler.handle(call(tmp_path, tool_input)).context
        assert "over" not in message


class TestMetadata:
    def test_matches_only_workflow(self, handler: WorkflowFanoutAdvisorHandler) -> None:
        assert handler.matches({"tool_name": "Workflow"})
        assert not handler.matches({"tool_name": "Agent"})

    def test_non_terminal_advisory(self) -> None:
        handler = WorkflowFanoutAdvisorHandler()
        assert handler.terminal is False
        assert handler.get_claude_md() is None
        assert len(handler.get_acceptance_tests()) == 1
