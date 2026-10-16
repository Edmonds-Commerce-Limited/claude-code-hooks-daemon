"""Tests for SubagentHandoffGateHandler (Plan 00471 Task 2.2, the L2 SubagentStop companion)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_context_budget import (
    SubagentContextBudgetHandler,
)
from claude_code_hooks_daemon.handlers.subagent_stop.subagent_handoff_gate import (
    SubagentHandoffGateHandler,
)

AGENT_ID = "ap471-impl-0123456789abcdef"
SESSION = "s1"


def write_transcript(path: Path, context: int) -> None:
    record = {
        "type": "assistant",
        "message": {"model": "m", "usage": {"cache_read_input_tokens": context}},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "CLAUDE" / "Plan" / "00471-x").mkdir(parents=True)
    return root


def pre_tool(
    tmp_path: Path, project: Path, tool: str, tool_input: dict[str, Any]
) -> dict[str, Any]:
    return {
        "session_id": SESSION,
        "transcript_path": str(tmp_path / "projects" / f"{SESSION}.jsonl"),
        "cwd": str(project),
        "agent_id": AGENT_ID,
        "agent_type": "p471-impl",
        "tool_name": tool,
        "tool_input": tool_input,
    }


def stop(tmp_path: Path, project: Path) -> dict[str, Any]:
    return {
        "session_id": SESSION,
        "cwd": str(project),
        "agent_id": AGENT_ID,
        "agent_type": "p471-impl",
        "agent_transcript_path": str(
            tmp_path / "projects" / SESSION / "subagents" / f"agent-{AGENT_ID}.jsonl"
        ),
        "hook_event_name": "SubagentStop",
    }


@pytest.fixture
def budget(tmp_path: Path, project: Path) -> SubagentContextBudgetHandler:
    instance = SubagentContextBudgetHandler()
    instance._untracked_override = tmp_path / "untracked"
    instance._project_root = project
    instance._soft_tokens = 150_000
    instance._hard_tokens = 250_000
    return instance


@pytest.fixture
def gate(tmp_path: Path) -> SubagentHandoffGateHandler:
    instance = SubagentHandoffGateHandler()
    instance._untracked_override = tmp_path / "untracked"
    return instance


def test_shares_the_budget_options() -> None:
    assert SubagentHandoffGateHandler().shares_options_with == "subagent_context_budget"


def test_an_agent_never_over_hard_stops_freely(gate, tmp_path, project) -> None:
    assert gate.handle(stop(tmp_path, project)).decision == Decision.ALLOW


def test_over_hard_without_handoff_is_blocked_until_written(
    budget, gate, tmp_path, project
) -> None:
    transcript = tmp_path / "projects" / SESSION / "subagents" / f"agent-{AGENT_ID}.jsonl"
    write_transcript(transcript, 260_000)
    denied = budget.handle(pre_tool(tmp_path, project, "Bash", {"command": "ls"}))
    assert denied.decision == Decision.DENY

    blocked = gate.handle(stop(tmp_path, project))
    assert blocked.decision == Decision.DENY
    assert blocked.reason is not None
    assert blocked.reason.startswith(f"BLOCKED [{RuleID.SUBAGENT_HANDOFF_MISSING}]")
    assert "-p471-impl-handoff.md" in blocked.reason

    handoff = project / "CLAUDE" / "Plan" / "00471-x" / "subagent-reports" / "h-handoff.md"
    allowed = budget.handle(
        pre_tool(tmp_path, project, "Write", {"file_path": str(handoff), "content": "x"})
    )
    assert allowed.decision == Decision.ALLOW
    handoff.parent.mkdir(parents=True)
    handoff.write_text("state", encoding="utf-8")
    assert gate.handle(stop(tmp_path, project)).decision == Decision.ALLOW


def test_the_named_path_also_satisfies_it(budget, gate, tmp_path, project) -> None:
    transcript = tmp_path / "projects" / SESSION / "subagents" / f"agent-{AGENT_ID}.jsonl"
    write_transcript(transcript, 260_000)
    reason = budget.handle(pre_tool(tmp_path, project, "Bash", {"command": "ls"})).reason or ""
    named = next(word for word in reason.split() if word.endswith("-handoff.md"))
    Path(named).parent.mkdir(parents=True)
    Path(named).write_text("state", encoding="utf-8")
    assert gate.handle(stop(tmp_path, project)).decision == Decision.ALLOW


def test_never_locks_out_after_three_blocks(budget, gate, tmp_path, project) -> None:
    transcript = tmp_path / "projects" / SESSION / "subagents" / f"agent-{AGENT_ID}.jsonl"
    write_transcript(transcript, 260_000)
    budget.handle(pre_tool(tmp_path, project, "Bash", {"command": "ls"}))
    decisions = [gate.handle(stop(tmp_path, project)).decision for _ in range(4)]
    assert decisions == [Decision.DENY, Decision.DENY, Decision.DENY, Decision.ALLOW]


def test_matches_only_real_agent_stops(gate, tmp_path, project) -> None:
    assert gate.matches(stop(tmp_path, project)) is True
    assert gate.matches({"session_id": SESSION}) is False


def test_docs(gate) -> None:
    assert [rule.rule_id for rule in gate.get_rules()] == [RuleID.SUBAGENT_HANDOFF_MISSING]
    assert gate.get_acceptance_tests()
