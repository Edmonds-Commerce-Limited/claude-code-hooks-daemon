"""Comprehensive tests for WorktreeFileCopyHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.worktree_file_copy import (
    WorktreeFileCopyHandler,
)


class TestWorktreeFileCopyHandler:
    """Test suite for WorktreeFileCopyHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return WorktreeFileCopyHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'prevent-worktree-file-copying'."""
        assert handler.name == "prevent-worktree-file-copying"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 15."""
        assert handler.priority == 15

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    # matches() - Positive Cases: cp command
    def test_matches_cp_from_worktree_to_src(self, handler):
        """Should match cp from worktree to src/."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp untracked/worktrees/feature-branch/src/test.py src/"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_cp_from_worktree_to_tests(self, handler):
        """Should match cp from worktree to tests/."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp untracked/worktrees/fix-bug/tests/test.py tests/"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_cp_recursive_flag(self, handler):
        """Should match cp -r from worktree."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp -r untracked/worktrees/branch/src/ src/"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Positive Cases: mv command
    def test_matches_mv_from_worktree_to_src(self, handler):
        """Should match mv from worktree to src/."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "mv untracked/worktrees/branch/src/file.py src/"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Positive Cases: rsync command
    def test_matches_rsync_from_worktree_to_src(self, handler):
        """Should match rsync from worktree to src."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rsync -av untracked/worktrees/branch/src/ src/"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_rsync_with_tests_directory(self, handler):
        """Should match rsync targeting tests directory."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rsync untracked/worktrees/branch/ tests/"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_rsync_with_config_directory(self, handler):
        """Should match rsync targeting config directory."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rsync -r untracked/worktrees/fix/ config/"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Within same worktree
    def test_matches_cp_within_same_worktree_returns_false(self, handler):
        """Should allow cp within the same worktree."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "cp untracked/worktrees/branch/src/a.py untracked/worktrees/branch/tests/"
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_different_worktrees_with_target_dirs_returns_true(self, handler):
        """Should block copying between different worktrees when target is src/tests/config."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp untracked/worktrees/feature-a/file src/"},
        }
        # From worktree to main repo src/ - should block
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: No worktrees involved
    def test_matches_cp_without_worktree_returns_false(self, handler):
        """Should not match cp without worktree paths."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "cp src/file.py backup/"}}
        assert handler.matches(hook_input) is False

    def test_matches_mv_without_worktree_returns_false(self, handler):
        """Should not match mv without worktree paths."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "mv src/old.py src/new.py"}}
        assert handler.matches(hook_input) is False

    def test_matches_rsync_without_worktree_returns_false(self, handler):
        """Should not match rsync without worktree paths."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "rsync -av src/ backup/"}}
        assert handler.matches(hook_input) is False

    # matches() - Negative Cases: Different commands
    def test_matches_ls_command_returns_false(self, handler):
        """Should not match ls command even with worktree path."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls untracked/worktrees/branch/"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_cat_command_returns_false(self, handler):
        """Should not match cat command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat untracked/worktrees/branch/README.md"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_git_command_returns_false(self, handler):
        """Should not match git commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git log untracked/worktrees/branch/"},
        }
        assert handler.matches(hook_input) is False

    # matches() - Edge Cases
    def test_matches_empty_command_returns_false(self, handler):
        """Should not match empty command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        assert handler.matches(hook_input) is False

    def test_matches_none_command_returns_false(self, handler):
        """Should not match None command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": None}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_command_key_returns_false(self, handler):
        """Should not match when command key missing."""
        hook_input = {"tool_name": "Bash", "tool_input": {}}
        assert handler.matches(hook_input) is False

    def test_matches_non_bash_tool_returns_false(self, handler):
        """Should not match non-Bash tools."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.sh",
                "content": "cp untracked/worktrees/branch/file src/",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_case_insensitive_cp(self, handler):
        """Should match CP command (case-insensitive)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "CP untracked/worktrees/branch/file src/"},
        }
        assert handler.matches(hook_input) is True

    # handle() Tests
    def test_handle_returns_deny_decision(self, handler):
        """handle() should return deny decision."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp untracked/worktrees/branch/src/file.py src/"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "mv untracked/worktrees/branch/tests/test.py tests/"},
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_reason_shows_command(self, handler):
        """handle() reason should show the blocked command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp untracked/worktrees/my-feature/src/app.py src/"},
        }
        result = handler.handle(hook_input)
        assert "cp untracked/worktrees/my-feature/src/app.py src/" in result.reason

    def test_handle_reason_explains_catastrophic_consequences(self, handler):
        """handle() reason should explain why this is catastrophic."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rsync untracked/worktrees/branch/src/ src/"},
        }
        result = handler.handle(hook_input)
        assert "CATASTROPHIC" in result.reason or "catastrophic" in result.reason

    def test_handle_reason_provides_correct_workflow(self, handler):
        """handle() reason should provide correct git workflow."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp untracked/worktrees/branch/file src/"},
        }
        result = handler.handle(hook_input)
        assert "CORRECT WORKFLOW" in result.reason
        assert "git commit" in result.reason
        assert "git merge" in result.reason

    def test_handle_reason_mentions_worktree_guide(self, handler):
        """handle() reason should reference worktree documentation."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "mv untracked/worktrees/branch/src/file src/"},
        }
        result = handler.handle(hook_input)
        assert "CLAUDE/Worktree.md" in result.reason or "Worktree" in result.reason

    def test_handle_context_is_none(self, handler):
        """handle() context should be None."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp untracked/worktrees/branch/file src/"},
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp untracked/worktrees/branch/file src/"},
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    # Integration Tests
    def test_blocks_all_copy_commands(self, handler):
        """Should block cp, mv, and rsync from worktree to main."""
        commands = [
            "cp untracked/worktrees/branch/src/file.py src/",
            "mv untracked/worktrees/branch/tests/test.py tests/",
            "rsync -av untracked/worktrees/branch/config/ config/",
        ]
        for cmd in commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is True, f"Should block: {cmd}"

    def test_allows_safe_operations_within_worktree(self, handler):
        """Should allow file operations within the same worktree."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "cp untracked/worktrees/branch/backup.py untracked/worktrees/branch/src/"
            },
        }
        assert handler.matches(hook_input) is False

    def test_allows_operations_not_involving_worktrees(self, handler):
        """Should allow normal file operations outside worktrees."""
        safe_commands = [
            "cp src/file.py backup/",
            "mv tests/old.py tests/new.py",
            "rsync -av src/ dist/",
        ]
        for cmd in safe_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is False, f"Should allow: {cmd}"
