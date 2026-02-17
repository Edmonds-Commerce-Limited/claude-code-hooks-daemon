"""Tests for LintOnEditHandler - language-aware lint-on-edit via Strategy Pattern."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler


@pytest.fixture()
def handler() -> LintOnEditHandler:
    return LintOnEditHandler()


class TestInit:
    def test_handler_id(self, handler: LintOnEditHandler) -> None:
        assert handler.handler_id.config_key == "lint_on_edit"

    def test_priority(self, handler: LintOnEditHandler) -> None:
        from claude_code_hooks_daemon.constants import Priority

        assert handler.priority == Priority.LINT_ON_EDIT

    def test_terminal_is_false(self, handler: LintOnEditHandler) -> None:
        assert handler.terminal is False

    def test_has_validation_tag(self, handler: LintOnEditHandler) -> None:
        from claude_code_hooks_daemon.constants import HandlerTag

        assert HandlerTag.VALIDATION in handler.tags

    def test_has_multi_language_tag(self, handler: LintOnEditHandler) -> None:
        from claude_code_hooks_daemon.constants import HandlerTag

        assert HandlerTag.MULTI_LANGUAGE in handler.tags


class TestMatches:
    def test_matches_write_python_file(self, handler: LintOnEditHandler, tmp_path: Path) -> None:
        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_shell_file(self, handler: LintOnEditHandler, tmp_path: Path) -> None:
        test_file = tmp_path / "script.sh"
        test_file.write_text("#!/bin/bash\necho hello")
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_bash_tool(self, handler: LintOnEditHandler) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hello"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_read_tool(self, handler: LintOnEditHandler) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/app.py"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_unknown_extension(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "file.unknown"
        test_file.write_text("content")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_nonexistent_file(self, handler: LintOnEditHandler) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/nonexistent/app.py"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_skip_path(self, handler: LintOnEditHandler, tmp_path: Path) -> None:
        vendor_dir = tmp_path / "vendor"
        vendor_dir.mkdir()
        test_file = vendor_dir / "lib.py"
        test_file.write_text("x = 1")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_node_modules(self, handler: LintOnEditHandler, tmp_path: Path) -> None:
        nm_dir = tmp_path / "node_modules" / "pkg"
        nm_dir.mkdir(parents=True)
        test_file = nm_dir / "index.rb"
        test_file.write_text("puts 'hello'")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_no_file_path(self, handler: LintOnEditHandler) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False


class TestHandle:
    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_handle_lint_passes(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_subprocess.run.return_value = mock_result

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_handle_lint_fails(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "SyntaxError: invalid syntax"
        mock_result.stderr = ""
        mock_subprocess.run.return_value = mock_result

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "deny"
        assert "SyntaxError" in (result.reason or "")

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_handle_timeout(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        import subprocess

        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1")
        mock_subprocess.run.side_effect = subprocess.TimeoutExpired(
            cmd="python", timeout=Timeout.LINT_CHECK
        )
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"
        assert "timed out" in (result.reason or "").lower()

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_handle_file_not_found(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        mock_subprocess.run.side_effect = FileNotFoundError("python not found")

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(tmp_path / "app.py")},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"

    def test_handle_no_file_path(self, handler: LintOnEditHandler) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_handle_extended_lint_runs_if_default_passes(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "script.sh"
        test_file.write_text("#!/bin/bash\necho hello")

        # First call (default lint) passes, second call (extended) also passes
        pass_result = MagicMock()
        pass_result.returncode = 0
        pass_result.stdout = ""
        pass_result.stderr = ""
        mock_subprocess.run.return_value = pass_result

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"
        # Should have called subprocess.run at least twice (default + extended)
        assert mock_subprocess.run.call_count >= 2

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_handle_extended_lint_fails(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "script.sh"
        test_file.write_text("#!/bin/bash\necho hello")

        pass_result = MagicMock()
        pass_result.returncode = 0
        pass_result.stdout = ""
        pass_result.stderr = ""

        fail_result = MagicMock()
        fail_result.returncode = 1
        fail_result.stdout = "SC2086: Double quote to prevent globbing"
        fail_result.stderr = ""

        mock_subprocess.run.side_effect = [pass_result, fail_result]

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "deny"
        assert "SC2086" in (result.reason or "")

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_handle_extended_lint_not_found_allows(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """If extended linter is not installed, allow through gracefully."""
        test_file = tmp_path / "script.sh"
        test_file.write_text("#!/bin/bash\necho hello")

        pass_result = MagicMock()
        pass_result.returncode = 0
        pass_result.stdout = ""
        pass_result.stderr = ""

        mock_subprocess.run.side_effect = [pass_result, FileNotFoundError("shellcheck not found")]

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"


class TestLanguageFilter:
    def test_language_filter_restricts_matching(self, tmp_path: Path) -> None:
        handler = LintOnEditHandler()
        handler._languages = ["Shell"]  # Only Shell

        py_file = tmp_path / "app.py"
        py_file.write_text("x = 1")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(py_file)},
        }
        # Python should be filtered out
        assert handler.matches(hook_input) is False

    def test_language_filter_allows_matching_language(self, tmp_path: Path) -> None:
        handler = LintOnEditHandler()
        handler._languages = ["Shell"]

        sh_file = tmp_path / "script.sh"
        sh_file.write_text("#!/bin/bash\necho hello")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(sh_file)},
        }
        assert handler.matches(hook_input) is True


class TestCommandOverrides:
    """Test command override functionality."""

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_default_command_override(self, mock_subprocess: MagicMock, tmp_path: Path) -> None:
        """Test that default command can be overridden via config."""
        handler = LintOnEditHandler()
        handler._command_overrides = {"Python": {"default": "custom-lint {file}", "extended": None}}

        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_subprocess.run.return_value = mock_result

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"

        # Verify custom command was used (only called once since extended is None)
        assert mock_subprocess.run.call_count == 1
        call_args = mock_subprocess.run.call_args[0][0]
        assert "custom-lint" in call_args[0]

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_extended_command_override(self, mock_subprocess: MagicMock, tmp_path: Path) -> None:
        """Test that extended command can be overridden via config."""
        handler = LintOnEditHandler()
        handler._command_overrides = {"Shell": {"extended": "custom-shellcheck {file}"}}

        test_file = tmp_path / "script.sh"
        test_file.write_text("#!/bin/bash\necho hello")

        pass_result = MagicMock()
        pass_result.returncode = 0
        pass_result.stdout = ""
        pass_result.stderr = ""

        # Default passes, then extended with custom command
        mock_subprocess.run.return_value = pass_result

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"

        # Should call subprocess twice (default + extended)
        assert mock_subprocess.run.call_count >= 2

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_extended_command_disabled_via_null_override(
        self, mock_subprocess: MagicMock, tmp_path: Path
    ) -> None:
        """Test that extended command can be disabled by setting to None."""
        handler = LintOnEditHandler()
        handler._command_overrides = {"Shell": {"extended": None}}

        test_file = tmp_path / "script.sh"
        test_file.write_text("#!/bin/bash\necho hello")

        pass_result = MagicMock()
        pass_result.returncode = 0
        pass_result.stdout = ""
        pass_result.stderr = ""
        mock_subprocess.run.return_value = pass_result

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"

        # Should only call default lint (extended disabled)
        assert mock_subprocess.run.call_count == 1


class TestEdgeCases:
    """Test edge cases and error paths."""

    def test_apply_language_filter_called_only_once(self, tmp_path: Path) -> None:
        """Test that language filter is applied only once (lazy initialization)."""
        handler = LintOnEditHandler()
        handler._languages = ["Python"]

        # First call should apply filter
        py_file = tmp_path / "app.py"
        py_file.write_text("x = 1")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(py_file)},
        }
        handler.matches(hook_input)
        assert handler._languages_applied is True

        # Second call should return early (line 68)
        handler.matches(hook_input)
        # If we get here without error, early return worked

    def test_handle_unknown_file_extension_returns_allow(self, handler: LintOnEditHandler) -> None:
        """Test that handle returns ALLOW for unknown file extensions."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/unknown.xyz"},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_lint_error_with_both_stdout_and_stderr(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Test that both stdout and stderr are included in error message."""
        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "Error in stdout"
        mock_result.stderr = "Error in stderr"
        mock_subprocess.run.return_value = mock_result

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "deny"
        assert "Error in stdout" in (result.reason or "")
        assert "Error in stderr" in (result.reason or "")

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_lint_error_with_only_stderr(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Test that stderr is used when stdout is empty."""
        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error in stderr only"
        mock_subprocess.run.return_value = mock_result

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "deny"
        assert "Error in stderr only" in (result.reason or "")


class TestAcceptanceTests:
    def test_returns_list(self, handler: LintOnEditHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, handler: LintOnEditHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 1
