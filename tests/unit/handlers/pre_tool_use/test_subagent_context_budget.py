"""Tests for SubagentContextBudgetHandler (Plan 00471 Task 2.2, lever L2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_context_budget import (
    SubagentContextBudgetHandler,
)
from claude_code_hooks_daemon.utils.agent_dispatch_registry import record_dispatch
from claude_code_hooks_daemon.utils.spend_ledger import unmeasured_count

AGENT_ID = "ap471-impl-0123456789abcdef"
AGENT_NAME = "p471-impl"
SESSION = "s1"


def write_transcript(path: Path, context: int) -> None:
    record = {
        "type": "assistant",
        "requestId": "r1",
        "message": {
            "model": "claude-opus-5-5",
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 0, "cache_read_input_tokens": context},
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "CLAUDE" / "Plan" / "00471-subagent-token-budget-protection").mkdir(parents=True)
    return root


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    return tmp_path / "projects" / SESSION / "subagents" / f"agent-{AGENT_ID}.jsonl"


@pytest.fixture
def handler(tmp_path: Path, project: Path) -> SubagentContextBudgetHandler:
    instance = SubagentContextBudgetHandler()
    instance._untracked_override = tmp_path / "untracked"
    instance._project_root = project
    instance._soft_tokens = 150_000
    return instance


def event(
    tmp_path: Path,
    project: Path,
    tool: str = "Bash",
    tool_input: dict[str, Any] | None = None,
    *,
    agent_id: str = AGENT_ID,
    agent_type: str = AGENT_NAME,
) -> dict[str, Any]:
    return {
        "session_id": SESSION,
        "transcript_path": str(tmp_path / "projects" / f"{SESSION}.jsonl"),
        "cwd": str(project),
        "agent_id": agent_id,
        "agent_type": agent_type,
        "tool_name": tool,
        "tool_input": tool_input if tool_input is not None else {"command": "ls"},
    }


class TestShape:
    def test_scope_is_sub(self) -> None:
        assert SubagentContextBudgetHandler().scope is HandlerScope.SUB

    def test_shipped_defaults(self) -> None:
        instance = SubagentContextBudgetHandler()
        assert instance._soft_tokens == 300_000
        assert instance._hard_tokens is None
        assert instance._max_override_tokens == 450_000

    def test_off_when_no_band_is_set(
        self, handler: SubagentContextBudgetHandler, tmp_path: Path, project: Path
    ) -> None:
        handler._soft_tokens = None
        assert handler.matches(event(tmp_path, project)) is False

    def test_empty_input_does_not_match(self, handler: SubagentContextBudgetHandler) -> None:
        assert handler.matches({}) is False

    def test_no_tool_name_does_not_match(
        self, handler: SubagentContextBudgetHandler, tmp_path: Path, project: Path
    ) -> None:
        payload = event(tmp_path, project)
        del payload["tool_name"]
        assert handler.matches(payload) is False

    def test_no_agent_id_does_not_match(
        self, handler: SubagentContextBudgetHandler, tmp_path: Path, project: Path
    ) -> None:
        """Only a subagent's call has a context budget; main's carries no agent_id."""
        assert handler.matches(event(tmp_path, project, agent_id="")) is False

    def test_a_subagent_tool_call_matches(
        self, handler: SubagentContextBudgetHandler, tmp_path: Path, project: Path
    ) -> None:
        assert handler.matches(event(tmp_path, project)) is True

    def test_exempt_agent_type(
        self, handler: SubagentContextBudgetHandler, tmp_path: Path, project: Path
    ) -> None:
        handler._exempt_agent_types = ["qa-runner"]
        unnamed = event(tmp_path, project, agent_id="a0123456789abcdef", agent_type="qa-runner")
        assert handler.matches(unnamed) is False
        assert handler.matches(event(tmp_path, project)) is True

    def test_validate_options(self) -> None:
        problems = SubagentContextBudgetHandler.validate_options(
            {"soft_tokens": "x", "hard_tokens": -1, "handoff_globs": "nope"}
        )
        assert set(problems) == {"soft_tokens", "hard_tokens", "handoff_globs"}
        assert (
            SubagentContextBudgetHandler.validate_options({"soft_tokens": 1, "hard_tokens": None})
            == {}
        )


class TestSoftBand:
    def test_below_soft_is_silent(self, handler, tmp_path, project, transcript) -> None:
        write_transcript(transcript, 100_000)
        result = handler.handle(event(tmp_path, project))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_advises_once_per_band(self, handler, tmp_path, project, transcript) -> None:
        write_transcript(transcript, 160_000)
        first = handler.handle(event(tmp_path, project))
        second = handler.handle(event(tmp_path, project))
        assert first.decision == Decision.ALLOW
        advice = "\n".join(first.context)
        assert "160,000" in advice
        assert "subagent-reports/" in advice and "-p471-impl-handoff.md" in advice
        assert "00471-subagent-token-budget-protection" in advice
        assert "SendMessage" in advice
        assert not second.context

    def test_once_per_band_survives_a_new_instance(
        self, handler, tmp_path, project, transcript
    ) -> None:
        write_transcript(transcript, 160_000)
        handler.handle(event(tmp_path, project))
        fresh = SubagentContextBudgetHandler()
        fresh._untracked_override = handler._untracked_override
        fresh._project_root = project
        fresh._soft_tokens = 150_000
        assert not fresh.handle(event(tmp_path, project)).context

    def test_no_plan_folder_falls_back_to_scratch(
        self, handler, tmp_path, project, transcript
    ) -> None:
        write_transcript(transcript, 160_000)
        hook_input = event(tmp_path, project, agent_id="ax-0123456789abcdef", agent_type="helper")
        write_transcript(transcript.with_name("agent-ax-0123456789abcdef.jsonl"), 160_000)
        advice = "\n".join(handler.handle(hook_input).context)
        assert "untracked/scratch/" in advice

    def test_small_fresh_agent_with_no_usage_is_silent_and_not_unmeasured(
        self, handler, tmp_path, project, transcript
    ) -> None:
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps({"type": "user", "message": {"content": "go"}}) + "\n")
        assert handler.handle(event(tmp_path, project)).decision == Decision.ALLOW
        assert unmeasured_count(tmp_path / "untracked", SESSION) == 0

    def test_large_transcript_with_no_usage_fails_open_and_is_recorded_unmeasured(
        self, handler, tmp_path, project, transcript
    ) -> None:
        """Review B2: a renamed `usage` field must not switch the gate off silently."""
        transcript.parent.mkdir(parents=True)
        line = json.dumps({"type": "user", "message": {"content": "x" * 1000}}) + "\n"
        transcript.write_text(line * 1000, encoding="utf-8")
        for _ in range(3):
            assert handler.handle(event(tmp_path, project)).decision == Decision.ALLOW
        assert unmeasured_count(tmp_path / "untracked", SESSION) == 1
        log = tmp_path / "untracked" / "logs" / "hooks" / "verdicts.jsonl"
        assert json.loads(log.read_text())["detail"]["reason"] == "no-usage-in-tail"


class TestUnmeasured:
    def test_missing_transcript_allows_with_one_record(self, handler, tmp_path, project) -> None:
        for _ in range(4):
            assert handler.handle(event(tmp_path, project)).decision == Decision.ALLOW
        assert unmeasured_count(tmp_path / "untracked", SESSION) == 1
        log = tmp_path / "untracked" / "logs" / "hooks" / "verdicts.jsonl"
        lines = [json.loads(line) for line in log.read_text().splitlines()]
        assert [line["verdict"] for line in lines] == ["unmeasured"]
        assert lines[0]["detail"]["reason"] == "transcript-missing"

    def test_unreadable_transcript_is_its_own_reason(
        self, handler, tmp_path, project, transcript, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_transcript(transcript, 10)

        def unreadable(_path: Path) -> None:
            raise PermissionError("denied")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.pre_tool_use.subagent_context_budget.read_tail",
            unreadable,
        )
        assert handler.handle(event(tmp_path, project)).decision == Decision.ALLOW
        log = tmp_path / "untracked" / "logs" / "hooks" / "verdicts.jsonl"
        assert json.loads(log.read_text())["detail"]["reason"] == "transcript-unreadable"


class TestCostOnTheQuietPath:
    def test_below_every_band_never_computes_the_handoff_path(
        self, handler, tmp_path, project, transcript, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Review S1: the CLAUDE/Plan glob runs only when a band needs the path."""
        write_transcript(transcript, 10_000)
        calls: list[str] = []

        def counting(*args: Any) -> Path:
            calls.append("handoff_path")
            return project / "h.md"

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.pre_tool_use.subagent_context_budget.handoff_path",
            counting,
        )
        for _ in range(5):
            handler.handle(event(tmp_path, project))
        assert calls == []


