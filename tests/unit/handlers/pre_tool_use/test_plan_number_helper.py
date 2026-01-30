"""Tests for PlanNumberHelperHandler.

This handler prevents Claude from using broken bash commands to discover plan numbers.
Instead, it provides the correct next plan number via context injection.
"""

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_project_context():
    """Mock ProjectContext for handler instantiation tests."""
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/test")
        yield mock


import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper import (
    PlanNumberHelperHandler,
)


class TestPlanNumberHelperHandler:
    """Test plan number helper handler."""

    @pytest.fixture
    def handler_enabled(self, tmp_path: Path) -> PlanNumberHelperHandler:
        """Create handler with planning mode enabled."""
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = "CLAUDE/Plan"
        return handler

    @pytest.fixture
    def handler_disabled(self, tmp_path: Path) -> PlanNumberHelperHandler:
        """Create handler with planning mode disabled."""
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = None  # Planning mode disabled
        return handler

    @pytest.fixture
    def handler_with_workflow_docs(self, tmp_path: Path) -> PlanNumberHelperHandler:
        """Create handler with workflow docs configured."""
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = "CLAUDE/Plan"
        handler._plan_workflow_docs = "CLAUDE/PlanWorkflow.md"

        # Create the workflow docs file
        workflow_file = tmp_path / "CLAUDE" / "PlanWorkflow.md"
        workflow_file.parent.mkdir(parents=True, exist_ok=True)
        workflow_file.write_text("# Plan Workflow\n\nGuidance here...")

        return handler

    def test_initialization(self) -> None:
        """Handler should initialize with correct settings."""
        handler = PlanNumberHelperHandler()
        assert handler.name == "plan-number-helper"
        assert handler.priority == 30  # Run before other workflow handlers
        assert not handler.terminal  # Non-blocking, advisory only
        assert "workflow" in handler.tags
        assert "advisory" in handler.tags

    def test_disabled_when_planning_mode_off(
        self, handler_disabled: PlanNumberHelperHandler
    ) -> None:
        """Handler should not match when planning mode is disabled."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d CLAUDE/Plan/0* 2>/dev/null | sort -V | tail -1"},
        }

        assert not handler_disabled.matches(hook_input)

    def test_detects_ls_glob_pattern(self, handler_enabled: PlanNumberHelperHandler) -> None:
        """Should detect ls commands with glob patterns on plan directory."""
        commands = [
            "ls -d CLAUDE/Plan/0* 2>/dev/null | sort -V | tail -1",
            "ls -d CLAUDE/Plan/[0-9]* | tail -1",
            "ls CLAUDE/Plan/ | grep -E '^[0-9]' | sort | tail -1",
            "ls -1 CLAUDE/Plan | sort -n | tail -1",
        ]

        for command in commands:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert handler_enabled.matches(hook_input), f"Should match: {command}"

    def test_detects_find_commands(self, handler_enabled: PlanNumberHelperHandler) -> None:
        """Should detect find commands on plan directory."""
        commands = [
            "find CLAUDE/Plan -maxdepth 1 -type d | tail -1",
            "find CLAUDE/Plan/ -name '0*' -type d",
            "find CLAUDE/Plan -type d -name '[0-9]*' | sort | tail -1",
        ]

        for command in commands:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert handler_enabled.matches(hook_input), f"Should match: {command}"

    def test_detects_glob_expansion(self, handler_enabled: PlanNumberHelperHandler) -> None:
        """Should detect glob expansion attempts."""
        commands = [
            "echo CLAUDE/Plan/0* | awk '{print $NF}'",
            "printf '%s\\n' CLAUDE/Plan/[0-9]* | tail -1",
        ]

        for command in commands:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert handler_enabled.matches(hook_input), f"Should match: {command}"

    def test_ignores_safe_commands(self, handler_enabled: PlanNumberHelperHandler) -> None:
        """Should not match safe commands."""
        safe_commands = [
            "ls -la",
            "find . -name '*.py'",
            "cat CLAUDE/Plan/00042-feature/PLAN.md",
            "mkdir -p CLAUDE/Plan/00123-new-feature",
            "git status",
        ]

        for command in safe_commands:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert not handler_enabled.matches(hook_input), f"Should NOT match: {command}"

    def test_ignores_non_bash_tools(self, handler_enabled: PlanNumberHelperHandler) -> None:
        """Should only match Bash tool, not others."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "CLAUDE/Plan/00042-feature/PLAN.md"},
        }

        assert not handler_enabled.matches(hook_input)

    @patch("claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper.get_next_plan_number")
    def test_returns_correct_next_plan_number(
        self, mock_get_next: any, handler_enabled: PlanNumberHelperHandler, tmp_path: Path
    ) -> None:
        """Should return correct next plan number in context."""
        # Mock the plan numbering utility
        mock_get_next.return_value = "00042"

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "ls -d CLAUDE/Plan/0* 2>/dev/null | sort -V | tail -1",
                "description": "Get latest plan number",
            },
        }

        result = handler_enabled.handle(hook_input)

        # Should return ALLOW with context
        assert result.decision == Decision.ALLOW
        assert result.context is not None
        assert len(result.context) > 0

        # Context should include next plan number
        context_str = " ".join(result.context)
        assert "00042" in context_str
        assert "next plan number" in context_str.lower()

        # Should call get_next_plan_number with correct path
        mock_get_next.assert_called_once()
        call_args = mock_get_next.call_args[0][0]
        assert call_args == tmp_path / "CLAUDE/Plan"

    @patch("claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper.get_next_plan_number")
    def test_provides_helpful_context_message(
        self, mock_get_next: any, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Should provide clear, actionable context message."""
        mock_get_next.return_value = "00123"

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d CLAUDE/Plan/0* | tail -1"},
        }

        result = handler_enabled.handle(hook_input)

        assert result.decision == Decision.ALLOW
        context_str = " ".join(result.context)

        # Should explain the problem and provide solution
        assert "00123" in context_str
        assert "next" in context_str.lower()
        assert "plan" in context_str.lower()

    def test_handler_is_non_terminal(self, handler_enabled: PlanNumberHelperHandler) -> None:
        """Handler should be non-terminal to allow command execution."""
        # This is advisory only - we want to provide context but not block
        assert not handler_enabled.terminal

    def test_priority_runs_before_other_workflow_handlers(self) -> None:
        """Should run before other workflow handlers (priority 30)."""
        handler = PlanNumberHelperHandler()
        assert handler.priority == 30

        # Should run before markdown_organization (priority 35)
        # This ensures we provide context before any potential blocking

    def test_custom_plan_directory(self, tmp_path: Path) -> None:
        """Should work with custom plan directory paths."""
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = "custom/plans/dir"

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d custom/plans/dir/0* | tail -1"},
        }

        # Should match based on configured plan directory
        assert handler.matches(hook_input)

    @patch("claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper.get_next_plan_number")
    def test_handles_get_next_plan_number_errors(
        self, mock_get_next: any, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Should handle errors from get_next_plan_number gracefully."""
        # Simulate error getting next plan number
        mock_get_next.side_effect = Exception("Plan directory not accessible")

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d CLAUDE/Plan/0* | tail -1"},
        }

        result = handler_enabled.handle(hook_input)

        # Should still return ALLOW (non-blocking)
        assert result.decision == Decision.ALLOW

        # Should provide error context
        if result.context:
            context_str = " ".join(result.context)
            assert "error" in context_str.lower() or "00001" in context_str

    @patch("claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper.get_next_plan_number")
    def test_includes_workflow_docs_when_configured(
        self, mock_get_next: any, handler_with_workflow_docs: PlanNumberHelperHandler
    ) -> None:
        """Should include workflow docs reference when configured and file exists."""
        mock_get_next.return_value = "00042"

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d CLAUDE/Plan/0* | tail -1"},
        }

        result = handler_with_workflow_docs.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert result.context is not None
        context_str = " ".join(result.context)

        # Should include plan number
        assert "00042" in context_str

        # Should include workflow docs reference
        assert "CLAUDE/PlanWorkflow.md" in context_str
        assert "plan structure" in context_str.lower() or "conventions" in context_str.lower()

    @patch("claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper.get_next_plan_number")
    def test_omits_workflow_docs_when_file_missing(
        self, mock_get_next: any, tmp_path: Path
    ) -> None:
        """Should not include workflow docs reference when file doesn't exist."""
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = "CLAUDE/Plan"
        handler._plan_workflow_docs = "CLAUDE/PlanWorkflow.md"
        # Note: Not creating the workflow file

        mock_get_next.return_value = "00042"

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d CLAUDE/Plan/0* | tail -1"},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert result.context is not None
        context_str = " ".join(result.context)

        # Should include plan number
        assert "00042" in context_str

        # Should NOT include workflow docs reference (file doesn't exist)
        assert "PlanWorkflow.md" not in context_str

    @patch("claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper.get_next_plan_number")
    def test_works_without_workflow_docs_config(
        self, mock_get_next: any, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Should work normally when workflow docs are not configured."""
        # handler_enabled fixture doesn't have _plan_workflow_docs set
        mock_get_next.return_value = "00042"

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d CLAUDE/Plan/0* | tail -1"},
        }

        result = handler_enabled.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert result.context is not None
        context_str = " ".join(result.context)

        # Should include plan number
        assert "00042" in context_str

        # Should NOT crash or include workflow docs
        assert "PlanWorkflow.md" not in context_str
