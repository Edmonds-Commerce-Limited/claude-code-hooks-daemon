"""Comprehensive tests for DangerousPermissionsHandler."""

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.dangerous_permissions import (
    DangerousPermissionsHandler,
)


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """get_data_layer() is a process-wide singleton (Plan 00116, Decision G).

    Without this, one test's ``mark_disclosed`` for a rule_id + transcript_path
    leaks into a later test that reuses the same pair, turning a genuine
    "first fire" into a stale "already disclosed".
    """
    reset_data_layer()
    yield
    reset_data_layer()


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

    # matches() - Documented world-writable forms (666, a+w, o+w)
    def test_matches_chmod_666(self, handler):
        """Should match 'chmod 666' (world-writable, documented as blocked)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod 666 file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_chmod_recursive_666(self, handler):
        """Should match 'chmod -R 666'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod -R 666 dir/"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_chmod_a_plus_w(self, handler):
        """Should match 'chmod a+w' (all gain write, documented as blocked)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod a+w file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_chmod_o_plus_w(self, handler):
        """Should match 'chmod o+w' (others gain write, documented as blocked)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod o+w file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_chmod_o_plus_rw(self, handler):
        """Should match 'chmod o+rw' (others gain write)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod o+rw file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_chmod_other_world_writable_octal(self, handler):
        """Should match other world-writable octal modes (e.g. 757, last digit 7)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod 757 file.txt"},
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

    def test_handle_reason_leads_with_rule_id(self, handler):
        """handle() reason should lead with the rule's ID (Plan 00116 parity contract)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod -R 777 /var/www/"},
        }
        result = handler.handle(hook_input)
        assert result.reason.startswith(f"BLOCKED [{RuleID.CHMOD_WORLD_WRITABLE}]")

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


class TestDangerousPermissionsDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Plan 00116)."""

    @pytest.fixture
    def handler(self):
        return DangerousPermissionsHandler()

    def _hook_input(self, command: str, transcript_path: str | None = None) -> dict:
        hook_input: dict = {"tool_name": "Bash", "tool_input": {"command": command}}
        if transcript_path is not None:
            hook_input["transcript_path"] = transcript_path
        return hook_input

    def test_first_fire_for_agent_is_verbose(self, handler):
        hook_input = self._hook_input("chmod 777 file.txt", "/tmp/agent-a/transcript.jsonl")
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "CORRECT permissions" in result.reason

    def test_second_fire_for_same_agent_is_terse(self, handler):
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("chmod 777 file.txt", transcript_path))
        result = handler.handle(self._hook_input("chmod a+w other.txt", transcript_path))
        assert "CORRECT permissions" not in result.reason
        assert result.reason.startswith(f"BLOCKED [{RuleID.CHMOD_WORLD_WRITABLE}]")
        assert "Fix:" in result.reason

    def test_same_rule_different_agent_is_independently_verbose(self, handler):
        handler.handle(self._hook_input("chmod 777 file.txt", "/tmp/agent-a/transcript.jsonl"))
        result = handler.handle(
            self._hook_input("chmod 777 file.txt", "/tmp/agent-b/transcript.jsonl")
        )
        assert "CORRECT permissions" in result.reason

    def test_missing_transcript_path_fails_toward_verbose_every_time(self, handler):
        hook_input = self._hook_input("chmod 777 file.txt")
        first = handler.handle(hook_input)
        second = handler.handle(hook_input)
        assert "CORRECT permissions" in first.reason
        assert "CORRECT permissions" in second.reason


class TestDangerousPermissionsGetRules:
    """get_rules() declares the single Rule backing this handler (Plan 00116)."""

    @pytest.fixture
    def handler(self):
        return DangerousPermissionsHandler()

    def test_returns_one_rule(self, handler):
        rules = handler.get_rules()
        assert len(rules) == 1
        assert all(isinstance(rule, Rule) for rule in rules)

    def test_rule_id_matches_constant(self, handler):
        rules = handler.get_rules()
        assert rules[0].rule_id == RuleID.CHMOD_WORLD_WRITABLE

    def test_rule_has_non_empty_verbose(self, handler):
        rules = handler.get_rules()
        assert rules[0].verbose
