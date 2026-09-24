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


_DECLARED_PROMPT = (
    "This is Plan 00307 work: /workspace/CLAUDE/Plan/00307-subagent-file-based"
    "-report-handoff/. Write your findings there."
)


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

    def test_matches_agent_tool_dispatch_with_prompt(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        # Claude Code >= 2.1.x dispatches subagents under tool_name "Agent"
        # (verified live in the v3.59.0 acceptance run); the handler must
        # match both the legacy "Task" name and "Agent".
        hook_input = {"tool_name": "Agent", "tool_input": {"prompt": "do some work"}}
        assert handler.matches(hook_input) is True

    def test_does_not_match_non_task_tool(self, handler: DispatchDeclarationHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        assert handler.matches(hook_input) is False

    def test_does_not_match_task_without_prompt(self, handler: DispatchDeclarationHandler) -> None:
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

    def test_string_false_strict_option_is_not_treated_as_strict(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        """N3 code-review fix: a YAML author writing ``strict: "false"`` (a
        string, e.g. from an env-var-substituted config) must not be coerced
        truthy by bare Python truthiness -- that would silently deny every
        undeclared dispatch despite the config saying not-strict."""
        handler._strict = "false"

        result = handler.handle(_task_input("refactor the config loader"))

        assert result.decision == Decision.ALLOW

    def test_string_true_strict_option_is_treated_as_strict(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        handler._strict = "true"

        result = handler.handle(_task_input("refactor the config loader"))

        assert result.decision == Decision.DENY


class TestReadOnlyDispatchAdvisory:
    """Plan 00460 Task 1.4: an ADVISORY, never a deny, when the dispatched
    `subagent_type` resolves read-only AND the prompt declares a report
    path -- the coordinator brief that told a Write-less agent to write a
    file was the other half of the original bug report."""

    def test_advises_when_read_only_type_dispatched_with_declaration(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        hook_input = _task_input(_DECLARED_PROMPT, subagent_type="Explore")

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "Explore" in result.context[0]
        assert "no `Write` tool" in result.context[0]

    def test_silent_when_writable_type_dispatched_with_declaration(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        hook_input = _task_input(_DECLARED_PROMPT, subagent_type="general-purpose")

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_silent_when_subagent_type_missing(self, handler: DispatchDeclarationHandler) -> None:
        """No `subagent_type` on the dispatch resolves unknown -- never guessed."""
        result = handler.handle(_task_input(_DECLARED_PROMPT))

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_no_advisory_when_read_only_type_dispatched_without_declaration(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        """Task 1.4 is scoped to a DECLARED report path -- an undeclared
        dispatch already gets the standard contract-injection advisory, and
        does not additionally get the read-only mismatch one."""
        hook_input = _task_input("refactor the config loader", subagent_type="Explore")

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "DISPATCH DECLARATION" in result.context[0]

    def test_advisory_fires_even_in_strict_mode_and_never_denies(
        self, strict_handler: DispatchDeclarationHandler
    ) -> None:
        hook_input = _task_input(_DECLARED_PROMPT, subagent_type="Explore")

        result = strict_handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "no `Write` tool" in result.context[0]

    def test_project_agent_without_write_tool_is_advised(
        self, handler: DispatchDeclarationHandler, tmp_path: Any
    ) -> None:
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "code-reviewer.md").write_text(
            "---\nname: code-reviewer\ndescription: reviews code\n"
            "tools: Read, Glob, Grep, Bash\n---\n\nBody.\n"
        )
        handler._project_root = tmp_path
        hook_input = _task_input(_DECLARED_PROMPT, subagent_type="code-reviewer")

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "code-reviewer" in result.context[0]


class TestConfiguredPlanDirectory:
    """Plan 00311 Task 1.1 (N1): declaration option 1 must recognise the
    project's CONFIGURED plan directory, not just the ``CLAUDE/Plan/``
    literal -- a project with a non-default ``plan_workflow.directory`` could
    never satisfy it otherwise, so the advisory (or, in strict mode, the
    deny) fired on every compliant dispatch."""

    def test_recognises_declaration_under_non_default_plan_dir(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        """A non-default ``ProjectLayout.plan_dir`` (Plan 00288 facade,
        injected unconditionally by the registry) is honoured, mirroring
        ``plan_workflow.py``'s identical fix for the same facade."""
        from claude_code_hooks_daemon.core.project_layout import ProjectLayout

        handler._project_layout = ProjectLayout(
            source_dirs=(),
            test_dirs=(),
            config_dirs=("config",),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="Plans",
            plan_archive_dirs=("Completed",),
        )
        prompt = "This is Plan 00042 work: Plans/00042-widget/. Write your findings there."

        result = handler.handle(_task_input(prompt))

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_default_plan_dir_literal_no_longer_matches_non_default_dir(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        """The old hardcoded ``CLAUDE/Plan/`` literal must NOT satisfy the
        declaration once a non-default directory is configured -- otherwise
        the pattern would silently accept a path the project does not use."""
        from claude_code_hooks_daemon.core.project_layout import ProjectLayout

        handler._project_layout = ProjectLayout(
            source_dirs=(),
            test_dirs=(),
            config_dirs=("config",),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="Plans",
            plan_archive_dirs=("Completed",),
        )
        prompt = "This is Plan 00042 work: CLAUDE/Plan/00042-widget/. Write your findings there."

        result = handler.handle(_task_input(prompt))

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1

    def test_no_layout_injected_falls_back_to_default_plan_dir(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        """A handler constructed directly (no registry injection, as every
        other test in this file does) must still recognise the default
        ``CLAUDE/Plan/`` literal -- the fallback constant matches
        ``PlanWorkflowConfig.directory``'s default."""
        assert handler._project_layout is None

        prompt = "Plan 00307: CLAUDE/Plan/00307-subagent-file-based-report-handoff/"

        result = handler.handle(_task_input(prompt))

        assert result.decision == Decision.ALLOW
        assert result.context == []
