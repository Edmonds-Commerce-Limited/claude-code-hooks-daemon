"""Comprehensive tests for AutoApproveReadsHandler.

Tests use REAL PermissionRequest event structure with tool_name and
permission_suggestions fields (NOT the non-existent permission_type field).
"""

import pytest

from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.permission_request.auto_approve_reads import (
    AutoApproveReadsHandler,
)


class TestAutoApproveReadsHandler:
    """Test suite for AutoApproveReadsHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return AutoApproveReadsHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'auto-approve-reads'."""
        assert handler.name == "auto-approve-reads"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 10."""
        assert handler.priority == 10

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    # =====================================================================
    # matches() - Positive Cases (read-only tools)
    # =====================================================================
    def test_matches_read_tool(self, handler):
        """Should match Read tool permission request."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/README.md"},
            "permission_suggestions": [{"prompt": "Allow read?"}],
        }
        assert handler.matches(hook_input) is True

    def test_matches_glob_tool(self, handler):
        """Should match Glob tool permission request."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Glob",
            "tool_input": {"pattern": "**/*.py"},
            "permission_suggestions": [{"prompt": "Allow glob?"}],
        }
        assert handler.matches(hook_input) is True

    def test_matches_grep_tool(self, handler):
        """Should match Grep tool permission request."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Grep",
            "tool_input": {"pattern": "TODO"},
            "permission_suggestions": [{"prompt": "Allow grep?"}],
        }
        assert handler.matches(hook_input) is True

    # =====================================================================
    # matches() - Negative Cases (write/execute tools should NOT match)
    # =====================================================================
    def test_matches_write_tool_returns_false(self, handler):
        """Should NOT match Write tool — not a read operation."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/test.py"},
            "permission_suggestions": [{"prompt": "Allow write?"}],
        }
        assert handler.matches(hook_input) is False

    def test_matches_edit_tool_returns_false(self, handler):
        """Should NOT match Edit tool — not a read operation."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/test.py"},
            "permission_suggestions": [{"prompt": "Allow edit?"}],
        }
        assert handler.matches(hook_input) is False

    def test_matches_bash_tool_returns_false(self, handler):
        """Should NOT match Bash tool — not a read operation."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "permission_suggestions": [{"prompt": "Allow bash?"}],
        }
        assert handler.matches(hook_input) is False

    def test_matches_missing_tool_name_returns_false(self, handler):
        """Should not match when tool_name is missing."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "permission_suggestions": [{"prompt": "Allow?"}],
        }
        assert handler.matches(hook_input) is False

    def test_matches_none_tool_name_returns_false(self, handler):
        """Should not match when tool_name is None."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": None,
            "permission_suggestions": [{"prompt": "Allow?"}],
        }
        assert handler.matches(hook_input) is False

    def test_matches_empty_tool_name_returns_false(self, handler):
        """Should not match when tool_name is empty."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "",
            "permission_suggestions": [{"prompt": "Allow?"}],
        }
        assert handler.matches(hook_input) is False

    def test_matches_unknown_tool_returns_false(self, handler):
        """Should not match unknown tool names."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "CustomTool",
            "permission_suggestions": [{"prompt": "Allow?"}],
        }
        assert handler.matches(hook_input) is False

    # =====================================================================
    # handle() Tests - Read tool (auto-approve)
    # =====================================================================
    def test_handle_read_tool_returns_allow_decision(self, handler):
        """handle() should return allow for Read tool."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/README.md"},
            "permission_suggestions": [{"prompt": "Allow read?"}],
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_read_tool_has_no_reason(self, handler):
        """handle() should not provide reason for Read tool (auto-approval)."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/notes.txt"},
            "permission_suggestions": [{"prompt": "Allow read?"}],
        }
        result = handler.handle(hook_input)
        assert result.reason is None

    def test_handle_glob_tool_returns_allow(self, handler):
        """handle() should return allow for Glob tool."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Glob",
            "tool_input": {"pattern": "**/*.py"},
            "permission_suggestions": [{"prompt": "Allow glob?"}],
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_grep_tool_returns_allow(self, handler):
        """handle() should return allow for Grep tool."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Grep",
            "tool_input": {"pattern": "TODO"},
            "permission_suggestions": [{"prompt": "Allow grep?"}],
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    # =====================================================================
    # handle() Tests - Non-read tools (should not reach handle, but test defence)
    # =====================================================================
    def test_handle_non_read_tool_returns_deny(self, handler):
        """handle() should deny non-read tools that somehow reach handle()."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/test.py"},
            "permission_suggestions": [{"prompt": "Allow write?"}],
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert result.reason is not None
        assert "BLOCKED" in result.reason

    def test_handle_returns_hook_result_instance(self, handler):
        """handle() should return HookResult instance."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/README.md"},
            "permission_suggestions": [{"prompt": "Allow read?"}],
        }
        result = handler.handle(hook_input)
        assert isinstance(result, HookResult)
