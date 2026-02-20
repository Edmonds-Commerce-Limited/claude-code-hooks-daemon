"""Tests for PlanCompletionAdvisorHandler.

Comprehensive test coverage for plan completion move advisory.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_completion_advisor import (
    PlanCompletionAdvisorHandler,
)


class TestPlanCompletionAdvisorHandler:
    """Test suite for PlanCompletionAdvisorHandler."""

    @pytest.fixture
    def handler(self) -> PlanCompletionAdvisorHandler:
        """Create handler instance."""
        return PlanCompletionAdvisorHandler()

    # ===== Handler metadata tests =====

    def test_handler_has_correct_name(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler has correct display name."""
        assert handler.name == "plan-completion-advisor"

    def test_handler_has_correct_priority(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler has correct priority (50, workflow range)."""
        assert handler.priority == 50

    def test_handler_is_non_terminal(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler is non-terminal (advisory only)."""
        assert handler.terminal is False

    def test_handler_has_correct_tags(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler has correct tags for workflow/planning/advisory."""
        assert "workflow" in handler.tags
        assert "planning" in handler.tags
        assert "advisory" in handler.tags
        assert "non-terminal" in handler.tags

    # ===== matches() positive tests =====

    def test_matches_write_plan_md_with_status_complete(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler matches Write tool writing PLAN.md with Status: Complete."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "content": "# Plan 00014\n\n**Status**: Complete\n\n## Overview\n",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_plan_md_with_status_complete(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler matches Edit tool changing status to Complete."""
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "old_string": "**Status**: In Progress",
                "new_string": "**Status**: Complete",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_status_complete_with_date(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler matches Status: Complete (2026-02-06) with date suffix."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "content": "# Plan 00014\n\n**Status**: Complete (2026-02-06)\n\n## Overview\n",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_status_completed(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler matches Status: Completed (past tense variation)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00027-plan-completion/PLAN.md",
                "content": "# Plan 00027\n\n**Status**: Completed\n\n## Overview\n",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_status_complete_uppercase(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler matches Status: COMPLETE (uppercase variation)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00027-plan-completion/PLAN.md",
                "content": "# Plan 00027\n\n**Status**: COMPLETE\n\n## Overview\n",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_status_complete_lowercase(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler matches Status: complete (lowercase variation)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00027-plan-completion/PLAN.md",
                "content": "# Plan 00027\n\n**Status**: complete\n\n## Overview\n",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_new_string_with_status_complete_date(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler matches Edit with new_string containing complete with date."""
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "old_string": "**Status**: In Progress",
                "new_string": "**Status**: Complete (2026-02-06)",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_five_digit_plan_number(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler matches plan directories with 5-digit plan numbers."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00001-first-plan/PLAN.md",
                "content": "# Plan 00001\n\n**Status**: Complete\n\n## Overview\n",
            },
        }
        assert handler.matches(hook_input) is True

    # ===== matches() negative tests =====

    def test_does_not_match_file_in_completed_directory(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler does NOT trigger for files already in Completed/ directory."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/Completed/00014-eliminate-cwd/PLAN.md",
                "content": "# Plan 00014\n\n**Status**: Complete\n\n## Overview\n",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_non_plan_md_file(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler does NOT trigger for non-PLAN.md files in plan directory."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/analysis.md",
                "content": "# Analysis\n\n**Status**: Complete\n",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_complete_in_body_only(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler does NOT trigger when 'complete' appears only in body text."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "content": (
                    "# Plan 00014\n\n"
                    "**Status**: In Progress\n\n"
                    "## Overview\n\n"
                    "This plan is nearly complete and should be done soon.\n"
                ),
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_readme_edits(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler does NOT trigger for README.md edits."""
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/README.md",
                "old_string": "Active Plans",
                "new_string": "**Status**: Complete",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_non_write_edit_tool(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler does NOT trigger for Bash tool."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "cat CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_read_tool(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler does NOT trigger for Read tool."""
        hook_input: dict[str, Any] = {
            "tool_name": "Read",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_plan_md_outside_plan_directory(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler does NOT trigger for PLAN.md outside CLAUDE/Plan/ directory."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/docs/PLAN.md",
                "content": "# Plan\n\n**Status**: Complete\n",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_write_without_status_complete(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler does NOT trigger when writing PLAN.md without complete status."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "content": "# Plan 00014\n\n**Status**: In Progress\n\n## Overview\n",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_edit_without_status_complete(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler does NOT trigger for Edit without complete in new_string."""
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "old_string": "**Status**: Not Started",
                "new_string": "**Status**: In Progress",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_missing_file_path(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler does NOT trigger when file_path is missing."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "content": "**Status**: Complete",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_empty_tool_input(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler does NOT trigger with empty tool_input."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False

    # ===== handle() tests =====

    def test_handle_returns_allow_decision(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler returns ALLOW decision (advisory, non-blocking)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "content": "# Plan 00014\n\n**Status**: Complete\n",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_returns_context(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler returns advisory text in context list (not empty)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "content": "# Plan 00014\n\n**Status**: Complete\n",
            },
        }
        result = handler.handle(hook_input)
        assert result.context
        assert len(result.context[0]) > 0

    def test_handle_includes_git_mv_command(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler context includes correct git mv command with folder name."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "content": "# Plan 00014\n\n**Status**: Complete\n",
            },
        }
        result = handler.handle(hook_input)
        assert "git mv" in result.context[0]
        assert "00014-eliminate-cwd" in result.context[0]
        assert "CLAUDE/Plan/Completed/" in result.context[0]

    def test_handle_mentions_readme_update(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler context mentions README.md update."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "content": "# Plan 00014\n\n**Status**: Complete\n",
            },
        }
        result = handler.handle(hook_input)
        assert "README.md" in result.context[0]

    def test_handle_mentions_plan_statistics(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler context mentions plan statistics update."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "content": "# Plan 00014\n\n**Status**: Complete\n",
            },
        }
        result = handler.handle(hook_input)
        assert "statistic" in result.context[0].lower()

    def test_handle_extracts_correct_folder_for_different_plans(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler extracts correct folder name for different plan paths."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00027-plan-completion-move-advisor/PLAN.md",
                "content": "# Plan 00027\n\n**Status**: Complete\n",
            },
        }
        result = handler.handle(hook_input)
        assert "00027-plan-completion-move-advisor" in result.context[0]

    def test_handle_works_with_edit_tool(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Handler works correctly when triggered via Edit tool."""
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "old_string": "**Status**: In Progress",
                "new_string": "**Status**: Complete (2026-02-06)",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "git mv" in result.context[0]
        assert "00014-eliminate-cwd" in result.context[0]

    # ===== Acceptance tests =====

    def test_get_acceptance_tests_returns_non_empty(
        self, handler: PlanCompletionAdvisorHandler
    ) -> None:
        """Handler provides at least one acceptance test."""
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 1

    def test_handle_uses_context_not_guidance(self, handler: PlanCompletionAdvisorHandler) -> None:
        """Regression test: advisory MUST be returned as context, not guidance.

        Bug: PlanCompletionAdvisorHandler returned guidance=... but Claude Code only
        surfaces additionalContext (context list) in system-reminders for PreToolUse
        events. guidance is silently ignored, making the advisory invisible.

        Fix: return context=[guidance_text] so advisory appears in system-reminders.
        """
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00014-eliminate-cwd/PLAN.md",
                "content": "# Plan 00014\n\n**Status**: Complete\n",
            },
        }
        result = handler.handle(hook_input)
        assert result.context, "Advisory must be in context list (shown as additionalContext)"
        assert result.guidance is None, "guidance field is not shown in PreToolUse system-reminders"
        assert any("git mv" in c for c in result.context), "Context must contain 'git mv'"
        assert any("README" in c for c in result.context), "Context must contain 'README'"
