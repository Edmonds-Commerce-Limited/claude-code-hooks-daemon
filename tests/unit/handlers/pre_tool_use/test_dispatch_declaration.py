"""Enforce the Plan 00307 file-handoff contract at Agent/Task dispatch time.

A subagent's final message travels through a bounded-size wire channel (Task
1.1's reproduction: a 24k-token inline return was silently elided in the
MIDDLE by the harness). The fix has two halves — prevention at dispatch
(this handler) and enforcement at return (SubagentStop). This handler injects
or, in strict mode, requires a declaration on every ``Task`` dispatch prompt:
EITHER a plan-folder path (which becomes the canonical home for the agent's
``subagent-reports/`` artefacts) OR an explicit "not plan work" + declared
file destination.

Design constraints pinned:

- **Silent when a declaration is already present** — advising someone who
  already did the right thing trains them to ignore the advisory.
- **Advisory by default** — ``additionalContext`` injects the contract but
  never blocks the dispatch.
- **Strict mode is opt-in** — denies an undeclared dispatch instead.
- **Never raises** — a malformed ``tool_input`` must not crash matching.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.dispatch_declaration import (
    DispatchDeclarationHandler,
)


def _task_input(prompt: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"prompt": prompt}
    payload.update(extra)
    return {"tool_name": "Task", "tool_input": payload}


@pytest.fixture
def handler() -> DispatchDeclarationHandler:
    return DispatchDeclarationHandler()


@pytest.fixture
def strict_handler() -> DispatchDeclarationHandler:
    instance = DispatchDeclarationHandler()
    instance._strict = True
    return instance


class TestIdentity:
    def test_is_advisory_by_default(self, handler: DispatchDeclarationHandler) -> None:
        assert handler.terminal is False

    def test_exposes_claude_md_guidance(self, handler: DispatchDeclarationHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "subagent-reports" in guidance


class TestMatching:
    def test_matches_task_dispatch_with_prompt(self, handler: DispatchDeclarationHandler) -> None:
        assert handler.matches(_task_input("do some work")) is True

    def test_does_not_match_non_task_tool(self, handler: DispatchDeclarationHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        assert handler.matches(hook_input) is False

    def test_does_not_match_task_without_prompt(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        hook_input = {"tool_name": "Task", "tool_input": {}}
        assert handler.matches(hook_input) is False

    def test_matches_returns_false_on_malformed_tool_input(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        hook_input = {"tool_name": "Task", "tool_input": "not-a-dict"}
        assert handler.matches(hook_input) is False


class TestAdvisoryMode:
    def test_silent_when_plan_folder_declared(self, handler: DispatchDeclarationHandler) -> None:
        prompt = (
            "This is Plan 00307 work: /workspace/CLAUDE/Plan/00307-subagent-file-based"
            "-report-handoff/. Write your findings there."
        )
        result = handler.handle(_task_input(prompt))

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_silent_when_not_plan_work_declared_with_destination(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        prompt = (
            "This is not plan work. Write your report to untracked/agent-reports/"
            "260901-probe-haiku.md and reply with a short summary."
        )
        result = handler.handle(_task_input(prompt))

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_injects_contract_when_declaration_absent(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        result = handler.handle(_task_input("refactor the config loader"))

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "subagent-reports" in result.context[0]
        assert "plan folder" in result.context[0].lower()

    def test_not_plan_work_alone_without_destination_is_not_a_declaration(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        result = handler.handle(_task_input("this is not plan work, just do it"))

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1


class TestStrictMode:
    def test_denies_undeclared_dispatch_in_strict_mode(
        self, strict_handler: DispatchDeclarationHandler
    ) -> None:
        result = strict_handler.handle(_task_input("refactor the config loader"))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "subagent-reports" in result.reason

    def test_allows_declared_dispatch_in_strict_mode(
        self, strict_handler: DispatchDeclarationHandler
    ) -> None:
        prompt = "Plan 00307: /workspace/CLAUDE/Plan/00307-subagent-file-based-report-handoff/"

        result = strict_handler.handle(_task_input(prompt))

        assert result.decision == Decision.ALLOW
