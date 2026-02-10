"""Comprehensive tests for GitStashHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.git_stash import GitStashHandler


class TestGitStashHandler:
    """Test suite for GitStashHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return GitStashHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'block-git-stash'."""
        assert handler.name == "block-git-stash"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 20."""
        assert handler.priority == 20

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    # matches() - Positive Cases: Block stash CREATION commands
    def test_matches_git_stash_plain(self, handler):
        """Should match plain 'git stash' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_push(self, handler):
        """Should match 'git stash push' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash push"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_save(self, handler):
        """Should match 'git stash save' command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git stash save 'work in progress'"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_with_message(self, handler):
        """Should match git stash with message."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git stash -m 'temporary work'"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_with_pathspec(self, handler):
        """Should match git stash with pathspec."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash -- src/"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_push_with_options(self, handler):
        """Should match git stash push with various options."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git stash push -u -m 'message' -- file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_case_insensitive(self, handler):
        """Should match git stash with different casing."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "GIT STASH"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_with_trailing_spaces(self, handler):
        """Should match git stash with trailing whitespace."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash   "}}
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_in_command_chain(self, handler):
        """Should match git stash in command chain."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git status && git stash && git pull"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_after_semicolon(self, handler):
        """Should match git stash after semicolon."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "cd /workspace; git stash"}}
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Allow recovery/query operations
    def test_matches_git_stash_pop_returns_false(self, handler):
        """Should NOT match git stash pop (recovery operation)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash pop"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_stash_apply_returns_false(self, handler):
        """Should NOT match git stash apply (recovery operation)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash apply"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_stash_list_returns_false(self, handler):
        """Should NOT match git stash list (query operation)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash list"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_stash_show_returns_false(self, handler):
        """Should NOT match git stash show (query operation)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash show"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_stash_apply_with_stash_id_returns_false(self, handler):
        """Should NOT match git stash apply with stash ID."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash apply stash@{0}"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_stash_pop_with_index_returns_false(self, handler):
        """Should NOT match git stash pop with index."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash pop stash@{2}"}}
        assert handler.matches(hook_input) is False

    # Note: drop/clear are ALSO blocked by this handler (and DestructiveGitHandler)
    def test_matches_git_stash_drop_returns_true(self, handler):
        """git stash drop IS matched by this handler's regex."""
        # The regex matches "git stash" followed by space or end
        # So "git stash drop" matches the "git stash " part
        # DestructiveGitHandler (priority 10) would also block this
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash drop"}}
        # This handler DOES match drop (before checking for allowed subcommands)
        assert handler.matches(hook_input) is True

    # matches() - Edge Cases
    def test_matches_non_bash_tool_returns_false(self, handler):
        """Should not match non-Bash tools."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.sh", "content": "git stash"},
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
        """Should not match commands without git."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "stash some files"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_status_returns_false(self, handler):
        """Should not match other git commands."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
        assert handler.matches(hook_input) is False

    def test_matches_word_containing_stash_returns_false(self, handler):
        """Should not match words containing 'stash' but not the command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git log --grep='mustache'"}}
        assert handler.matches(hook_input) is False

    # handle() Tests
    def test_handle_returns_allow_decision(self, handler):
        """handle() should return allow decision with warning."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_context_contains_warning(self, handler):
        """handle() context should contain warning messages."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}
        result = handler.handle(hook_input)
        assert len(result.context) > 0
        assert any("WARNING" in msg for msg in result.context)

    def test_handle_guidance_explains_why_risky(self, handler):
        """handle() guidance should explain why stash is risky."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash push"}}
        result = handler.handle(hook_input)
        assert result.guidance is not None
        assert "WHY" in result.guidance
        assert "lost" in result.guidance or "forgotten" in result.guidance

    def test_handle_guidance_provides_alternatives(self, handler):
        """handle() guidance should provide safe alternatives."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}
        result = handler.handle(hook_input)
        assert result.guidance is not None
        assert "SAFE ALTERNATIVES" in result.guidance or "ALTERNATIVES" in result.guidance
        assert "git commit" in result.guidance

    def test_handle_guidance_mentions_worktree_issues(self, handler):
        """handle() guidance should mention worktree-related problems."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}
        result = handler.handle(hook_input)
        assert result.guidance is not None
        assert "worktree" in result.guidance.lower()

    def test_handle_guidance_suggests_asking_human(self, handler):
        """handle() guidance should suggest asking human for help."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}
        result = handler.handle(hook_input)
        assert result.guidance is not None
        assert "human" in result.guidance.lower()

    def test_handle_allows_but_warns(self, handler):
        """handle() should allow but provide strong warnings."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}
        result = handler.handle(hook_input)
        # Should allow with guidance, not deny
        assert result.decision == "allow"
        assert result.guidance is not None
        assert len(result.context) > 0

    # Integration Tests
    def test_allows_recovery_workflow(self, handler):
        """Should allow complete recovery workflow."""
        recovery_commands = [
            "git stash list",
            "git stash show",
            "git stash show stash@{0}",
            "git stash apply",
            "git stash apply stash@{1}",
            "git stash pop",
        ]
        for cmd in recovery_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is False, f"Should allow: {cmd}"

    def test_blocks_all_creation_variants(self, handler):
        """Should block all stash creation variants."""
        creation_commands = [
            "git stash",
            "git stash push",
            "git stash save",
            "git stash -m 'message'",
            "git stash push -m 'message'",
            "git stash save 'message'",
            "git stash -- file.txt",
            "git stash push -u",
        ]
        for cmd in creation_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is True, f"Should block: {cmd}"

    # Mode Configuration Tests
    def test_default_mode_is_warn(self):
        """Handler should default to 'warn' mode for backward compatibility."""
        handler = GitStashHandler()
        # Default mode should be 'warn'
        assert hasattr(handler, "_mode")
        assert handler._mode == "warn"

    def test_accepts_deny_mode_configuration(self):
        """Handler should accept 'deny' mode configuration."""
        handler = GitStashHandler()
        # Simulate config system setting mode
        handler._mode = "deny"
        assert handler._mode == "deny"

    def test_accepts_warn_mode_configuration(self):
        """Handler should accept 'warn' mode configuration."""
        handler = GitStashHandler()
        handler._mode = "warn"
        assert handler._mode == "warn"

    def test_deny_mode_returns_deny_decision(self):
        """In 'deny' mode, handle() should return deny decision."""
        handler = GitStashHandler()
        handler._mode = "deny"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_deny_mode_provides_blocking_reason(self):
        """In 'deny' mode, handle() should provide clear blocking reason."""
        handler = GitStashHandler()
        handler._mode = "deny"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert "BLOCKED" in result.reason or "blocked" in result.reason.lower()

    def test_deny_mode_provides_alternatives(self):
        """In 'deny' mode, reason should still provide alternatives."""
        handler = GitStashHandler()
        handler._mode = "deny"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert "git commit" in result.reason or "ALTERNATIVES" in result.reason

    def test_warn_mode_returns_allow_decision(self):
        """In 'warn' mode, handle() should return allow decision."""
        handler = GitStashHandler()
        handler._mode = "warn"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_warn_mode_provides_warning_guidance(self):
        """In 'warn' mode, handle() should provide warning guidance."""
        handler = GitStashHandler()
        handler._mode = "warn"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}
        result = handler.handle(hook_input)
        assert result.guidance is not None
        assert "WARNING" in result.guidance

    def test_mode_only_affects_handle_not_matches(self):
        """Mode configuration should not affect matches() behavior."""
        deny_handler = GitStashHandler()
        deny_handler._mode = "deny"
        warn_handler = GitStashHandler()
        warn_handler._mode = "warn"

        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash"}}

        # Both should match the same patterns
        assert deny_handler.matches(hook_input) == warn_handler.matches(hook_input)
