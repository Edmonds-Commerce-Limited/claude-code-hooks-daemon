"""Comprehensive tests for DangerousPermissionsHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.dangerous_permissions import (
    DangerousPermissionsHandler,
)


class TestDangerousPermissionsHandler:
    """Test suite for DangerousPermissionsHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return DangerousPermissionsHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'block-dangerous-permissions'."""
        assert handler.name == "block-dangerous-permissions"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 15."""
        assert handler.priority == 15

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (blocks execution)."""
        assert handler.terminal is True

    # matches() - Pattern 1: chmod 777
    def test_matches_chmod_777(self, handler):
        """Should match 'chmod 777'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod 777 file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_chmod_777_with_path(self, handler):
        """Should match chmod 777 with file path."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod 777 /var/www/uploads/"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_chmod_recursive_777(self, handler):
        """Should match 'chmod -R 777'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod -R 777 /tmp/data"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_chmod_777_multiple_files(self, handler):
        """Should match chmod 777 with multiple files."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod 777 file1.txt file2.txt file3.txt"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 2: chmod a+rwx
    def test_matches_chmod_a_plus_rwx(self, handler):
        """Should match 'chmod a+rwx'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod a+rwx file.sh"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_chmod_recursive_a_plus_rwx(self, handler):
        """Should match 'chmod -R a+rwx'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod -R a+rwx /var/www/"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Edge cases
    def test_matches_chmod_777_at_end(self, handler):
        """Should match when 777 appears at end."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod file.txt 777"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_chmod_with_verbose_flag(self, handler):
        """Should match with -v flag."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod -v 777 file.txt"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Safe chmod commands
    def test_matches_chmod_755_returns_false(self, handler):
        """Should NOT match safe 'chmod 755'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod 755 script.sh"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_chmod_644_returns_false(self, handler):
        """Should NOT match safe 'chmod 644'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod 644 config.json"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_chmod_600_returns_false(self, handler):
        """Should NOT match safe 'chmod 600'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod 600 secret.key"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_chmod_u_plus_x_returns_false(self, handler):
        """Should NOT match 'chmod u+x'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod u+x script.sh"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_chmod_go_minus_w_returns_false(self, handler):
        """Should NOT match 'chmod go-w'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod go-w file.txt"},
        }
        assert handler.matches(hook_input) is False

    # matches() - Edge Cases
    def test_matches_non_bash_tool_returns_false(self, handler):
        """Should not match non-Bash tools."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.sh",
                "content": "chmod 777 file.txt",
            },
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

    # handle() Tests - Return value and message structure
    def test_handle_returns_deny_decision(self, handler):
        """handle() should return deny decision."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod 777 file.txt"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod 777 file.txt"},
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_reason_contains_command(self, handler):
        """handle() reason should include the blocked command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod -R 777 /var/www/"},
        }
        result = handler.handle(hook_input)
        assert "chmod -R 777 /var/www/" in result.reason

    def test_handle_reason_explains_danger(self, handler):
        """handle() reason should explain why 777 is dangerous."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod 777 file.txt"},
        }
        result = handler.handle(hook_input)
        assert "777" in result.reason or "a+rwx" in result.reason
        assert "security" in result.reason.lower()

    def test_handle_reason_provides_correct_permissions(self, handler):
        """handle() reason should provide correct permission examples."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod 777 file.txt"},
        }
        result = handler.handle(hook_input)
        assert "755" in result.reason
        assert "644" in result.reason
        assert "600" in result.reason

    def test_handle_empty_command_returns_allow(self, handler):
        """handle() should return ALLOW for empty command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    # Integration Tests
    def test_blocks_all_dangerous_permission_variants(self, handler):
        """Should block all known dangerous permission patterns."""
        dangerous_commands = [
            "chmod 777 file.txt",
            "chmod -R 777 /var/www/",
            "chmod a+rwx script.sh",
            "chmod -R a+rwx /tmp/data",
            "chmod 777 file1 file2 file3",
            "chmod -v 777 file.txt",
        ]
        for cmd in dangerous_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is True, f"Should block: {cmd}"

    def test_allows_all_safe_chmod_commands(self, handler):
        """Should allow all safe chmod commands."""
        safe_commands = [
            "chmod 755 script.sh",
            "chmod 644 config.json",
            "chmod 600 secret.key",
            "chmod u+x script.sh",
            "chmod go-w file.txt",
            "chmod 700 ~/.ssh",
            "chmod -R 755 /var/www/html",
        ]
        for cmd in safe_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is False, f"Should allow: {cmd}"
