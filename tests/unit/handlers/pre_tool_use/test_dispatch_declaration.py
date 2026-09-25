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
from tests.claude_plugin_fixture import READ_ONLY_TOOLS, install_fake_plugin

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

# Plan 00460 review finding m4: unlike `_DECLARED_PROMPT` above, this one also
# matches `_DESTINATION_PATTERN` (a verb + to/in/under/into + a path-shaped
# token) -- the read-only-mismatch advisory is scoped to an explicit report
# DESTINATION, not to a bare plan-folder mention, so tests that exercise that
# advisory need a prompt that actually declares one.
_DECLARED_PROMPT_WITH_DESTINATION = (
    "This is Plan 00307 work: /workspace/CLAUDE/Plan/00307-subagent-file-based"
    "-report-handoff/. Write your report to CLAUDE/Plan/00307-subagent-file-based"
    "-report-handoff/subagent-reports/output.md."
)


@pytest.fixture
def handler(tmp_path: Any) -> DispatchDeclarationHandler:
    """Plan 00460 review finding m10: root both the project- and user-agent
    lookups (`resolve_agent_can_write`'s two bases) at fresh `tmp_path`
    subdirectories by default, neither of which exists. Left unset, a test
    that never sets `_project_root` resolves against the REAL checkout via
    `resolve_lookup_root`'s cwd fallback, and `_config_dir` unset resolves
    against the real Claude home -- a real risk now that review finding M4
    makes project/user agents consulted BEFORE the built-in table: this
    repo's own real `.claude/agents/` (or a developer's real `~/.claude/
    agents/`) could silently answer a lookup a test meant to be hermetic.
    Individual tests that need a populated agents dir (e.g.
    `test_project_agent_without_write_tool_is_advised`) override
    `_project_root` explicitly."""
    instance = DispatchDeclarationHandler()
    instance._project_root = tmp_path / "project"
    instance._config_dir = tmp_path / "config"
    return instance


