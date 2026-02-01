"""Comprehensive tests for SudoPipHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.sudo_pip import SudoPipHandler


class TestSudoPipHandler:
    """Test suite for SudoPipHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return SudoPipHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'block-sudo-pip'."""
        assert handler.name == "block-sudo-pip"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 10."""
        assert handler.priority == 10

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (blocks execution)."""
        assert handler.terminal is True

    # matches() - Pattern 1: sudo pip install
    def test_matches_sudo_pip_install(self, handler):
        """Should match 'sudo pip install'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip install requests"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_sudo_pip_install_multiple_packages(self, handler):
        """Should match 'sudo pip install' with multiple packages."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip install requests flask django"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_sudo_pip_install_with_flags(self, handler):
        """Should match 'sudo pip install' with flags."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip install --upgrade numpy"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_sudo_pip_install_case_insensitive(self, handler):
        """Should match with different casing."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "SUDO PIP INSTALL requests"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 2: sudo pip3 install
    def test_matches_sudo_pip3_install(self, handler):
        """Should match 'sudo pip3 install'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip3 install requests"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_sudo_pip3_install_with_version(self, handler):
        """Should match pip3 with version specifier."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip3 install requests==2.28.0"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 3: sudo python -m pip install
    def test_matches_sudo_python_m_pip_install(self, handler):
        """Should match 'sudo python -m pip install'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo python -m pip install requests"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_sudo_python_m_pip_install_with_flags(self, handler):
        """Should match 'sudo python -m pip install' with additional flags."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo python -m pip install --upgrade flask"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 4: sudo python3 -m pip install
    def test_matches_sudo_python3_m_pip_install(self, handler):
        """Should match 'sudo python3 -m pip install'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo python3 -m pip install requests"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_sudo_python3_m_pip_install_with_requirements(self, handler):
        """Should match with -r requirements.txt."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo python3 -m pip install -r requirements.txt"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Safe pip commands
    def test_matches_pip_install_without_sudo_returns_false(self, handler):
        """Should NOT match safe 'pip install'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pip install requests"}}
        assert handler.matches(hook_input) is False

    def test_matches_pip3_install_without_sudo_returns_false(self, handler):
        """Should NOT match safe 'pip3 install'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pip3 install requests"}}
        assert handler.matches(hook_input) is False

    def test_matches_python_m_pip_install_without_sudo_returns_false(self, handler):
        """Should NOT match safe 'python -m pip install'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "python -m pip install requests"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_python3_m_pip_install_without_sudo_returns_false(self, handler):
        """Should NOT match safe 'python3 -m pip install'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -m pip install requests"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_pip_install_user_returns_false(self, handler):
        """Should NOT match 'pip install --user'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --user requests"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_pip_list_returns_false(self, handler):
        """Should NOT match 'sudo pip list'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "sudo pip list"}}
        assert handler.matches(hook_input) is False

    def test_matches_pip_show_returns_false(self, handler):
        """Should NOT match 'sudo pip show'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "sudo pip show requests"}}
        assert handler.matches(hook_input) is False

    def test_matches_pip_freeze_returns_false(self, handler):
        """Should NOT match 'sudo pip freeze'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "sudo pip freeze"}}
        assert handler.matches(hook_input) is False

    def test_matches_pip_uninstall_returns_false(self, handler):
        """Should NOT match 'sudo pip uninstall'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip uninstall requests"},
        }
        assert handler.matches(hook_input) is False

    # matches() - Edge Cases
    def test_matches_non_bash_tool_returns_false(self, handler):
        """Should not match non-Bash tools."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.sh",
                "content": "sudo pip install requests",
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

    def test_matches_missing_command_key_returns_false(self, handler):
        """Should not match when command key is missing."""
        hook_input = {"tool_name": "Bash", "tool_input": {}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_tool_input_returns_false(self, handler):
        """Should not match when tool_input is missing."""
        hook_input = {"tool_name": "Bash"}
        assert handler.matches(hook_input) is False

    def test_matches_command_without_sudo_returns_false(self, handler):
        """Should not match commands without 'sudo'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "apt install python3-pip"}}
        assert handler.matches(hook_input) is False

    def test_matches_sudo_apt_install_returns_false(self, handler):
        """Should not match other sudo commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo apt install python3-pip"},
        }
        assert handler.matches(hook_input) is False

    # handle() Tests - Return value and message structure
    def test_handle_returns_deny_decision(self, handler):
        """handle() should return deny decision."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip install requests"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip install requests"},
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_reason_contains_command(self, handler):
        """handle() reason should include the blocked command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip3 install flask"},
        }
        result = handler.handle(hook_input)
        assert "sudo pip3 install flask" in result.reason

    def test_handle_reason_explains_danger(self, handler):
        """handle() reason should explain why sudo pip is dangerous."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip install requests"},
        }
        result = handler.handle(hook_input)
        assert "system-wide" in result.reason or "System-wide" in result.reason
        assert "package manager" in result.reason or "OS tools" in result.reason

    def test_handle_reason_provides_safe_alternatives(self, handler):
        """handle() reason should provide safe alternatives."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip install requests"},
        }
        result = handler.handle(hook_input)
        assert "venv" in result.reason or "virtual environment" in result.reason
        assert "--user" in result.reason

    def test_handle_reason_warns_about_conflicts(self, handler):
        """handle() reason should warn about conflicts."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip install requests"},
        }
        result = handler.handle(hook_input)
        assert "conflict" in result.reason.lower() or "break" in result.reason.lower()

    # handle() Tests - Return values
    def test_handle_context_is_empty_list(self, handler):
        """handle() context should be empty list (not used)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip install requests"},
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None (not used)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sudo pip install requests"},
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    def test_handle_empty_command_returns_allow(self, handler):
        """handle() should return ALLOW for empty command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    # Integration Tests
    def test_blocks_all_sudo_pip_variants(self, handler):
        """Should block all known variants of sudo pip install."""
        dangerous_commands = [
            "sudo pip install requests",
            "sudo pip3 install requests",
            "sudo python -m pip install requests",
            "sudo python3 -m pip install requests",
            "sudo pip install --upgrade numpy",
            "sudo pip3 install -r requirements.txt",
            "sudo python -m pip install flask django",
            "SUDO PIP INSTALL requests",
        ]
        for cmd in dangerous_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is True, f"Should block: {cmd}"

    def test_allows_all_safe_pip_commands(self, handler):
        """Should allow all safe pip commands."""
        safe_commands = [
            "pip install requests",
            "pip3 install requests",
            "python -m pip install requests",
            "python3 -m pip install requests",
            "pip install --upgrade requests",
            "pip install -r requirements.txt",
            "pip install --user requests",
            "sudo pip list",
            "sudo pip show requests",
            "sudo pip freeze",
            "sudo apt install python3-pip",
        ]
        for cmd in safe_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is False, f"Should allow: {cmd}"
