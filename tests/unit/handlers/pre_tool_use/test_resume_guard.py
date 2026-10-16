"""Tests for ResumeGuardHandler (Plan 00471 Task 2.3, lever L3)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.resume_guard import ResumeGuardHandler
from claude_code_hooks_daemon.utils.spend_ledger import read_events

SESSION = "s1"
OLD_ID = "aplan464-impl-1111111111111111"
NEW_ID = "aplan464-impl-2222222222222222"


def write_agent(
    subagents: Path,
    agent_id: str,
    name: str,
    *,
    context: int,
    stopped: bool = True,
    age_seconds: float = 3600,
) -> Path:
    subagents.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "assistant",
        "message": {
            "model": "claude-opus-5-5",
            "stop_reason": "end_turn" if stopped else "tool_use",
            "usage": {"cache_read_input_tokens": context},
        },
    }
    transcript = subagents / f"agent-{agent_id}.jsonl"
    transcript.write_text(json.dumps(record) + "\n", encoding="utf-8")
    (subagents / f"agent-{agent_id}.meta.json").write_text(json.dumps({"name": name}))
    stamp = time.time() - age_seconds
    os.utime(transcript, (stamp, stamp))
    return transcript


@pytest.fixture
def subagents(tmp_path: Path) -> Path:
    return tmp_path / "projects" / SESSION / "subagents"


@pytest.fixture
def handler(tmp_path: Path) -> ResumeGuardHandler:
    instance = ResumeGuardHandler()
    instance._untracked_override = tmp_path / "untracked"
    instance._project_root = tmp_path / "repo"
    instance._max_resume_tokens = 150_000
    instance._mode = "deny"
    return instance


def send(tmp_path: Path, to: str, message: Any = "NEW TASK: more work") -> dict[str, Any]:
    return {
        "session_id": SESSION,
        "transcript_path": str(tmp_path / "projects" / f"{SESSION}.jsonl"),
        "cwd": str(tmp_path / "repo"),
        "tool_name": "SendMessage",
        "tool_input": {"to": to, "message": message, "summary": "x"},
    }


class TestMatches:
    def test_only_send_message(self, handler, tmp_path) -> None:
        assert handler.matches(send(tmp_path, "x")) is True
        other = send(tmp_path, "x")
        other["tool_name"] = "Bash"
        assert handler.matches(other) is False

    def test_shipped_defaults_advise_at_250k(self) -> None:
        instance = ResumeGuardHandler()
        assert instance._max_resume_tokens == 250_000
        assert instance._mode == "advise"
        assert instance._warm_seconds == 300

    def test_validate_options(self) -> None:
        problems = ResumeGuardHandler.validate_options(
            {"max_resume_tokens": 0, "warm_seconds": "x", "mode": "block"}
        )
        assert set(problems) == {"max_resume_tokens", "warm_seconds", "mode"}


class TestDecision:
    def test_stopped_cold_large_is_denied_naming_the_route(
        self, handler, tmp_path, subagents
    ) -> None:
        write_agent(subagents, NEW_ID, "plan464-impl", context=300_000)
        reports = tmp_path / "repo" / "untracked" / "agent-reports" / "auto"
        reports.mkdir(parents=True)
        report = reports / f"261015-120000-plan464-impl-{NEW_ID}.md"
        report.write_text("report", encoding="utf-8")
        result = handler.handle(send(tmp_path, "plan464-impl"))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.RESUME_COLD_LARGE}]")
        assert "300,000" in result.reason
        assert str(report) in result.reason
        assert "RESUME-LARGE:" in result.reason
        assert "fresh" in result.reason

    def test_newest_generation_of_a_name_is_judged(self, handler, tmp_path, subagents) -> None:
        write_agent(subagents, OLD_ID, "plan464-impl", context=300_000, age_seconds=7200)
        write_agent(subagents, NEW_ID, "plan464-impl", context=20_000, age_seconds=3600)
        assert handler.handle(send(tmp_path, "plan464-impl")).decision == Decision.ALLOW

    def test_meta_must_confirm_the_name(self, handler, tmp_path, subagents) -> None:
        write_agent(subagents, NEW_ID, "someone-else", context=300_000)
        assert handler.handle(send(tmp_path, "plan464-impl")).decision == Decision.ALLOW

    def test_raw_agent_id_resolves(self, handler, tmp_path, subagents) -> None:
        write_agent(subagents, "a0123456789abcdef", "", context=300_000)
        assert handler.handle(send(tmp_path, "a0123456789abcdef")).decision == Decision.DENY

    def test_warm_is_allowed(self, handler, tmp_path, subagents) -> None:
        write_agent(subagents, NEW_ID, "plan464-impl", context=300_000, age_seconds=60)
        assert handler.handle(send(tmp_path, "plan464-impl")).decision == Decision.ALLOW

    def test_running_is_never_gated(self, handler, tmp_path, subagents) -> None:
        write_agent(subagents, NEW_ID, "plan464-impl", context=300_000, stopped=False)
        assert handler.handle(send(tmp_path, "plan464-impl")).decision == Decision.ALLOW

    def test_small_is_allowed(self, handler, tmp_path, subagents) -> None:
        write_agent(subagents, NEW_ID, "plan464-impl", context=100_000)
        assert handler.handle(send(tmp_path, "plan464-impl")).decision == Decision.ALLOW

    def test_unresolvable_target_fails_open(self, handler, tmp_path) -> None:
        assert handler.handle(send(tmp_path, "peer-in-another-session")).decision == Decision.ALLOW

    def test_override_prefix_allows_and_is_recorded(self, handler, tmp_path, subagents) -> None:
        write_agent(subagents, NEW_ID, "plan464-impl", context=300_000)
        message = "RESUME-LARGE: one-line fix it already has the context for\nfix the typo"
        assert handler.handle(send(tmp_path, "plan464-impl", message)).decision == Decision.ALLOW
        events = read_events(tmp_path / "untracked", SESSION)
        assert events[-1]["kind"] == "resume-override"
        assert events[-1]["to"] == "plan464-impl"
        assert events[-1]["reason"] == "one-line fix it already has the context for"

    def test_non_string_message_is_judged_without_an_override(
        self, handler, tmp_path, subagents
    ) -> None:
        write_agent(subagents, NEW_ID, "plan464-impl", context=300_000)
        message = {"type": "shutdown_request"}
        assert handler.handle(send(tmp_path, "plan464-impl", message)).decision == Decision.DENY

    def test_advise_mode_allows_with_context(self, handler, tmp_path, subagents) -> None:
        handler._mode = "advise"
        write_agent(subagents, NEW_ID, "plan464-impl", context=300_000)
        result = handler.handle(send(tmp_path, "plan464-impl"))
        assert result.decision == Decision.ALLOW
        assert "300,000" in "\n".join(result.context)

    def test_handoff_file_from_the_budget_state_is_named(
        self, handler, tmp_path, subagents
    ) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_context_budget import (
            STATE_HANDOFF_WRITTEN,
            STATE_KIND,
        )
        from claude_code_hooks_daemon.utils.spend_ledger import state_path, write_state

        write_agent(subagents, NEW_ID, "plan464-impl", context=300_000)
        handoff = tmp_path / "repo" / "h-handoff.md"
        handoff.parent.mkdir(parents=True)
        handoff.write_text("x", encoding="utf-8")
        write_state(
            state_path(tmp_path / "untracked", SESSION, STATE_KIND, NEW_ID),
            {STATE_HANDOFF_WRITTEN: str(handoff)},
        )
        reason = handler.handle(send(tmp_path, "plan464-impl")).reason or ""
        assert str(handoff) in reason


class TestDocs:
    def test_rules_guidance_and_acceptance(self) -> None:
        instance = ResumeGuardHandler()
        assert [rule.rule_id for rule in instance.get_rules()] == [RuleID.RESUME_COLD_LARGE]
        assert "RESUME-LARGE:" in (instance.get_claude_md() or "")
        assert instance.get_acceptance_tests()