@pytest.fixture
def strict_handler(tmp_path: Any) -> DispatchDeclarationHandler:
    instance = DispatchDeclarationHandler()
    instance._strict = True
    instance._project_root = tmp_path / "project"
    instance._config_dir = tmp_path / "config"
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

    def test_contract_mentions_the_daemon_auto_saves_a_safety_net(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        """Plan 00460 Task 1.6: the daemon persists every reply regardless of
        a declaration, so the contract text says so rather than implying
        the declared destination is the only way a reply survives."""
        result = handler.handle(_task_input("refactor the config loader"))

        assert result.context[0] is not None
        assert "auto-sav" in result.context[0].lower()

    def test_not_plan_work_alone_without_destination_is_not_a_declaration(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        result = handler.handle(_task_input("this is not plan work, just do it"))

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1


_PLAN_WORK_TO_GITIGNORED_FALLBACK = (
    "Review the v3.65.0 diff for Plan 00422: /workspace/CLAUDE/Plan/00422-niggles"
    "-ledger-fifteen/. Write your report to untracked/agent-reports/"
    "260924-review-opus.md and reply with a short summary."
)


class TestTheDefaultDestinationIsTracked:
    """Ledger 00422 N5, decision 6: evidence must land where git can see it.

    Twenty release-review non-defects were written to the gitignored
    ``untracked/agent-reports/`` while a plan applied, and were one container
    restart from gone. The plan's ``subagent-reports/`` is the default; the
    gitignored directory is the fallback only when no plan applies.
    """

    def test_the_contract_names_the_plan_folder_as_the_tracked_default(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        text = handler.handle(_task_input("refactor the config loader")).context[0]

        assert "tracked" in text.lower()
        assert "default" in text.lower()
        assert text.find("subagent-reports") < text.find("untracked/agent-reports/")

    def test_the_contract_says_the_fallback_is_gitignored_and_only_for_plan_less_work(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        text = handler.handle(_task_input("refactor the config loader")).context[0].lower()

        assert "gitignored" in text
        assert "only when no plan applies" in text

    def test_strict_mode_denies_with_the_same_default(
        self, strict_handler: DispatchDeclarationHandler
    ) -> None:
        reason = strict_handler.handle(_task_input("refactor the config loader")).reason

        assert reason is not None
        assert "tracked" in reason.lower()
        assert "only when no plan applies" in reason.lower()

    def test_claude_md_guidance_states_the_tracked_default(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        guidance = handler.get_claude_md()

        assert guidance is not None
        assert "tracked" in guidance.lower()
        assert "only when no plan applies" in guidance.lower()

    def test_plan_work_sent_to_the_gitignored_fallback_is_advised(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        """The N5 shape: a plan applies, and the report still goes to the
        directory git cannot see."""
        result = handler.handle(_task_input(_PLAN_WORK_TO_GITIGNORED_FALLBACK))

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "gitignored" in result.context[0].lower()
        assert "CLAUDE/Plan/00422-niggles-ledger-fifteen/subagent-reports/" in result.context[0]

    def test_plan_work_sent_to_the_gitignored_fallback_is_never_denied(
        self, strict_handler: DispatchDeclarationHandler
    ) -> None:
        """A declared destination is a declaration: strict mode denies only
        an UNDECLARED dispatch, so this stays advisory there too."""
        result = strict_handler.handle(_task_input(_PLAN_WORK_TO_GITIGNORED_FALLBACK))

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1

    def test_plan_work_sent_to_its_own_subagent_reports_is_silent(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        """Control: the tracked destination draws nothing."""
        hook_input = _task_input(_DECLARED_PROMPT_WITH_DESTINATION, subagent_type="general-purpose")

        assert handler.handle(hook_input).context == []

    def test_plan_less_work_sent_to_the_fallback_is_silent(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        """Control: with no plan, the fallback is the right destination."""
        prompt = (
            "This is not plan work. Write your report to untracked/agent-reports/"
            "260901-probe-haiku.md and reply with a short summary."
        )

        assert handler.handle(_task_input(prompt)).context == []

    def test_a_plan_prompt_that_only_mentions_the_fallback_is_silent(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        """Only a DESTINATION under the fallback counts, not any mention of it."""
        prompt = (
            "Plan 00422: /workspace/CLAUDE/Plan/00422-niggles-ledger-fifteen/. The "
            "daemon also keeps a copy under untracked/agent-reports/auto/."
        )

        assert handler.handle(_task_input(prompt)).context == []

    def test_a_configured_fallback_directory_is_the_one_judged(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        handler._fallback_report_dir = "scratch/reports/"
        prompt = (
            "Plan 00422: CLAUDE/Plan/00422-niggles-ledger-fifteen/. Save it to "
            "scratch/reports/260924-x.md."
        )

        result = handler.handle(_task_input(prompt))

        assert len(result.context) == 1
        assert "scratch/reports/" in result.context[0]


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
        hook_input = _task_input(_DECLARED_PROMPT_WITH_DESTINATION, subagent_type="Explore")

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "Explore" in result.context[0]
        assert "no `Write` tool" in result.context[0]

    def test_read_only_mismatch_mentions_the_auto_saved_path(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        """Plan 00460 Task 1.6: since the daemon now auto-saves every reply
        regardless of Write access, the mismatch advisory should say so
        rather than only suggesting a writable type or an inline summary."""
        hook_input = _task_input(_DECLARED_PROMPT_WITH_DESTINATION, subagent_type="Explore")

        result = handler.handle(hook_input)

        assert "agent-reports" in result.context[0]

    def test_silent_when_writable_type_dispatched_with_declaration(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        hook_input = _task_input(_DECLARED_PROMPT_WITH_DESTINATION, subagent_type="general-purpose")

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_silent_when_subagent_type_missing(self, handler: DispatchDeclarationHandler) -> None:
        """No `subagent_type` on the dispatch resolves unknown -- never guessed."""
        result = handler.handle(_task_input(_DECLARED_PROMPT_WITH_DESTINATION))

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_no_advisory_when_plan_folder_is_only_context(
        self, handler: DispatchDeclarationHandler
    ) -> None:
        """Plan 00460 review finding m4: a bare plan-folder mention with no
        explicit destination phrasing (`_DECLARED_PROMPT` says "Write your
        findings there", naming no path directly) satisfies the standard
        declaration (so the contract-injection advisory stays silent) but
        must NOT additionally trigger the read-only-mismatch advisory --
        that one is scoped to a prompt that actually names a report
        destination, not to any prompt that merely cites a plan folder."""
        hook_input = _task_input(_DECLARED_PROMPT, subagent_type="Explore")

        result = handler.handle(hook_input)

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
        hook_input = _task_input(_DECLARED_PROMPT_WITH_DESTINATION, subagent_type="Explore")

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
        hook_input = _task_input(_DECLARED_PROMPT_WITH_DESTINATION, subagent_type="code-reviewer")

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "code-reviewer" in result.context[0]

    def test_plugin_agent_without_write_tool_is_advised(
        self, handler: DispatchDeclarationHandler, tmp_path: Any
    ) -> None:
        """Plan 00468 P2: the audit's reproduction. A Write-less plugin agent
        dispatched with a declared report path got nothing; `Explore` got the
        advisory."""
        project = tmp_path / "plugin-project"
        (project / ".claude").mkdir(parents=True)
        config = tmp_path / "plugin-config"
        install_fake_plugin(
            config,
            project,
            agents={
                "conformance-reviewer.md": (
                    f"name: conformance-reviewer\ndescription: d\ntools: {READ_ONLY_TOOLS}"
                )
            },
        )
        handler._project_root = project
        handler._config_dir = config
        agent = "defence-before-fix:conformance-reviewer"
        hook_input = _task_input(_DECLARED_PROMPT_WITH_DESTINATION, subagent_type=agent)

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert agent in result.context[0]
        assert "no `Write` tool" in result.context[0]

    def test_project_agent_with_a_colon_in_its_description_is_advised(
        self, handler: DispatchDeclarationHandler, tmp_path: Any
    ) -> None:
        """Plan 00468 P6: this repository's real code-reviewer.md shape."""
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "code-reviewer.md").write_text(
            "---\nname: code-reviewer\ndescription: Analyzes real quality issues: dead code\n"
            "tools: Read, Glob, Grep, Bash\n---\n\nBody.\n"
        )
        handler._project_root = tmp_path
        hook_input = _task_input(_DECLARED_PROMPT_WITH_DESTINATION, subagent_type="code-reviewer")

        result = handler.handle(hook_input)

        assert len(result.context) == 1
        assert "no `Write` tool" in result.context[0]


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
