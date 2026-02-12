"""Tests for DaemonLocationGuardHandler."""

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.daemon_location_guard import (
    DaemonLocationGuardHandler,
)


class TestDaemonLocationGuardHandler:
    """Test suite for DaemonLocationGuardHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return DaemonLocationGuardHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'daemon-location-guard'."""
        assert handler.name == "daemon-location-guard"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 11."""
        assert handler.priority == 11

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal."""
        assert handler.terminal is True

    # matches() Tests - Should block cd into hooks-daemon
    def test_matches_cd_into_hooks_daemon(self, handler):
        """Should match cd into .claude/hooks-daemon."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd .claude/hooks-daemon"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_cd_with_absolute_path(self, handler):
        """Should match cd with absolute path to hooks-daemon."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd /workspace/.claude/hooks-daemon"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_cd_with_leading_dot_slash(self, handler):
        """Should match cd ./.claude/hooks-daemon."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd ./.claude/hooks-daemon"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_cd_in_compound_command(self, handler):
        """Should match cd in compound command with &&."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "cd .claude/hooks-daemon && python -m claude_code_hooks_daemon.daemon.cli status"
            },
        }
        assert handler.matches(hook_input) is True

    # matches() Tests - Should NOT match safe operations
    def test_not_matches_cd_to_different_directory(self, handler):
        """Should not match cd to other directories."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd src/handlers"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_ls_hooks_daemon(self, handler):
        """Should not match listing hooks-daemon directory."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls .claude/hooks-daemon"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_non_bash_tool(self, handler):
        """Should not match non-Bash tools."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": ".claude/hooks-daemon/test.txt"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_official_upgrade_command(self, handler):
        """Should not match the official upgrade command pattern."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "cd .claude/hooks-daemon && git pull && cd ../.. && ./scripts/upgrade.sh"
            },
        }
        # This should be whitelisted
        assert handler.matches(hook_input) is False

    # handle() Tests
    def test_handle_blocks_cd_with_clear_message(self, handler):
        """Should block cd into hooks-daemon with helpful message."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd .claude/hooks-daemon"},
        }
        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert "hooks-daemon" in result.reason.lower()
        assert "project root" in result.reason.lower()

    def test_handle_blocks_compound_command(self, handler):
        """Should block compound command with cd into hooks-daemon."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "cd .claude/hooks-daemon && python -m claude_code_hooks_daemon.daemon.cli restart"
            },
        }
        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert "hooks-daemon" in result.reason.lower()

    def test_handle_provides_guidance_on_correct_usage(self, handler):
        """Should provide guidance on running daemon commands from project root."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd .claude/hooks-daemon"},
        }
        result = handler.handle(hook_input)

        assert result.guidance is not None
        assert "PYTHON" in result.guidance or "$PYTHON" in result.guidance

    def test_handle_mentions_upgrade_command(self, handler):
        """Should mention official upgrade command in guidance."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd .claude/hooks-daemon"},
        }
        result = handler.handle(hook_input)

        assert result.guidance is not None
        assert "upgrade" in result.guidance.lower()
