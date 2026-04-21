"""Tests for GhPrCommentsHandler."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.gh_pr_comments import (
    GhPrCommentsHandler,
)


class TestGhPrCommentsHandler:
    """Tests for GhPrCommentsHandler."""

    @pytest.fixture
    def handler(self) -> GhPrCommentsHandler:
        """Create handler instance."""
        return GhPrCommentsHandler()

    # ==========================================================================
    # MATCHES TESTS - should block (missing --comments)
    # ==========================================================================

    def test_matches_basic_gh_pr_view(self, handler: GhPrCommentsHandler) -> None:
        """Should match basic gh pr view without --comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 123"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_with_repo_flag(self, handler: GhPrCommentsHandler) -> None:
        """Should match gh pr view with --repo flag but no --comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 227 --repo owner/repo"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_with_json_flag_without_comments(self, handler: GhPrCommentsHandler) -> None:
        """Should match gh pr view with --json but no comments field."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 123 --json title,body"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_with_web_flag(self, handler: GhPrCommentsHandler) -> None:
        """Should match gh pr view --web without --comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 123 --web"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_with_repo_before_number(self, handler: GhPrCommentsHandler) -> None:
        """Should match when --repo comes before the PR number."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view --repo owner/repo 42"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_gh_pr_view_without_number(self, handler: GhPrCommentsHandler) -> None:
        """Should match `gh pr view` (current branch PR) without --comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view"},
        }
        assert handler.matches(hook_input) is True

    # ==========================================================================
    # NOT MATCHES TESTS - should allow (has --comments or not gh pr view)
    # ==========================================================================

    def test_not_matches_with_comments_flag(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match when --comments is already present."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 123 --comments"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_with_comments_and_repo(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match when --comments is present with other flags."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 227 --repo owner/repo --comments"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_with_json_including_comments(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match when --json includes comments field."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 19 --json title,body,comments"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_with_json_comments_first(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match when --json includes comments field (different order)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 19 --json comments,title,body"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_with_json_piped_to_jq(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match when --json with comments is piped to jq."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 19 --json title,body,comments | jq '.'"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_gh_pr_list(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match gh pr list commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr list --repo owner/repo"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_gh_pr_create(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match gh pr create commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr create --title 'Bug fix'"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_gh_pr_checks(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match gh pr checks commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr checks 123"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_gh_pr_diff(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match gh pr diff commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr diff 123"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_gh_issue_view(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match gh issue view commands (covered by sibling handler)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue view 456"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_non_bash_tool(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match non-Bash tools."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/gh pr view"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_empty_command(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match when command is empty."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": ""},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_missing_command(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match when command key is missing."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_unrelated_gh_command(self, handler: GhPrCommentsHandler) -> None:
        """Should NOT match unrelated gh commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh repo clone owner/repo"},
        }
        assert handler.matches(hook_input) is False

    # ==========================================================================
    # HANDLE TESTS - verify blocking behavior
    # ==========================================================================

    def test_handle_blocks_with_deny(self, handler: GhPrCommentsHandler) -> None:
        """Should return DENY decision when blocking."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 123"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_provides_reason(self, handler: GhPrCommentsHandler) -> None:
        """Should provide clear reason for blocking."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 123"},
        }
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert "--comments" in result.reason
        assert "gh pr view 123 --comments" in result.reason

    def test_handle_suggests_corrected_command(self, handler: GhPrCommentsHandler) -> None:
        """Should suggest the corrected command with --comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 227 --repo BallicomDev/product-data-api"},
        }
        result = handler.handle(hook_input)
        expected_suggestion = "gh pr view 227 --repo BallicomDev/product-data-api --comments"
        assert result.reason is not None
        assert expected_suggestion in result.reason

    def test_handle_explains_why_comments_needed(self, handler: GhPrCommentsHandler) -> None:
        """Should explain why comments are important."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 42"},
        }
        result = handler.handle(hook_input)
        assert result.reason is not None
        lower = result.reason.lower()
        assert "review" in lower or "context" in lower or "discussion" in lower

    def test_handle_suggests_adding_comments_to_json_fields(
        self, handler: GhPrCommentsHandler
    ) -> None:
        """Should suggest adding 'comments' to --json fields rather than appending --comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 19 --json title,body"},
        }
        result = handler.handle(hook_input)
        expected_suggestion = "gh pr view 19 --json title,body,comments"
        assert result.reason is not None
        assert expected_suggestion in result.reason

    def test_handle_suggests_adding_comments_to_json_with_pipe(
        self, handler: GhPrCommentsHandler
    ) -> None:
        """Should suggest adding 'comments' to --json fields even when piped."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 19 --json title,body | jq '.'"},
        }
        result = handler.handle(hook_input)
        expected_suggestion = "gh pr view 19 --json title,body,comments | jq '.'"
        assert result.reason is not None
        assert expected_suggestion in result.reason

    def test_handle_allows_when_no_command(self, handler: GhPrCommentsHandler) -> None:
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

    def test_handler_name(self, handler: GhPrCommentsHandler) -> None:
        """Should have correct handler name."""
        assert handler.name == "require-gh-pr-comments"

    def test_handler_priority(self, handler: GhPrCommentsHandler) -> None:
        """Should have workflow priority (40-50 range)."""
        assert 40 <= handler.priority <= 50

    def test_handler_is_terminal(self, handler: GhPrCommentsHandler) -> None:
        """Should be a terminal handler (stops dispatch chain)."""
        assert handler.terminal is True

    def test_handler_tags(self, handler: GhPrCommentsHandler) -> None:
        """Should have appropriate tags."""
        assert "workflow" in handler.tags
        assert "github" in handler.tags
        assert "blocking" in handler.tags

    # ==========================================================================
    # CLAUDE.MD GUIDANCE TESTS
    # ==========================================================================

    def test_get_claude_md_returns_guidance(self, handler: GhPrCommentsHandler) -> None:
        """Should return non-None guidance for CLAUDE.md injection."""
        guidance = handler.get_claude_md()
        assert guidance is not None

    def test_get_claude_md_mentions_comments_flag(self, handler: GhPrCommentsHandler) -> None:
        """Guidance should explain the --comments requirement."""
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "--comments" in guidance

    def test_get_claude_md_mentions_json_alternative(self, handler: GhPrCommentsHandler) -> None:
        """Guidance should mention --json with comments field as alternative."""
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "--json" in guidance

    def test_get_claude_md_mentions_pr(self, handler: GhPrCommentsHandler) -> None:
        """Guidance should refer to gh pr view specifically."""
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "gh pr view" in guidance
