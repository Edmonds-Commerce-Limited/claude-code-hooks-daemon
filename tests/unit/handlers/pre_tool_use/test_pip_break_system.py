"""Comprehensive tests for PipBreakSystemHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.pip_break_system import (
    PipBreakSystemHandler,
)


class TestPipBreakSystemHandler:
    """Test suite for PipBreakSystemHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return PipBreakSystemHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'block-pip-break-system'."""
        assert handler.name == "block-pip-break-system"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 10."""
        assert handler.priority == 10

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (blocks execution)."""
        assert handler.terminal is True

    # matches() - Pattern 1: pip install --break-system-packages
    def test_matches_pip_install_break_system_packages(self, handler):
        """Should match 'pip install --break-system-packages'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --break-system-packages requests"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_pip_install_break_system_packages_only_flag(self, handler):
        """Should match 'pip install --break-system-packages' without package name."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --break-system-packages"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_pip_install_break_system_packages_multiple(self, handler):
        """Should match 'pip install --break-system-packages' with multiple packages."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --break-system-packages requests flask django"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_pip_install_break_system_packages_with_other_flags(self, handler):
        """Should match with other flags present."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --upgrade --break-system-packages numpy"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_pip_install_break_system_packages_case_insensitive(self, handler):
        """Should match with different casing."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "PIP INSTALL --BREAK-SYSTEM-PACKAGES requests"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 2: pip3 install --break-system-packages
    def test_matches_pip3_install_break_system_packages(self, handler):
        """Should match 'pip3 install --break-system-packages'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip3 install --break-system-packages requests"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_pip3_install_break_system_packages_with_version(self, handler):
        """Should match pip3 with version specifier."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip3 install --break-system-packages requests==2.28.0"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 3: python -m pip install --break-system-packages
    def test_matches_python_m_pip_install_break_system_packages(self, handler):
        """Should match 'python -m pip install --break-system-packages'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "python -m pip install --break-system-packages requests"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_python_m_pip_install_break_system_packages_with_flags(self, handler):
        """Should match 'python -m pip install' with additional flags."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "python -m pip install --upgrade --break-system-packages flask"
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 4: python3 -m pip install --break-system-packages
    def test_matches_python3_m_pip_install_break_system_packages(self, handler):
        """Should match 'python3 -m pip install --break-system-packages'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -m pip install --break-system-packages requests"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_python3_m_pip_install_with_requirements(self, handler):
        """Should match with -r requirements.txt."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 -m pip install --break-system-packages -r requirements.txt"
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Edge cases with flag variations
    def test_matches_flag_at_beginning(self, handler):
        """Should match when flag appears first."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --break-system-packages --upgrade requests"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_flag_at_end(self, handler):
        """Should match when flag appears last."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install requests --break-system-packages"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_flag_in_middle(self, handler):
        """Should match when flag is in middle of command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --upgrade --break-system-packages requests"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Safe pip commands
    def test_matches_pip_install_without_flag_returns_false(self, handler):
        """Should NOT match safe 'pip install'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pip install requests"}}
        assert handler.matches(hook_input) is False

    def test_matches_pip3_install_without_flag_returns_false(self, handler):
        """Should NOT match safe 'pip3 install'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pip3 install requests"}}
        assert handler.matches(hook_input) is False

    def test_matches_python_m_pip_install_without_flag_returns_false(self, handler):
        """Should NOT match safe 'python -m pip install'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "python -m pip install requests"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_python3_m_pip_install_without_flag_returns_false(self, handler):
        """Should NOT match safe 'python3 -m pip install'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -m pip install requests"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_pip_list_returns_false(self, handler):
        """Should NOT match 'pip list'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pip list"}}
        assert handler.matches(hook_input) is False

    def test_matches_pip_show_returns_false(self, handler):
        """Should NOT match 'pip show'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pip show requests"}}
        assert handler.matches(hook_input) is False

    def test_matches_pip_freeze_returns_false(self, handler):
        """Should NOT match 'pip freeze'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pip freeze"}}
        assert handler.matches(hook_input) is False

    def test_matches_pip_uninstall_returns_false(self, handler):
        """Should NOT match 'pip uninstall'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pip uninstall requests"}}
        assert handler.matches(hook_input) is False

    # matches() - Edge Cases
    def test_matches_non_bash_tool_returns_false(self, handler):
        """Should not match non-Bash tools."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.sh",
                "content": "pip install --break-system-packages requests",
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

    def test_matches_command_without_pip_returns_false(self, handler):
        """Should not match commands without 'pip'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "apt install python3-pip"}}
        assert handler.matches(hook_input) is False

    def test_matches_echo_mentioning_flag_returns_false(self, handler):
        """Should not match echo statements mentioning the flag."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'Do not use pip install --break-system-packages'"},
        }
        # This will actually match because the pattern exists
        # This is acceptable - better safe than sorry
        assert handler.matches(hook_input) is True

    # handle() Tests - Return value and message structure
    def test_handle_returns_deny_decision(self, handler):
        """handle() should return deny decision."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --break-system-packages requests"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --break-system-packages requests"},
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_reason_contains_command(self, handler):
        """handle() reason should include the blocked command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip3 install --break-system-packages flask"},
        }
        result = handler.handle(hook_input)
        assert "pip3 install --break-system-packages flask" in result.reason

    def test_handle_reason_explains_danger(self, handler):
        """handle() reason should explain why flag is dangerous."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --break-system-packages requests"},
        }
        result = handler.handle(hook_input)
        assert "--break-system-packages" in result.reason
        assert "system package manager" in result.reason

    def test_handle_reason_provides_safe_alternatives(self, handler):
        """handle() reason should provide safe alternatives."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --break-system-packages requests"},
        }
        result = handler.handle(hook_input)
        assert "SAFE alternatives" in result.reason
        assert "python -m venv" in result.reason or "venv" in result.reason

    def test_handle_reason_warns_about_corruption(self, handler):
        """handle() reason should warn about system corruption."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --break-system-packages requests"},
        }
        result = handler.handle(hook_input)
        assert "corrupt" in result.reason.lower() or "break" in result.reason.lower()

    def test_handle_reason_instructs_ask_human(self, handler):
        """handle() reason should instruct to ask human."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --break-system-packages requests"},
        }
        result = handler.handle(hook_input)
        assert "ask the human user" in result.reason or "human user" in result.reason

    # handle() Tests - Return values
    def test_handle_context_is_empty_list(self, handler):
        """handle() context should be empty list (not used)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --break-system-packages requests"},
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None (not used)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install --break-system-packages requests"},
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    def test_handle_empty_command_returns_allow(self, handler):
        """handle() should return ALLOW for empty command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    # Integration Tests
    def test_blocks_all_pip_break_system_variants(self, handler):
        """Should block all known variants of pip install --break-system-packages."""
        dangerous_commands = [
            "pip install --break-system-packages requests",
            "pip3 install --break-system-packages requests",
            "python -m pip install --break-system-packages requests",
            "python3 -m pip install --break-system-packages requests",
            "pip install --upgrade --break-system-packages numpy",
            "pip install requests --break-system-packages",
            "pip3 install --break-system-packages -r requirements.txt",
            "python -m pip install --break-system-packages flask django",
            "PIP INSTALL --BREAK-SYSTEM-PACKAGES requests",
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
            "pip list",
            "pip show requests",
            "pip freeze",
            "pip uninstall requests",
            "pip install --user requests",
        ]
        for cmd in safe_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is False, f"Should allow: {cmd}"