class TestNeverLocksOut:
    """Review S4: under strict_mode an escaped exception would deny every call."""

    def test_an_unreadable_agent_directory_is_recorded_unreadable(
        self, handler, tmp_path, project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(*_args: object) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.pre_tool_use.subagent_context_budget."
            "resolve_agent_transcript",
            refuse,
        )
        assert handler.handle(event(tmp_path, project)).decision == Decision.ALLOW
        log = tmp_path / "untracked" / "logs" / "hooks" / "verdicts.jsonl"
        assert json.loads(log.read_text())["detail"]["reason"] == "transcript-unreadable"

    def test_any_failure_to_judge_allows_and_is_recorded(
        self, handler, tmp_path, project, transcript, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_transcript(transcript, 400_000)
        handler._hard_tokens = 250_000

        def broken(_hook_input: object) -> None:
            raise KeyError("boom")

        monkeypatch.setattr(handler, "bands_for", broken)
        assert handler.handle(event(tmp_path, project)).decision == Decision.ALLOW
        log = tmp_path / "untracked" / "logs" / "hooks" / "verdicts.jsonl"
        assert json.loads(log.read_text())["detail"]["reason"] == "handler-error"


class TestHardBand:
    @pytest.fixture(autouse=True)
    def _hard(self, handler: SubagentContextBudgetHandler, transcript: Path) -> None:
        handler._hard_tokens = 250_000
        write_transcript(transcript, 260_000)

    @pytest.mark.parametrize(
        ("tool", "tool_input"),
        [
            ("Bash", {"command": "git status"}),
            ("Bash", {"command": "git add -A && git commit -m 'WIP: handoff'"}),
            ("Bash", {"command": "cd /repo && git -C /repo diff --stat"}),
            ("Bash", {"command": "git log --oneline -3"}),
            ("SendMessage", {"to": "team-lead", "message": "handoff written"}),
            (
                "Write",
                {"file_path": "REPO/CLAUDE/Plan/00471-x/subagent-reports/h.md", "content": "x"},
            ),
            (
                "Edit",
                {
                    "file_path": "REPO/untracked/scratch/notes.md",
                    "old_string": "a",
                    "new_string": "b",
                },
            ),
            ("Read", {"file_path": "REPO/CLAUDE/Plan/00471-x/subagent-reports/h.md"}),
            # Review S2: quoted separators and the commit idioms a handoff needs.
            ("Bash", {"command": "git commit -m 'WIP: parser done; tests left'"}),
            ("Bash", {"command": "cd '/path with space' && git status"}),
            ("Bash", {"command": "git add -A && git commit -F untracked/scratch/msg.txt"}),
            ("Bash", {"command": 'git commit -m "WIP: handoff\n\nCo-Authored-By: x <x@y>"'}),
            ("Bash", {"command": "git status\ngit diff --stat"}),
            # A bare `&` is a separator like `;`: each side is judged on its own.
            ("Bash", {"command": "git status & git log --oneline -3"}),
            # Review N6: a deferred SendMessage must stay loadable.
            ("ToolSearch", {"query": "select:SendMessage"}),
        ],
    )
    def test_allowlist_passes(self, handler, tmp_path, project, tool, tool_input) -> None:
        for key, value in tool_input.items():
            if isinstance(value, str):
                tool_input[key] = value.replace("REPO", str(project))
        result = handler.handle(event(tmp_path, project, tool, tool_input))
        assert result.decision == Decision.ALLOW

    @pytest.mark.parametrize(
        ("tool", "tool_input"),
        [
            ("Bash", {"command": "ls"}),
            ("Bash", {"command": "git status; rm -rf src"}),
            ("Bash", {"command": 'git commit -m "$(pytest)"'}),
            ("Bash", {"command": "git push"}),
            ("Bash", {"command": "git status\nrm -rf src"}),
            ("Bash", {"command": "git status & rm -rf src"}),
            ("Bash", {"command": "git log > notes.txt"}),
            ("Bash", {"command": "git log 2>&1 >notes.txt"}),
            ("Bash", {"command": "(git status; rm -rf src)"}),
            ("Bash", {"command": "git commit -m 'unbalanced"}),
            ("Write", {"file_path": "REPO/src/x.py", "content": "x"}),
            ("Read", {"file_path": "REPO/src/x.py"}),
            ("Grep", {"pattern": "x"}),
            ("Agent", {"prompt": "x"}),
        ],
    )
    def test_everything_else_is_denied(self, handler, tmp_path, project, tool, tool_input) -> None:
        for key, value in tool_input.items():
            if isinstance(value, str):
                tool_input[key] = value.replace("REPO", str(project))
        result = handler.handle(event(tmp_path, project, tool, tool_input))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.SUBAGENT_CONTEXT_BUDGET}]")
        assert "-p471-impl-handoff.md" in result.reason
        assert "git commit -F" in result.reason
        assert "SendMessage" in result.reason
        assert "cannot Write" in result.reason

    def test_escalates_after_three_consecutive_denials(self, handler, tmp_path, project) -> None:
        reasons = [handler.handle(event(tmp_path, project)).reason or "" for _ in range(4)]
        assert all("stop now" not in reason.lower() for reason in reasons[:3])
        assert "stop now" in reasons[3].lower()
        assert "worktree state is the handoff" in reasons[3]

    def test_an_allowed_call_resets_the_count(self, handler, tmp_path, project) -> None:
        for _ in range(3):
            handler.handle(event(tmp_path, project))
        handler.handle(event(tmp_path, project, "Bash", {"command": "git status"}))
        reason = handler.handle(event(tmp_path, project)).reason or ""
        assert "stop now" not in reason.lower()

    def test_below_hard_but_above_soft_only_advises(
        self, handler, tmp_path, project, transcript
    ) -> None:
        write_transcript(transcript, 200_000)
        result = handler.handle(event(tmp_path, project))
        assert result.decision == Decision.ALLOW
        assert result.context


