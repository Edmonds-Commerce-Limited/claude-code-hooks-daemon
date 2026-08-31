"""Comprehensive tests for WorktreeFileCopyHandler."""

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.worktree_file_copy import (
    WorktreeFileCopyHandler,
)


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test (Plan 00116)."""
    reset_data_layer()
    yield
    reset_data_layer()


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

    def test_matches_different_worktrees_to_different_worktrees_returns_true(self, handler):
        """Should block copying between different worktrees even if both paths contain worktrees."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "cp untracked/worktrees/feature-a/file.py untracked/worktrees/feature-b/src/"
            },
        }
        # Different worktrees (feature-a to feature-b/src/) - should block
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

    # matches() - .claude/worktrees/ paths (Claude Code managed worktrees)
    def test_matches_cp_from_claude_worktree_to_src(self, handler):
        """Should match cp from .claude/worktrees/ to src/."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp .claude/worktrees/feature-branch/src/test.py src/"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_cp_from_claude_worktree_to_tests(self, handler):
        """Should match cp from .claude/worktrees/ to tests/."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp .claude/worktrees/fix-bug/tests/test.py tests/"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_mv_from_claude_worktree_to_src(self, handler):
        """Should match mv from .claude/worktrees/ to src/."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "mv .claude/worktrees/branch/src/file.py src/"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_rsync_from_claude_worktree(self, handler):
        """Should match rsync from .claude/worktrees/ to src."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rsync -av .claude/worktrees/branch/src/ src/"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_cp_within_same_claude_worktree_returns_false(self, handler):
        """Should allow cp within the same .claude/worktrees/ branch."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "cp .claude/worktrees/branch/src/a.py .claude/worktrees/branch/tests/"
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_ls_claude_worktree_returns_false(self, handler):
        """Should not match ls of .claude/worktrees/ path."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls .claude/worktrees/branch/"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_honours_declared_source_dir_from_facade(self, handler):
        """A project-declared layout.source_dirs entry is also protected
        (Plan 00288 Task 4.3): "main repo code dirs" is read from the
        ProjectLayout facade instead of the hardcoded src/tests/config
        triple."""
        from claude_code_hooks_daemon.core.project_layout import ProjectLayout

        handler._project_layout = ProjectLayout(
            source_dirs=("backend",),
            test_dirs=("tests",),
            config_dirs=("config",),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="CLAUDE/Plan",
            plan_archive_dirs=("Completed",),
        )
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "cp untracked/worktrees/feature-branch/backend/test.py backend/"
            },
        }
        assert handler.matches(hook_input) is True


class TestGetRules:
    @pytest.fixture
    def handler(self) -> WorktreeFileCopyHandler:
        return WorktreeFileCopyHandler()

    def test_returns_one_rule(self, handler: WorktreeFileCopyHandler) -> None:
        rules = handler.get_rules()
        assert len(rules) == 1
        assert isinstance(rules[0], Rule)
        assert rules[0].rule_id == RuleID.WORKTREE_FILE_COPY
        assert rules[0].verbose


class TestDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Plan 00116).

    The blocked command is invocation-specific evidence and is always shown.
    """

    @pytest.fixture
    def handler(self) -> WorktreeFileCopyHandler:
        return WorktreeFileCopyHandler()

    def _hook_input(self, command: str, transcript_path: str) -> dict:
        return {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "transcript_path": transcript_path,
        }

    def test_deny_leads_with_rule_id(self, handler: WorktreeFileCopyHandler) -> None:
        result = handler.handle(
            self._hook_input(
                "cp untracked/worktrees/branch/src/file.py src/", "/tmp/agent-a/transcript.jsonl"
            )
        )
        assert result.reason.startswith(f"BLOCKED [{RuleID.WORKTREE_FILE_COPY}]")

    def test_first_fire_is_verbose(self, handler: WorktreeFileCopyHandler) -> None:
        result = handler.handle(
            self._hook_input(
                "cp untracked/worktrees/branch/src/file.py src/", "/tmp/agent-a/transcript.jsonl"
            )
        )
        assert "CATASTROPHIC" in result.reason

    def test_second_fire_same_agent_is_terse_but_still_names_command(
        self, handler: WorktreeFileCopyHandler
    ) -> None:
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(
            self._hook_input("cp untracked/worktrees/branch/src/a.py src/", transcript_path)
        )
        result = handler.handle(
            self._hook_input("mv untracked/worktrees/branch/tests/b.py tests/", transcript_path)
        )
        assert "CATASTROPHIC" not in result.reason
        assert "mv untracked/worktrees/branch/tests/b.py tests/" in result.reason

    def test_missing_transcript_path_fails_toward_verbose_every_time(
        self, handler: WorktreeFileCopyHandler
    ) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp untracked/worktrees/branch/src/file.py src/"},
        }
        first = handler.handle(hook_input)
        second = handler.handle(hook_input)
        assert "CATASTROPHIC" in first.reason
        assert "CATASTROPHIC" in second.reason
