"""Tests for DaemonLocationGuardHandler."""

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.daemon_location_guard import (
    DaemonLocationGuardHandler,
)


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


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

    def test_not_matches_cd_safe_dir_then_git_add_config_file(self, handler):
        """A cd into a SAFE dir followed by a git add of the config FILE must not block.

        Regression: the config files .claude/hooks-daemon.yaml(.example) are not
        the .claude/hooks-daemon/ directory, and a `cd /workspace` earlier in a
        compound command must not let a later reference match.
        """
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd /workspace; git add .claude/hooks-daemon.yaml.example"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_cd_safe_dir_then_cat_config_file(self, handler):
        """cd to a safe dir && cat the config file must not block."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd /workspace && cat .claude/hooks-daemon.yaml"},
        }
        assert handler.matches(hook_input) is False

    def test_not_matches_git_add_config_file_without_cd(self, handler):
        """Referencing the config file with no cd at all must not block."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git add .claude/hooks-daemon.yaml.example"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_cd_into_hooks_daemon_subdir(self, handler):
        """cd into a subdirectory of hooks-daemon must still block."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd .claude/hooks-daemon/src"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_cd_with_trailing_slash(self, handler):
        """cd into hooks-daemon/ (trailing slash) must still block."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd .claude/hooks-daemon/"},
        }
        assert handler.matches(hook_input) is True

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
        # Plan 00192: this handler fires when an agent is ALREADY confused, so
        # its remedy must be runnable as printed. It names the deployed wrapper
        # and must never emit "$PYTHON", which is unset in an agent's shell.
        assert "bin/hooks-daemon status" in result.guidance
        assert "$PYTHON" not in result.guidance

    def test_handle_mentions_upgrade_command(self, handler):
        """Should mention official upgrade command in guidance."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd .claude/hooks-daemon"},
        }
        result = handler.handle(hook_input)

        assert result.guidance is not None
        assert "upgrade" in result.guidance.lower()


class TestDaemonLocationGuardGetRules:
    """get_rules() declares the single Rule backing this handler (Plan 00116)."""

    @pytest.fixture
    def handler(self):
        return DaemonLocationGuardHandler()

    def test_returns_one_rule(self, handler):
        rules = handler.get_rules()
        assert len(rules) == 1
        assert isinstance(rules[0], Rule)

    def test_rule_id_matches_constant(self, handler):
        assert handler.get_rules()[0].rule_id == RuleID.DAEMON_DIR_CD

    def test_rule_has_non_empty_verbose(self, handler):
        assert handler.get_rules()[0].verbose


class TestDaemonLocationGuardDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Decision G)."""

    @pytest.fixture
    def handler(self):
        return DaemonLocationGuardHandler()

    def _hook_input(self, command: str, transcript_path):
        return {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "transcript_path": transcript_path,
        }

    def test_first_fire_for_agent_is_verbose(self, handler):
        hook_input = self._hook_input("cd .claude/hooks-daemon", "/tmp/agent-a/transcript.jsonl")
        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert "path confusion" in result.reason

    def test_second_fire_for_same_agent_is_terse(self, handler):
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("cd .claude/hooks-daemon", transcript_path))
        result = handler.handle(self._hook_input("cd .claude/hooks-daemon/src", transcript_path))

        assert result.decision == Decision.DENY
        assert "WHY BLOCKED" not in result.reason
        assert "cd .claude/hooks-daemon/src" in result.reason

    def test_terse_message_leads_with_rule_id(self, handler):
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("cd .claude/hooks-daemon", transcript_path))
        result = handler.handle(self._hook_input("cd .claude/hooks-daemon/src", transcript_path))

        assert result.reason.startswith(f"BLOCKED [{RuleID.DAEMON_DIR_CD}]")

    def test_missing_transcript_path_is_always_verbose(self, handler):
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "cd .claude/hooks-daemon"}}
        handler.handle(hook_input)
        result = handler.handle(hook_input)

        assert "path confusion" in result.reason
