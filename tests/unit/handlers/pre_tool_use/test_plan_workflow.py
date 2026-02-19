"""Tests for PlanWorkflowHandler.

Comprehensive test coverage for plan workflow guidance.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_workflow import PlanWorkflowHandler


class TestPlanWorkflowHandler:
    """Test suite for PlanWorkflowHandler."""

    @pytest.fixture
    def handler(self) -> PlanWorkflowHandler:
        """Create handler instance."""
        return PlanWorkflowHandler()

    # Tests for matches() method

    def test_matches_write_plan_md(self, handler: PlanWorkflowHandler) -> None:
        """Handler matches Write operation for PLAN.md in plan directory."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test-plan/PLAN.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_plan_md_uppercase(self, handler: PlanWorkflowHandler) -> None:
        """Handler matches Write operation for PLAN.md (uppercase)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/042-feature/PLAN.MD"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_plan_md_lowercase(self, handler: PlanWorkflowHandler) -> None:
        """Handler matches Write operation for plan.md (lowercase)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/010-bugfix/plan.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_plan_md_mixed_case(self, handler: PlanWorkflowHandler) -> None:
        """Handler matches Write operation for Plan.md (mixed case)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/005-update/Plan.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_windows_path(self, handler: PlanWorkflowHandler) -> None:
        """Handler matches Write operation with Windows-style path."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "C:\\workspace\\CLAUDE\\Plan\\001-test\\PLAN.md"},
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_write_other_files_in_plan(self, handler: PlanWorkflowHandler) -> None:
        """Handler does not match other files in plan directory."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test/README.md"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_write_plan_md_outside_plan_dir(
        self, handler: PlanWorkflowHandler
    ) -> None:
        """Handler does not match PLAN.md outside plan directory."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/docs/PLAN.md"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_edit_tool(self, handler: PlanWorkflowHandler) -> None:
        """Handler does not match Edit tool operations."""
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_read_tool(self, handler: PlanWorkflowHandler) -> None:
        """Handler does not match Read tool operations."""
        hook_input: dict[str, Any] = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_bash_tool(self, handler: PlanWorkflowHandler) -> None:
        """Handler does not match Bash tool operations."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat CLAUDE/Plan/001-test/PLAN.md"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_missing_file_path(self, handler: PlanWorkflowHandler) -> None:
        """Handler does not match when file_path is missing."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"content": "Some content"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_empty_file_path(self, handler: PlanWorkflowHandler) -> None:
        """Handler does not match when file_path is empty."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": ""},
        }
        assert handler.matches(hook_input) is False

    # Tests for handle() method

    def test_handle_allows_with_context(self, handler: PlanWorkflowHandler) -> None:
        """Handler allows operation with workflow context (shown as additionalContext)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context, "Advisory must be in context list"
        assert result.guidance is None

    def test_handle_context_includes_file_path(self, handler: PlanWorkflowHandler) -> None:
        """Handler context includes the file path."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/042-feature/PLAN.md"},
        }
        result = handler.handle(hook_input)
        assert "/workspace/CLAUDE/Plan/042-feature/PLAN.md" in result.context[0]

    def test_handle_context_includes_task_status_icons(self, handler: PlanWorkflowHandler) -> None:
        """Handler context mentions task status icons."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md"},
        }
        result = handler.handle(hook_input)
        assert "⬜" in result.context[0]
        assert "🔄" in result.context[0]
        assert "✅" in result.context[0]
        assert "not started" in result.context[0]
        assert "in progress" in result.context[0]
        assert "completed" in result.context[0]

    def test_handle_context_includes_success_criteria(self, handler: PlanWorkflowHandler) -> None:
        """Handler context mentions success criteria."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md"},
        }
        result = handler.handle(hook_input)
        assert "Success Criteria" in result.context[0]

    def test_handle_context_includes_manageable_phases(self, handler: PlanWorkflowHandler) -> None:
        """Handler context mentions breaking into phases."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md"},
        }
        result = handler.handle(hook_input)
        assert "manageable phases" in result.context[0]

    def test_handle_context_includes_status_updates(self, handler: PlanWorkflowHandler) -> None:
        """Handler context mentions updating task status."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md"},
        }
        result = handler.handle(hook_input)
        assert "Update task status" in result.context[0]

    def test_handle_context_references_guidelines(self, handler: PlanWorkflowHandler) -> None:
        """Handler context references full guidelines document."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md"},
        }
        result = handler.handle(hook_input)
        assert "CLAUDE/PlanWorkflow.md" in result.context[0]

    def test_handle_uses_context_not_guidance(self, handler: PlanWorkflowHandler) -> None:
        """Regression test: advisory MUST be returned as context, not guidance.

        Bug: PlanWorkflowHandler returned guidance=... but Claude Code only
        surfaces additionalContext (context list) in system-reminders for
        PreToolUse events. guidance is silently ignored, making the advisory
        invisible to the agent.

        Fix: return context=[guidance_text] so advisory appears in system-reminders.
        """
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md"},
        }
        result = handler.handle(hook_input)
        assert result.context, "Advisory must be in context list (shown as additionalContext)"
        assert result.guidance is None, "guidance field is not shown in PreToolUse system-reminders"
        assert any("Workflow" in c for c in result.context), "Context must contain 'Workflow'"

    # Tests for handler metadata

    def test_handler_has_correct_name(self, handler: PlanWorkflowHandler) -> None:
        """Handler has correct name."""
        assert handler.name == "plan-workflow-guidance"

    def test_handler_has_correct_priority(self, handler: PlanWorkflowHandler) -> None:
        """Handler has correct priority."""
        assert handler.priority == 45

    def test_handler_is_non_terminal(self, handler: PlanWorkflowHandler) -> None:
        """Handler is non-terminal (advisory)."""
        assert handler.terminal is False

    def test_handler_has_correct_tags(self, handler: PlanWorkflowHandler) -> None:
        """Handler has correct tags."""
        assert "workflow" in handler.tags
        assert "planning" in handler.tags
        assert "advisory" in handler.tags
        assert "non-terminal" in handler.tags
