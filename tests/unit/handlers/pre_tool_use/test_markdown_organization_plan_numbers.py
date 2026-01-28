"""Tests for markdown organization handler plan number format support.

Tests that both 3-digit (legacy) and 5-digit (new) plan number formats are supported.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization import (
    MarkdownOrganizationHandler,
)


class TestPlanNumberFormats:
    """Test that handler supports 3 or more digit plan numbers (flexible format)."""

    @pytest.fixture
    def handler(self, tmp_path: Path) -> MarkdownOrganizationHandler:
        """Create handler with planning mode disabled (testing manual plan creation)."""
        handler = MarkdownOrganizationHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = None  # Disabled - testing manual creation
        return handler

    def test_allows_3_digit_plan_numbers(self, handler: MarkdownOrganizationHandler) -> None:
        """Test that 3-digit plan numbers are allowed (legacy format)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/002-fix-silent-handler-failures/PLAN.md",
                "content": "# Plan 002",
            },
        }

        # Should NOT match (returns False = allowed)
        assert not handler.matches(hook_input), "3-digit plan numbers should be allowed"

    def test_allows_5_digit_plan_numbers(self, handler: MarkdownOrganizationHandler) -> None:
        """Test that 5-digit plan numbers are allowed (current format)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Plan/00007-handler-naming-convention-fix/PLAN.md",
                "content": "# Plan 007",
            },
        }

        # Should NOT match (returns False = allowed)
        assert not handler.matches(hook_input), "5-digit plan numbers should be allowed"

    def test_allows_flexible_digit_count(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Test that handler allows 3 or more digits (flexible)."""
        test_cases = [
            "CLAUDE/Plan/001-three-digits/PLAN.md",
            "CLAUDE/Plan/0042-four-digits/PLAN.md",
            "CLAUDE/Plan/00123-five-digits/PLAN.md",
            "CLAUDE/Plan/001234-six-digits/PLAN.md",
            "CLAUDE/Plan/99999-five-nines/PLAN.md",
            "CLAUDE/Plan/000001-six-zeros-one/PLAN.md",
        ]

        for file_path in test_cases:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": f"/workspace/{file_path}",
                    "content": "# Test Plan",
                },
            }

            assert not handler.matches(hook_input), f"{file_path} should be allowed"

    def test_rejects_insufficient_digits(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Test that plan folders with fewer than 3 digits are rejected."""
        invalid_cases = [
            "CLAUDE/Plan/1-one-digit/PLAN.md",
            "CLAUDE/Plan/12-two-digits/PLAN.md",
            "CLAUDE/Plan/99-two-nines/PLAN.md",
        ]

        for file_path in invalid_cases:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": f"/workspace/{file_path}",
                    "content": "# Test Plan",
                },
            }

            assert handler.matches(hook_input), f"{file_path} should be rejected (< 3 digits)"

    def test_rejects_non_numeric_plan_folders(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Test that plan folders without numbers are rejected."""
        invalid_cases = [
            "CLAUDE/Plan/no-number/PLAN.md",
            "CLAUDE/Plan/plan-name/PLAN.md",
            "CLAUDE/Plan/ABC-plan/PLAN.md",
        ]

        for file_path in invalid_cases:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": f"/workspace/{file_path}",
                    "content": "# Test Plan",
                },
            }

            assert handler.matches(hook_input), f"{file_path} should be rejected"

    def test_plan_number_pattern_examples(self, handler: MarkdownOrganizationHandler) -> None:
        """Test specific plan number patterns used in the codebase."""
        # Real examples from the codebase
        real_plans = [
            "CLAUDE/Plan/002-fix-silent-handler-failures/PLAN.md",
            "CLAUDE/Plan/003-planning-mode-project-integration/PLAN.md",
            "CLAUDE/Plan/00004-final-workspace-test/PLAN.md",
            "CLAUDE/Plan/00005-clean-final-test/PLAN.md",
            "CLAUDE/Plan/00006-eager-popping-nebula/PLAN.md",
            "CLAUDE/Plan/00007-handler-naming-convention-fix/PLAN.md",
        ]

        for file_path in real_plans:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": f"/workspace/{file_path}",
                    "content": "# Test Plan",
                },
            }

            # Should NOT match (returns False = allowed)
            result = handler.matches(hook_input)
            assert not result, (
                f"{file_path} should be allowed\n"
                f"This is a real plan folder from the codebase.\n"
                f"Handler should support both 3-digit and 5-digit formats."
            )
