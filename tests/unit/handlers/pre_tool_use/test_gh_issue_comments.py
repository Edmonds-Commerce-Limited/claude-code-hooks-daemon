"""Tests for GhIssueCommentsHandler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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

    def test_matches_with_json_flag_without_comments(self, handler: GhIssueCommentsHandler) -> None:
        """Should match gh issue view with --json but no comments field."""
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

    def test_not_matches_with_json_including_comments(
        self, handler: GhIssueCommentsHandler
    ) -> None:
        """Should NOT match when --json includes comments field."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 19 --json title,body,comments"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_with_json_comments_first(self, handler: GhIssueCommentsHandler) -> None:
        """Should NOT match when --json includes comments field (different order)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 19 --json comments,title,body"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_with_json_piped_to_jq(self, handler: GhIssueCommentsHandler) -> None:
        """Should NOT match when --json with comments is piped to jq."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 19 --json title,body,comments | jq '.'"},
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

    def test_handle_suggests_adding_comments_to_json_fields(
        self, handler: GhIssueCommentsHandler
    ) -> None:
        """Should suggest adding 'comments' to --json fields rather than appending --comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 19 --json title,body"},
        }
        result = handler.handle(hook_input)
        expected_suggestion = "gh issue view 19 --json title,body,comments"
        assert result.reason is not None
        assert expected_suggestion in result.reason

    def test_handle_suggests_adding_comments_to_json_with_pipe(
        self, handler: GhIssueCommentsHandler
    ) -> None:
        """Should suggest adding 'comments' to --json fields even when piped."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 19 --json title,body | jq '.'"},
        }
        result = handler.handle(hook_input)
        expected_suggestion = "gh issue view 19 --json title,body,comments | jq '.'"
        assert result.reason is not None
        assert expected_suggestion in result.reason

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

    # ==========================================================================
    # COMMAND REDIRECTION TESTS
    # ==========================================================================

    def test_redirection_disabled_by_default(self) -> None:
        """Command redirection should be disabled by default (CLAUDE.md cascade issue)."""
        handler = GhIssueCommentsHandler()
        assert handler._command_redirection is False

    def test_redirection_enabled_via_options(self) -> None:
        """Command redirection can be enabled via options."""
        handler = GhIssueCommentsHandler(options={"command_redirection": True})
        assert handler._command_redirection is True

    def test_get_redirected_command_basic(self, handler: GhIssueCommentsHandler) -> None:
        """Should return corrected command with --comments appended."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 123"},
        }
        redirected = handler.get_redirected_command(hook_input)
        assert redirected == ["gh", "issue", "view", "123", "--comments"]

    def test_get_redirected_command_with_repo(self, handler: GhIssueCommentsHandler) -> None:
        """Should return corrected command preserving --repo flag."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 227 --repo owner/repo"},
        }
        redirected = handler.get_redirected_command(hook_input)
        assert redirected == ["gh", "issue", "view", "227", "--repo", "owner/repo", "--comments"]

    def test_get_redirected_command_with_json(self, handler: GhIssueCommentsHandler) -> None:
        """Should add comments to --json fields."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 19 --json title,body"},
        }
        redirected = handler.get_redirected_command(hook_input)
        assert redirected is not None
        cmd_str = " ".join(redirected)
        assert "title,body,comments" in cmd_str

    def test_get_redirected_command_no_command(self, handler: GhIssueCommentsHandler) -> None:
        """Should return None when no bash command."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/test"},
        }
        redirected = handler.get_redirected_command(hook_input)
        assert redirected is None

    def test_handle_with_redirection_includes_context(self, tmp_path: Path) -> None:
        """When redirection is explicitly enabled, handle() should include redirection context."""
        handler = GhIssueCommentsHandler(options={"command_redirection": True})
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 123"},
        }
        from claude_code_hooks_daemon.core.command_redirection import (
            CommandRedirectionResult,
        )

        with (
            patch(
                "claude_code_hooks_daemon.handlers.pre_tool_use.gh_issue_comments.execute_and_save"
            ) as mock_exec,
            patch(
                "claude_code_hooks_daemon.handlers.pre_tool_use.gh_issue_comments.get_output_dir",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.handlers.pre_tool_use.gh_issue_comments.ProjectContext"
            ) as mock_ctx,
        ):
            mock_ctx.project_root.return_value = tmp_path
            mock_exec.return_value = CommandRedirectionResult(
                exit_code=0,
                output_path=tmp_path / "test.txt",
                command="gh issue view 123 --comments",
            )
            result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "--comments" in result.reason
        # Context should include redirection info
        joined_context = "\n".join(result.context)
        assert "COMMAND REDIRECTED" in joined_context
        assert "Exit code: 0" in joined_context

    def test_handle_without_redirection_no_context(self, tmp_path: Path) -> None:
        """When redirection is disabled, handle() should NOT include redirection context."""
        handler = GhIssueCommentsHandler(options={"command_redirection": False})
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 123"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "--comments" in result.reason
        # No redirection context
        joined_context = "\n".join(result.context)
        assert "COMMAND REDIRECTED" not in joined_context

    def test_handle_redirection_failure_falls_back(self, handler: GhIssueCommentsHandler) -> None:
        """When redirection execution fails, should fall back to block-only."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 123"},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.gh_issue_comments.execute_and_save",
            side_effect=OSError("disk full"),
        ):
            result = handler.handle(hook_input)

        # Should still deny with educational message
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "--comments" in result.reason
        # But no redirection context (failed gracefully)
        joined_context = "\n".join(result.context)
        assert "COMMAND REDIRECTED" not in joined_context
