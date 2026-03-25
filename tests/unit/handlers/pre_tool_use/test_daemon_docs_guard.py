"""Tests for DaemonDocsGuardHandler."""

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.daemon_docs_guard import (
    DaemonDocsGuardHandler,
)


class TestDaemonDocsGuardHandler:
    """Test suite for DaemonDocsGuardHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return DaemonDocsGuardHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'daemon-docs-guard'."""
        assert handler.name == "daemon-docs-guard"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 57 (advisory range)."""
        assert handler.priority == 57

    def test_init_sets_non_terminal(self, handler):
        """Handler should be non-terminal (advisory, allows operation)."""
        assert handler.terminal is False

    # matches() Tests — should trigger on reads inside hooks-daemon/CLAUDE/
    def test_matches_read_from_hooks_daemon_claude(self, handler):
        """Should match Read from .claude/hooks-daemon/CLAUDE/."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/.claude/hooks-daemon/CLAUDE/PlanWorkflow.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_read_from_hooks_daemon_claude_architecture(self, handler):
        """Should match Read from .claude/hooks-daemon/CLAUDE/ARCHITECTURE.md."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {
                "file_path": "/some/project/.claude/hooks-daemon/CLAUDE/ARCHITECTURE.md"
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_read_from_hooks_daemon_claude_subdirectory(self, handler):
        """Should match Read from any file under hooks-daemon/CLAUDE/."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {
                "file_path": "/workspace/.claude/hooks-daemon/CLAUDE/UPGRADES/v2/v2.10-to-v2.11.md"
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_relative_path_hooks_daemon_claude(self, handler):
        """Should match relative path containing hooks-daemon/CLAUDE/."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": ".claude/hooks-daemon/CLAUDE/PlanWorkflow.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_to_hooks_daemon_claude(self, handler):
        """Should also match Write to hooks-daemon/CLAUDE/ (wrong location)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/.claude/hooks-daemon/CLAUDE/SomeDoc.md",
                "content": "test",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_in_hooks_daemon_claude(self, handler):
        """Should also match Edit in hooks-daemon/CLAUDE/ (wrong location)."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/.claude/hooks-daemon/CLAUDE/HANDLER_DEVELOPMENT.md",
                "old_string": "old",
                "new_string": "new",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() Tests — should NOT trigger on correct paths
    def test_not_matches_read_from_project_claude(self, handler):
        """Should NOT match Read from project-root CLAUDE/ (correct location)."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/CLAUDE/PlanWorkflow.md"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_read_from_claude_md(self, handler):
        """Should NOT match Read from CLAUDE.md root file."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/CLAUDE.md"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_read_from_hooks_daemon_src(self, handler):
        """Should NOT match Read from hooks-daemon source (not CLAUDE/ dir)."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {
                "file_path": "/workspace/.claude/hooks-daemon/src/claude_code_hooks_daemon/daemon/cli.py"
            },
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_bash_tool(self, handler):
        """Should NOT match Bash tool calls."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat .claude/hooks-daemon/CLAUDE/PlanWorkflow.md"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_missing_file_path(self, handler):
        """Should NOT match if file_path is missing."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_wrong_tool_name(self, handler):
        """Should NOT match unrelated tool names."""
        hook_input = {
            "tool_name": "Glob",
            "tool_input": {"pattern": ".claude/hooks-daemon/CLAUDE/**"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_hooks_daemon_untracked(self, handler):
        """Should NOT match reads from hooks-daemon/untracked (runtime files)."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/.claude/hooks-daemon/untracked/daemon.log"},
        }
        assert handler.matches(hook_input) is False

    # handle() Tests
    def test_handle_returns_allow(self, handler):
        """Advisory handler should ALLOW the operation."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/.claude/hooks-daemon/CLAUDE/PlanWorkflow.md"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_provides_context_warning(self, handler):
        """Should provide context warning about wrong CLAUDE directory."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/.claude/hooks-daemon/CLAUDE/PlanWorkflow.md"},
        }
        result = handler.handle(hook_input)
        assert result.context is not None
        assert len(result.context) > 0

    def test_handle_warning_mentions_hooks_daemon(self, handler):
        """Warning should mention hooks-daemon to identify the problem."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/.claude/hooks-daemon/CLAUDE/PlanWorkflow.md"},
        }
        result = handler.handle(hook_input)
        context_text = "\n".join(result.context or [])
        assert "hooks-daemon" in context_text

    def test_handle_warning_mentions_project_claude_dir(self, handler):
        """Warning should direct to correct project CLAUDE/ directory."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/.claude/hooks-daemon/CLAUDE/PlanWorkflow.md"},
        }
        result = handler.handle(hook_input)
        context_text = "\n".join(result.context or [])
        assert "CLAUDE/" in context_text

    def test_handle_includes_read_file_in_warning(self, handler):
        """Warning should include the specific file being read."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/.claude/hooks-daemon/CLAUDE/PlanWorkflow.md"},
        }
        result = handler.handle(hook_input)
        context_text = "\n".join(result.context or [])
        assert "PlanWorkflow.md" in context_text

    def test_handle_write_returns_allow_with_warning(self, handler):
        """Write to wrong location should also be allowed but warned."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/.claude/hooks-daemon/CLAUDE/SomeDoc.md",
                "content": "test",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        context_text = "\n".join(result.context or [])
        assert "hooks-daemon" in context_text