class TestOverride:
    def test_named_dispatch_budget_raises_the_band(
        self, handler, tmp_path, project, transcript
    ) -> None:
        record_dispatch(
            tmp_path / "untracked", SESSION, AGENT_NAME, "python-developer", budget_tokens=400_000
        )
        write_transcript(transcript, 350_000)
        assert not handler.handle(event(tmp_path, project)).context

    def test_override_is_clamped(self, handler, tmp_path, project, transcript) -> None:
        record_dispatch(
            tmp_path / "untracked", SESSION, AGENT_NAME, "python-developer", budget_tokens=900_000
        )
        write_transcript(transcript, 460_000)
        assert handler.handle(event(tmp_path, project)).context

    def test_override_raises_hard_too(self, handler, tmp_path, project, transcript) -> None:
        handler._hard_tokens = 250_000
        record_dispatch(
            tmp_path / "untracked", SESSION, AGENT_NAME, "python-developer", budget_tokens=400_000
        )
        write_transcript(transcript, 300_000)
        assert handler.handle(event(tmp_path, project)).decision == Decision.ALLOW

    def test_unnamed_agent_has_no_override(self, handler, tmp_path, project, transcript) -> None:
        unnamed_id = "a0123456789abcdef"
        record_dispatch(
            tmp_path / "untracked", SESSION, "qa-runner", "qa-runner", budget_tokens=400_000
        )
        write_transcript(transcript.with_name(f"agent-{unnamed_id}.jsonl"), 350_000)
        hook_input = event(tmp_path, project, agent_id=unnamed_id, agent_type="qa-runner")
        assert handler.handle(hook_input).context


class TestDocs:
    def test_rules_and_guidance(self) -> None:
        instance = SubagentContextBudgetHandler()
        assert [rule.rule_id for rule in instance.get_rules()] == [RuleID.SUBAGENT_CONTEXT_BUDGET]
        guidance = instance.get_claude_md()
        assert guidance is not None and "handoff" in guidance
        assert instance.get_acceptance_tests()
