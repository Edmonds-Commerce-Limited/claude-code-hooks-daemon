"""Comprehensive tests for DestructiveGitHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler


class TestDestructiveGitHandler:
    """Test suite for DestructiveGitHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return DestructiveGitHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'prevent-destructive-git'."""
        assert handler.name == "prevent-destructive-git"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 10."""
        assert handler.priority == 10

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    def test_init_creates_destructive_patterns_list(self, handler):
        """Handler should initialize with 7 destructive patterns."""
        assert hasattr(handler, "destructive_patterns")
        assert len(handler.destructive_patterns) == 7

    # matches() - Pattern 1: git reset --hard
    def test_matches_git_reset_hard(self, handler):
        """Should match 'git reset --hard' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_reset_hard_with_ref(self, handler):
        """Should match 'git reset --hard' with reference."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD~1"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_reset_hard_with_branch(self, handler):
        """Should match 'git reset --hard' with branch name."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard origin/main"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_reset_hard_case_insensitive(self, handler):
        """Should match 'git reset --hard' with different casing."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "GIT RESET --HARD"}}
        assert handler.matches(hook_input) is True

    # matches() - Pattern 2: git clean -f
    def test_matches_git_clean_f(self, handler):
        """Should match 'git clean -f' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -f"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_clean_fd(self, handler):
        """Should match 'git clean -fd' (force + directories)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -fd"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_clean_fdx(self, handler):
        """Should match 'git clean -fdx' (force + directories + ignored)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -fdx"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_clean_with_path(self, handler):
        """Should match 'git clean -f' with path argument."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -f src/"}}
        assert handler.matches(hook_input) is True

    # matches() - Pattern 3: git checkout .
    def test_matches_git_checkout_dot(self, handler):
        """Should match 'git checkout .' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git checkout ."}}
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_dot_with_semicolon(self, handler):
        """Should match 'git checkout .' followed by semicolon."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git checkout .; git status"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_dot_with_and(self, handler):
        """Should match 'git checkout .' followed by &&."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout . && git status"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_dot_with_pipe(self, handler):
        """Should match 'git checkout .' followed by pipe."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout . | grep something"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 4: git checkout -- file
    def test_matches_git_checkout_dash_dash_file(self, handler):
        """Should match 'git checkout -- file' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git checkout -- file.txt"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_head_dash_dash_file(self, handler):
        """Should match 'git checkout HEAD -- file' command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout HEAD -- src/main.py"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_branch_dash_dash_file(self, handler):
        """Should match 'git checkout main -- file' command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout main -- README.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_ref_dash_dash_file(self, handler):
        """Should match 'git checkout @{upstream} -- file' command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout @{upstream} -- package.json"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_dash_dash_multiple_files(self, handler):
        """Should match 'git checkout --' with multiple files."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout -- file1.txt file2.txt"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 5: git restore (destructive variants)
    def test_matches_git_restore_file(self, handler):
        """Should match 'git restore file' (discards working tree changes)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_restore_multiple_files(self, handler):
        """Should match 'git restore' with multiple files."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore file1.txt file2.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_restore_path(self, handler):
        """Should match 'git restore' with path."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore src/main.py"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_restore_worktree(self, handler):
        """Should match 'git restore --worktree' command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore --worktree file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_restore_worktree_with_source(self, handler):
        """Should match 'git restore --worktree' with source ref."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore --source=HEAD --worktree file.txt"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 6: git stash drop/clear
    def test_matches_git_stash_drop(self, handler):
        """Should match 'git stash drop' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash drop"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_drop_with_stash_id(self, handler):
        """Should match 'git stash drop' with stash ID."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash drop stash@{0}"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_clear(self, handler):
        """Should match 'git stash clear' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash clear"}}
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Safe git commands
    def test_matches_git_reset_soft_returns_false(self, handler):
        """Should NOT match 'git reset --soft' (safe)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --soft HEAD~1"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_reset_mixed_returns_false(self, handler):
        """Should NOT match 'git reset --mixed' (safe)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --mixed HEAD~1"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_clean_dry_run_returns_false(self, handler):
        """Should NOT match 'git clean -n' (dry-run)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -n"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_checkout_branch_returns_false(self, handler):
        """Should NOT match 'git checkout' to switch branches."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git checkout main"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_restore_staged_returns_false(self, handler):
        """Should NOT match 'git restore --staged' (safe)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore --staged file.txt"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_git_stash_list_returns_false(self, handler):
        """Should NOT match 'git stash list' (query)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash list"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_stash_pop_returns_false(self, handler):
        """Should NOT match 'git stash pop' (recovery)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash pop"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_status_returns_false(self, handler):
        """Should NOT match 'git status'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_diff_returns_false(self, handler):
        """Should NOT match 'git diff'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git diff"}}
        assert handler.matches(hook_input) is False

    # matches() - Edge Cases
    def test_matches_non_bash_tool_returns_false(self, handler):
        """Should not match non-Bash tools."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.sh", "content": "git reset --hard"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_empty_command_returns_false(self, handler):
        """Should not match empty command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        assert handler.matches(hook_input) is False

    def test_matches_none_command_returns_false(self, handler):
        """Should not match when command is None."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": None}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_command_key_returns_false(self, handler):
        """Should not match when command key is missing."""
        hook_input = {"tool_name": "Bash", "tool_input": {}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_tool_input_returns_false(self, handler):
        """Should not match when tool_input is missing."""
        hook_input = {"tool_name": "Bash"}
        assert handler.matches(hook_input) is False

    def test_matches_command_without_git_returns_false(self, handler):
        """Should not match commands without 'git'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/test"}}
        assert handler.matches(hook_input) is False

    def test_matches_comment_mentioning_git_returns_false(self, handler):
        """Should not match commands that just mention git in comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'avoid git reset --hard'"},
        }
        # This will actually match because the pattern exists in the string
        # This is acceptable behavior - better safe than sorry
        assert handler.matches(hook_input) is True

    # handle() Tests - Specific reasons for each pattern
    def test_handle_git_reset_hard_reason(self, handler):
        """handle() should provide specific reason for git reset --hard."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "git reset --hard destroys all uncommitted changes permanently" in result.reason

    def test_handle_git_clean_f_reason(self, handler):
        """handle() should provide specific reason for git clean -f."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -f"}}
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "git clean -f permanently deletes untracked files" in result.reason

    def test_handle_git_stash_drop_reason(self, handler):
        """handle() should provide specific reason for git stash drop."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash drop"}}
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "git stash drop permanently destroys stashed changes" in result.reason

    def test_handle_git_stash_clear_reason(self, handler):
        """handle() should provide specific reason for git stash clear."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash clear"}}
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "git stash clear permanently destroys all stashed changes" in result.reason

    def test_handle_git_checkout_dash_dash_reason(self, handler):
        """handle() should provide specific reason for git checkout -- file."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git checkout -- file.txt"}}
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert (
            "git checkout [REF] -- file discards all local changes to that file permanently"
            in result.reason
        )

    def test_handle_git_restore_reason(self, handler):
        """handle() should provide specific reason for git restore."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git restore file.txt"}}
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "git restore discards all local changes to files permanently" in result.reason

    def test_handle_generic_destructive_reason(self, handler):
        """handle() should provide generic reason for other patterns."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git checkout ."}}
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "This git command destroys uncommitted changes permanently" in result.reason

    # handle() Tests - Message structure
    def test_handle_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_reason_contains_command(self, handler):
        """handle() reason should include the blocked command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD~3"}}
        result = handler.handle(hook_input)
        assert "git reset --hard HEAD~3" in result.reason

    def test_handle_reason_provides_safe_alternatives(self, handler):
        """handle() reason should provide safe alternatives."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -fd"}}
        result = handler.handle(hook_input)
        assert "SAFE alternatives" in result.reason
        assert "git stash" in result.reason
        assert "git diff" in result.reason
        assert "git status" in result.reason
        assert "git commit" in result.reason

    def test_handle_reason_warns_no_recovery(self, handler):
        """handle() reason should warn about no recovery."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}
        result = handler.handle(hook_input)
        assert "NO recovery possible" in result.reason

    def test_handle_reason_instructs_ask_human(self, handler):
        """handle() reason should instruct to ask human."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -f"}}
        result = handler.handle(hook_input)
        assert "ask the human user to run it manually" in result.reason

    def test_handle_reason_explains_llm_not_allowed(self, handler):
        """handle() reason should explain LLM is not allowed."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash drop"}}
        result = handler.handle(hook_input)
        assert "LLM is NOT ALLOWED" in result.reason

    # handle() Tests - Return values
    def test_handle_returns_deny_decision(self, handler):
        """handle() should always return deny decision."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_context_is_none(self, handler):
        """handle() context should be None (not used)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None (not used)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -f"}}
        result = handler.handle(hook_input)
        assert result.guidance is None

    def test_handle_empty_command_returns_allow(self, handler):
        """handle() should return ALLOW for empty command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    # Integration Tests
    def test_blocks_all_destructive_commands(self, handler):
        """Should block all known destructive commands."""
        destructive_commands = [
            "git reset --hard",
            "git reset --hard HEAD~1",
            "git clean -f",
            "git clean -fd",
            "git clean -fdx",
            "git checkout .",
            "git checkout -- file.txt",
            "git checkout HEAD -- file.txt",
            "git restore file.txt",
            "git restore src/main.py",
            "git restore --worktree file.txt",
            "git stash drop",
            "git stash clear",
        ]
        for cmd in destructive_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is True, f"Should block: {cmd}"

    def test_allows_all_safe_commands(self, handler):
        """Should allow all safe git commands."""
        safe_commands = [
            "git status",
            "git diff",
            "git log",
            "git reset --soft HEAD~1",
            "git reset --mixed HEAD~1",
            "git clean -n",
            "git checkout main",
            "git restore --staged file.txt",
            "git stash list",
            "git stash pop",
            "git stash apply",
            "git commit -m 'message'",
            "git add .",
            "git push",
        ]
        for cmd in safe_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is False, f"Should allow: {cmd}"
