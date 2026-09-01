"""Tests for Handler.workspace_scope (Plan 00301 follow-up, Task 2).

Pins the machine-readable REPO/PROJECT taxonomy defined in
CLAUDE/Code/WorkspaceResolution.md: REPO-level handlers must not consume
per-project layout/workspace resolution; PROJECT-level handlers resolve via
the injected ProjectRegistry helpers (resolve_workspace/layout_for), never
ProjectContext.project_root() for project-shaped questions.
"""

from claude_code_hooks_daemon.core.handler import Handler, WorkspaceScope
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import GoalInjectionHandler
from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    RecoveryCronAdvisorHandler,
)
from claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write import (
    ValidateEslintOnWriteHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.british_english import BritishEnglishHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization import (
    MarkdownOrganizationHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.npm_command import NpmCommandHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_workflow import PlanWorkflowHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.tdd_enforcement import TddEnforcementHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.worktree_file_copy import (
    WorktreeFileCopyHandler,
)
from claude_code_hooks_daemon.handlers.session_start.docs_qa_sweep import DocsQaSweepHandler
from claude_code_hooks_daemon.handlers.session_start.monorepo_detector import (
    MonorepoDetectorHandler,
)


class _PlainHandler(Handler):
    """A handler that declares nothing beyond the abstract minimum."""

    def matches(self, hook_input: dict) -> bool:
        return False

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list:
        return []


class TestHandlerWorkspaceScopeDefault:
    """The base class default is REPO -- the neutral, backward-compatible value."""

    def test_default_workspace_scope_is_repo(self) -> None:
        """A handler that declares nothing defaults to WorkspaceScope.REPO."""
        assert _PlainHandler.workspace_scope is WorkspaceScope.REPO


class TestProjectLevelHandlersDeclareProjectScope:
    """Handlers that must resolve per-project layout/workspace declare PROJECT."""

    def test_npm_command_is_project_scoped(self) -> None:
        assert NpmCommandHandler.workspace_scope is WorkspaceScope.PROJECT

    def test_lint_on_edit_is_project_scoped(self) -> None:
        assert LintOnEditHandler.workspace_scope is WorkspaceScope.PROJECT

    def test_validate_eslint_on_write_is_project_scoped(self) -> None:
        assert ValidateEslintOnWriteHandler.workspace_scope is WorkspaceScope.PROJECT

    def test_tdd_enforcement_is_project_scoped(self) -> None:
        assert TddEnforcementHandler.workspace_scope is WorkspaceScope.PROJECT

    def test_markdown_organization_is_project_scoped(self) -> None:
        assert MarkdownOrganizationHandler.workspace_scope is WorkspaceScope.PROJECT

    def test_monorepo_detector_is_project_scoped(self) -> None:
        assert MonorepoDetectorHandler.workspace_scope is WorkspaceScope.PROJECT

    def test_worktree_file_copy_is_project_scoped(self) -> None:
        assert WorktreeFileCopyHandler.workspace_scope is WorkspaceScope.PROJECT


class TestRepoLevelHandlersDeclareRepoScope:
    """Handlers whose concern is repository-singular declare REPO explicitly."""

    def test_docs_qa_sweep_is_repo_scoped(self) -> None:
        assert DocsQaSweepHandler.workspace_scope is WorkspaceScope.REPO

    def test_plan_workflow_is_repo_scoped(self) -> None:
        assert PlanWorkflowHandler.workspace_scope is WorkspaceScope.REPO

    def test_goal_injection_is_repo_scoped(self) -> None:
        assert GoalInjectionHandler.workspace_scope is WorkspaceScope.REPO

    def test_recovery_cron_advisor_is_repo_scoped(self) -> None:
        assert RecoveryCronAdvisorHandler.workspace_scope is WorkspaceScope.REPO

    def test_british_english_is_repo_scoped(self) -> None:
        """Doc-tree dir names are sourced from the ROOT project's
        `documentation.trees` config even when composing a declared
        sub-project's layout -- no per-project override exists, so this
        handler's true axis is repository-singular by design."""
        assert BritishEnglishHandler.workspace_scope is WorkspaceScope.REPO
