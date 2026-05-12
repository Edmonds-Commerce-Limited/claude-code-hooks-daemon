"""Comprehensive tests for AutoApproveReadsHandler.

Tests use REAL PermissionRequest event structure with tool_name,
permission_mode, and permission_suggestions fields.

The handler is gated on `permission_mode == "bypassPermissions"`. In any
other mode the handler must defer (matches() returns False) so Claude
Code's normal approval flow runs. This is the security gate restored
in Plan 00106 — silently auto-approving in non-YOLO modes was the bug.
"""

import pytest

from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.permission_request.auto_approve_reads import (
    AutoApproveReadsHandler,
)


def _bypass_request(tool_name: str, tool_input: dict | None = None) -> dict:
    """Build a PermissionRequest hook_input in bypassPermissions mode."""
    return {
        "hook_event_name": "PermissionRequest",
        "permission_mode": "bypassPermissions",
        "tool_name": tool_name,
        "tool_input": tool_input or {},
        "permission_suggestions": [{"prompt": "Allow?"}],
    }


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
    # matches() - Positive Cases (read-only tools IN BYPASS MODE)
    # =====================================================================
    def test_matches_read_tool(self, handler):
        """Should match Read tool permission request in bypass mode."""
        assert (
            handler.matches(_bypass_request("Read", {"file_path": "/workspace/README.md"})) is True
        )

    def test_matches_glob_tool(self, handler):
        """Should match Glob tool permission request in bypass mode."""
        assert handler.matches(_bypass_request("Glob", {"pattern": "**/*.py"})) is True

    def test_matches_grep_tool(self, handler):
        """Should match Grep tool permission request in bypass mode."""
        assert handler.matches(_bypass_request("Grep", {"pattern": "TODO"})) is True

    # =====================================================================
    # matches() - Negative Cases (write/execute tools should NOT match
    # even in bypass mode — only read-only tools auto-approve)
    # =====================================================================
    def test_matches_write_tool_returns_false(self, handler):
        """Should NOT match Write tool — not a read operation."""
        assert (
            handler.matches(_bypass_request("Write", {"file_path": "/workspace/test.py"})) is False
        )

    def test_matches_edit_tool_returns_false(self, handler):
        """Should NOT match Edit tool — not a read operation."""
        assert (
            handler.matches(_bypass_request("Edit", {"file_path": "/workspace/test.py"})) is False
        )

    def test_matches_bash_tool_returns_false(self, handler):
        """Should NOT match Bash tool — not a read operation."""
        assert handler.matches(_bypass_request("Bash", {"command": "ls"})) is False

    def test_matches_missing_tool_name_returns_false(self, handler):
        """Should not match when tool_name is missing."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "permission_mode": "bypassPermissions",
            "permission_suggestions": [{"prompt": "Allow?"}],
        }
        assert handler.matches(hook_input) is False

    def test_matches_none_tool_name_returns_false(self, handler):
        """Should not match when tool_name is None."""
        hook_input = _bypass_request("Read")
        hook_input["tool_name"] = None
        assert handler.matches(hook_input) is False

    def test_matches_empty_tool_name_returns_false(self, handler):
        """Should not match when tool_name is empty."""
        assert handler.matches(_bypass_request("")) is False

    def test_matches_unknown_tool_returns_false(self, handler):
        """Should not match unknown tool names."""
        assert handler.matches(_bypass_request("CustomTool")) is False

    # =====================================================================
    # handle() Tests - Read tool in bypass mode (auto-approve)
    # =====================================================================
    def test_handle_read_tool_returns_allow_decision(self, handler):
        """handle() should return allow for Read tool in bypass mode."""
        result = handler.handle(_bypass_request("Read", {"file_path": "/workspace/README.md"}))
        assert result.decision == "allow"

    def test_handle_read_tool_has_no_reason(self, handler):
        """handle() should not provide reason for Read tool (auto-approval)."""
        result = handler.handle(_bypass_request("Read", {"file_path": "/workspace/notes.txt"}))
        assert result.reason is None

    def test_handle_glob_tool_returns_allow(self, handler):
        """handle() should return allow for Glob tool in bypass mode."""
        result = handler.handle(_bypass_request("Glob", {"pattern": "**/*.py"}))
        assert result.decision == "allow"

    def test_handle_grep_tool_returns_allow(self, handler):
        """handle() should return allow for Grep tool in bypass mode."""
        result = handler.handle(_bypass_request("Grep", {"pattern": "TODO"}))
        assert result.decision == "allow"

    # =====================================================================
    # handle() Tests - Non-read tools (should not reach handle, but test defence)
    # =====================================================================
    def test_handle_non_read_tool_returns_deny(self, handler):
        """handle() should deny non-read tools that somehow reach handle()."""
        result = handler.handle(_bypass_request("Write", {"file_path": "/workspace/test.py"}))
        assert result.decision == "deny"
        assert result.reason is not None
        assert "BLOCKED" in result.reason

    def test_handle_returns_hook_result_instance(self, handler):
        """handle() should return HookResult instance."""
        result = handler.handle(_bypass_request("Read", {"file_path": "/workspace/README.md"}))
        assert isinstance(result, HookResult)


class TestPermissionModeGating:
    """Auto-approve must defer (no match) in every non-bypass mode.

    Plan 00106: silently auto-approving Read/Glob/Grep in `default` mode
    was the bug — it converted a non-YOLO session into YOLO behaviour
    without user consent. The handler must defer to Claude Code's normal
    approval flow unless the user has explicitly opted into bypass mode.
    """

    @pytest.fixture
    def handler(self):
        return AutoApproveReadsHandler()

    @pytest.mark.parametrize("mode", ["default", "plan", "acceptEdits", "dontAsk"])
    @pytest.mark.parametrize("tool", ["Read", "Glob", "Grep"])
    def test_does_not_match_read_only_tools_outside_bypass_mode(
        self, handler, mode: str, tool: str
    ):
        """Read/Glob/Grep must NOT auto-approve in default/plan/acceptEdits/dontAsk."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "permission_mode": mode,
            "tool_name": tool,
            "tool_input": {},
            "permission_suggestions": [{"prompt": "Allow?"}],
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_when_permission_mode_missing(self, handler):
        """No permission_mode key → defer (fail-safe to user's normal flow)."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/README.md"},
            "permission_suggestions": [{"prompt": "Allow?"}],
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_when_permission_mode_is_none(self, handler):
        """permission_mode == None → defer."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "permission_mode": None,
            "tool_name": "Read",
            "tool_input": {},
            "permission_suggestions": [{"prompt": "Allow?"}],
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_for_unknown_future_mode(self, handler):
        """Unrecognised mode strings → defer (fail safe)."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "permission_mode": "someFutureMode",
            "tool_name": "Read",
            "tool_input": {},
            "permission_suggestions": [{"prompt": "Allow?"}],
        }
        assert handler.matches(hook_input) is False


class TestClaudeMdGuidance:
    """get_claude_md() must document the permission-mode gate."""

    def test_returns_non_none(self):
        handler = AutoApproveReadsHandler()
        assert handler.get_claude_md() is not None

    def test_mentions_bypass_mode(self):
        handler = AutoApproveReadsHandler()
        guidance = handler.get_claude_md() or ""
        assert "bypassPermissions" in guidance or "bypass" in guidance.lower()
