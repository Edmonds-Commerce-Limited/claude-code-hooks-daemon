"""Tests for PlanTimeEstimatesHandler.

Comprehensive test coverage for blocking time estimates in plans.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_time_estimates import (
    PlanTimeEstimatesHandler,
)


class TestPlanTimeEstimatesHandler:
    """Test suite for PlanTimeEstimatesHandler."""

    @pytest.fixture
    def handler(self) -> PlanTimeEstimatesHandler:
        """Create handler instance."""
        return PlanTimeEstimatesHandler()

    # Tests for matches() method - Write operations

    def test_matches_write_with_estimated_effort_bold(
        self, handler: PlanTimeEstimatesHandler
    ) -> None:
        """Handler matches write with bold estimated effort."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "content": "**Estimated Effort**: 2 hours",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_estimated_effort_plain(
        self, handler: PlanTimeEstimatesHandler
    ) -> None:
        """Handler matches write with plain estimated effort."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "content": "Estimated Effort: 3 days",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_estimated_time(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler matches write with estimated time."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "content": "Estimated time: 30 minutes",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_total_estimated_time(
        self, handler: PlanTimeEstimatesHandler
    ) -> None:
        """Handler matches write with total estimated time."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "content": "**Total Estimated Time**: 1 week",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_target_completion_date(
        self, handler: PlanTimeEstimatesHandler
    ) -> None:
        """Handler matches write with target completion date."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "content": "**Target Completion**: 2026-02-15",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_completion_date_plain(
        self, handler: PlanTimeEstimatesHandler
    ) -> None:
        """Handler matches write with plain completion date."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "content": "Completion: 2026-03-01",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_numeric_duration(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler matches write with numeric duration (hours/days/etc)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "content": "This task should take 4 hours to complete.",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_eta(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler matches write with ETA."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "content": "ETA: 2 weeks",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_deadline(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler matches write with deadline."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "content": "deadline: 30 days",
            },
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_write_without_estimates(
        self, handler: PlanTimeEstimatesHandler
    ) -> None:
        """Handler does not match write without time estimates."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "content": "This is a plan without time estimates.",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_write_non_plan_file(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler does not match write to non-plan files."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/main.py",
                "content": "Estimated time: 2 hours",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_write_non_md_file(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler does not match write to non-markdown files."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/config.json",
                "content": "Estimated time: 2 hours",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_write_empty_content(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler does not match write with empty content."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "content": "",
            },
        }
        assert handler.matches(hook_input) is False

    # Tests for matches() method - Edit operations

    def test_matches_edit_with_time_estimate(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler matches edit with time estimate in new_string."""
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "old_string": "Original text",
                "new_string": "**Estimated Effort**: 5 hours",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_case_insensitive(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler matches edit with case-insensitive patterns."""
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "old_string": "text",
                "new_string": "ESTIMATED TIME: 10 HOURS",
            },
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_edit_without_estimates(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler does not match edit without time estimates."""
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "old_string": "old text",
                "new_string": "new text without estimates",
            },
        }
        assert handler.matches(hook_input) is False

    # Tests for matches() method - edge cases

    def test_does_not_match_read_tool(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler does not match Read tool."""
        hook_input: dict[str, Any] = {
            "tool_name": "Read",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_bash_tool(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler does not match Bash tool."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'Estimated time: 2 hours'"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_missing_file_path(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler does not match when file_path is missing."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"content": "Estimated time: 2 hours"},
        }
        assert handler.matches(hook_input) is False

    # Tests for handle() method

    def test_handle_denies_time_estimates(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler denies time estimates with appropriate message."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/001-test/PLAN.md",
                "content": "**Estimated Effort**: 2 hours",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "Time estimates not allowed" in result.reason
        assert "/workspace/CLAUDE/Plan/001-test/PLAN.md" in result.reason

    def test_handle_explains_why_blocked(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler explanation includes reasoning."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/002-test/PLAN.md",
                "content": "Target Completion: 2026-02-01",
            },
        }
        result = handler.handle(hook_input)
        assert "WHY:" in result.reason
        assert "false expectations" in result.reason
        assert "CORRECT APPROACH:" in result.reason

    def test_handle_provides_alternatives(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler provides alternative approach guidance."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/003-test/PLAN.md",
                "content": "ETA: 3 weeks",
            },
        }
        result = handler.handle(hook_input)
        assert "Break work into concrete tasks" in result.reason
        assert "Let user decide scheduling" in result.reason
        assert "Focus on actionable work" in result.reason

    # Tests for handler metadata

    def test_handler_has_correct_name(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler has correct name."""
        assert handler.name == "block-plan-time-estimates"

    def test_handler_has_correct_priority(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler has correct priority."""
        assert handler.priority == 40

    def test_handler_has_correct_tags(self, handler: PlanTimeEstimatesHandler) -> None:
        """Handler has correct tags."""
        assert "workflow" in handler.tags
        assert "planning" in handler.tags
        assert "advisory" in handler.tags
        assert "non-terminal" in handler.tags

    # Tests for ESTIMATE_PATTERNS constant

    def test_estimate_patterns_constant_exists(self, handler: PlanTimeEstimatesHandler) -> None:
        """ESTIMATE_PATTERNS constant exists and is populated."""
        assert hasattr(handler, "ESTIMATE_PATTERNS")
        assert len(handler.ESTIMATE_PATTERNS) > 0

    def test_estimate_patterns_includes_common_patterns(
        self, handler: PlanTimeEstimatesHandler
    ) -> None:
        """ESTIMATE_PATTERNS includes common time estimate patterns."""
        patterns_str = " ".join(handler.ESTIMATE_PATTERNS)
        assert "Estimated" in patterns_str
        assert "hours?" in patterns_str
        assert "minutes?" in patterns_str
        assert "days?" in patterns_str
        assert "weeks?" in patterns_str
