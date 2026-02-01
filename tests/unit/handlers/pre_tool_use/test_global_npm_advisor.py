"""Comprehensive tests for GlobalNpmAdvisorHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.global_npm_advisor import (
    GlobalNpmAdvisorHandler,
)


class TestGlobalNpmAdvisorHandler:
    """Test suite for GlobalNpmAdvisorHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return GlobalNpmAdvisorHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'advise-global-npm'."""
        assert handler.name == "advise-global-npm"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 40."""
        assert handler.priority == 40

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be NON-terminal (allows execution)."""
        assert handler.terminal is False

    # matches() - Pattern 1: npm install -g
    def test_matches_npm_install_g(self, handler):
        """Should match 'npm install -g'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install -g typescript"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npm_i_g(self, handler):
        """Should match 'npm i -g' (short form)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm i -g eslint"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npm_install_g_multiple_packages(self, handler):
        """Should match npm install -g with multiple packages."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install -g typescript eslint prettier"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npm_install_g_case_insensitive(self, handler):
        """Should match with different casing."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "NPM INSTALL -G typescript"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 2: yarn global add
    def test_matches_yarn_global_add(self, handler):
        """Should match 'yarn global add'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "yarn global add typescript"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_yarn_global_add_multiple_packages(self, handler):
        """Should match yarn global add with multiple packages."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "yarn global add eslint prettier"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Local installs
    def test_matches_npm_install_without_g_returns_false(self, handler):
        """Should NOT match local 'npm install'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install typescript"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_npm_install_save_dev_returns_false(self, handler):
        """Should NOT match 'npm install --save-dev'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install --save-dev typescript"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_yarn_add_without_global_returns_false(self, handler):
        """Should NOT match local 'yarn add'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "yarn add typescript"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_npx_returns_false(self, handler):
        """Should NOT match 'npx' commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx create-react-app my-app"},
        }
        assert handler.matches(hook_input) is False

    # matches() - Edge Cases
    def test_matches_non_bash_tool_returns_false(self, handler):
        """Should not match non-Bash tools."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.sh",
                "content": "npm install -g typescript",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_empty_command_returns_false(self, handler):
        """Should not match empty command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        assert handler.matches(hook_input) is False

    # handle() Tests - Non-blocking behavior
    def test_handle_returns_allow_decision(self, handler):
        """handle() should return ALLOW (non-blocking)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install -g typescript"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_context_contains_advisory(self, handler):
        """handle() context should contain advisory message."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install -g typescript"},
        }
        result = handler.handle(hook_input)
        assert len(result.context) == 1
        assert "ADVISORY" in result.context[0]

    def test_handle_advisory_mentions_npx(self, handler):
        """handle() advisory should mention npx alternative."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install -g typescript"},
        }
        result = handler.handle(hook_input)
        advisory = result.context[0]
        assert "npx" in advisory

    def test_handle_advisory_includes_package_name(self, handler):
        """handle() advisory should include the package name."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install -g eslint"},
        }
        result = handler.handle(hook_input)
        advisory = result.context[0]
        assert "eslint" in advisory

    def test_handle_advisory_includes_command(self, handler):
        """handle() advisory should include the original command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "yarn global add prettier"},
        }
        result = handler.handle(hook_input)
        advisory = result.context[0]
        assert "yarn global add prettier" in advisory

    def test_handle_reason_is_empty(self, handler):
        """handle() reason should be empty (not blocking)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install -g typescript"},
        }
        result = handler.handle(hook_input)
        assert result.reason == ""

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install -g typescript"},
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    def test_handle_non_matching_command_returns_allow_silently(self, handler):
        """handle() should return ALLOW without context for non-matching."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install typescript"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.context == []

    # Integration Tests
    def test_advises_on_all_global_install_variants(self, handler):
        """Should provide advice for all global install patterns."""
        global_commands = [
            "npm install -g typescript",
            "npm i -g eslint",
            "yarn global add prettier",
            "npm install -g typescript eslint",
            "NPM INSTALL -G typescript",
        ]
        for cmd in global_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is True, f"Should match: {cmd}"
            result = handler.handle(hook_input)
            assert result.decision == "allow", f"Should allow: {cmd}"
            assert len(result.context) == 1, f"Should have advisory: {cmd}"

    def test_allows_all_local_npm_commands_silently(self, handler):
        """Should allow local npm commands without advisory."""
        local_commands = [
            "npm install typescript",
            "npm install --save-dev eslint",
            "yarn add prettier",
            "npx create-react-app my-app",
        ]
        for cmd in local_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is False, f"Should not match: {cmd}"
            result = handler.handle(hook_input)
            assert result.decision == "allow", f"Should allow: {cmd}"
            assert result.context == [], f"Should have no advisory: {cmd}"
