"""Comprehensive tests for AutoApproveReadsHandler."""

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

    # matches() - Positive Cases
    def test_matches_file_read_permission(self, handler):
        """Should match file_read permission type."""
        hook_input = {
            "permission_type": "file_read",
            "resource": "/workspace/README.md",
        }
        assert handler.matches(hook_input) is True

    def test_matches_file_write_permission(self, handler):
        """Should match file_write permission type."""
        hook_input = {
            "permission_type": "file_write",
            "resource": "/workspace/notes.txt",
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases
    def test_matches_network_permission_returns_false(self, handler):
        """Should not match network permission types."""
        hook_input = {
            "permission_type": "network",
            "resource": "https://example.com",
        }
        assert handler.matches(hook_input) is False

    def test_matches_missing_permission_type_returns_false(self, handler):
        """Should not match when permission_type is missing."""
        hook_input = {
            "resource": "/workspace/file.txt",
        }
        assert handler.matches(hook_input) is False

    def test_matches_none_permission_type_returns_false(self, handler):
        """Should not match when permission_type is None."""
        hook_input = {
            "permission_type": None,
            "resource": "/workspace/file.txt",
        }
        assert handler.matches(hook_input) is False

    def test_matches_empty_permission_type_returns_false(self, handler):
        """Should not match when permission_type is empty."""
        hook_input = {
            "permission_type": "",
            "resource": "/workspace/file.txt",
        }
        assert handler.matches(hook_input) is False

    # handle() Tests - file_read
    def test_handle_file_read_returns_allow_decision(self, handler):
        """handle() should return allow for file_read."""
        hook_input = {
            "permission_type": "file_read",
            "resource": "/workspace/README.md",
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_file_read_has_no_reason(self, handler):
        """handle() should not provide reason for file_read (auto-approval)."""
        hook_input = {
            "permission_type": "file_read",
            "resource": "/workspace/notes.txt",
        }
        result = handler.handle(hook_input)
        assert result.reason is None

    def test_handle_file_read_has_no_context(self, handler):
        """handle() should not provide context for file_read."""
        hook_input = {
            "permission_type": "file_read",
            "resource": "/workspace/README.md",
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_file_read_has_no_guidance(self, handler):
        """handle() should not provide guidance for file_read."""
        hook_input = {
            "permission_type": "file_read",
            "resource": "/workspace/README.md",
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    # handle() Tests - file_write
    def test_handle_file_write_returns_deny_decision(self, handler):
        """handle() should return deny for file_write."""
        hook_input = {
            "permission_type": "file_write",
            "resource": "/workspace/test.py",
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_file_write_has_reason(self, handler):
        """handle() should provide reason for file_write denial."""
        hook_input = {
            "permission_type": "file_write",
            "resource": "/workspace/test.py",
        }
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert "BLOCKED" in result.reason
        assert "file_write" in result.reason

    def test_handle_returns_hook_result_instance(self, handler):
        """handle() should return HookResult instance."""
        hook_input = {
            "permission_type": "file_read",
            "resource": "/workspace/README.md",
        }
        result = handler.handle(hook_input)
        assert isinstance(result, HookResult)
