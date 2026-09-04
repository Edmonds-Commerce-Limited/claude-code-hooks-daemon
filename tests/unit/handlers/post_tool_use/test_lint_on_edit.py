"""Tests for LintOnEditHandler - language-aware lint-on-edit via Strategy Pattern."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from tests.conftest import layout_declaring_vendor_dirs

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


class TestResidentGuidance:
    """A handler that DENIES must say so before it fires, not only when it does.

    Plan 00203 Test 1: a denial burns a turn AND cancels every sibling tool
    call batched with it. This handler denies edits across nine languages and
    was silently inert until v3.52.0 made it actually run — so its denial rate
    rose at the exact moment no project had ever been told it existed.
    """

    def test_provides_guidance(self, handler: LintOnEditHandler) -> None:
        assert handler.get_claude_md() is not None

    def test_states_that_the_write_already_landed(self, handler: LintOnEditHandler) -> None:
        """The single most misleading thing about a PostToolUse denial.

        The file IS on disk before the linter runs, so a denial is a failure
        report, not a rollback. An agent that reads 'blocked' as 'the write
        did not happen' re-creates the file from scratch and loses any content
        it did not have in hand.
        """
        guidance = handler.get_claude_md() or ""

        assert "already" in guidance.lower()
        assert "disk" in guidance.lower() or "written" in guidance.lower()

    def test_names_the_recovery_action(self, handler: LintOnEditHandler) -> None:
        guidance = (handler.get_claude_md() or "").lower()

        assert "edit" in guidance
        assert "fix" in guidance

    def test_states_that_a_missing_linter_never_blocks(self, handler: LintOnEditHandler) -> None:
        """Graceful degradation is invisible unless stated.

        A missing tool ALLOWs with an advisory. Without this, a project seeing
        'lint tool not found' cannot tell whether it is now unprotected or
        about to be blocked.
        """
        guidance = (handler.get_claude_md() or "").lower()

        assert "not installed" in guidance or "not found" in guidance

    def test_points_at_the_config_keys_that_narrow_it(self, handler: LintOnEditHandler) -> None:
        guidance = handler.get_claude_md() or ""

        assert "languages" in guidance
        assert "command_overrides" in guidance


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

    def test_does_not_match_a_declared_vendor_dir(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Plan 00331: the skip set came from each strategy's `skip_paths`,
        which is built from the canonical constant -- so a declared
        `layout.vendor_dirs` never reached it.

        Checked at the HANDLER rather than by threading a layout through all
        13 lint strategies: `skip_paths` is a per-language surface, and
        per-language literals are this plan's explicit Non-Goal.
        """
        role_dir = tmp_path / "infra" / "roles" / "lts.vault"
        role_dir.mkdir(parents=True)
        test_file = role_dir / "task.py"
        test_file.write_text("x = 1")
        handler._project_layout = layout_declaring_vendor_dirs("roles")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is False

    def test_matches_an_undeclared_dir_of_that_name(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """The skip must come from the DECLARATION, not from the name."""
        role_dir = tmp_path / "infra" / "roles" / "lts.vault"
        role_dir.mkdir(parents=True)
        test_file = role_dir / "task.py"
        test_file.write_text("x = 1")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_no_file_path(self, handler: LintOnEditHandler) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_protected_path(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Plan 00272 Task 4-5: a protected file is never lintable, whatever its extension."""
        test_file = tmp_path / "app.protectedmarker.py"
        test_file.write_text("x = 1")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.sfm"
            ".resolve_configured_patterns",
            return_value=("*.protectedmarker*",),
        ):
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
        # Regression test: an ALLOW decision's `reason` is silently dropped by
        # HookResult.to_json() for PostToolUse events - the message MUST be
        # in `context` to actually reach the user.
        assert "timed out" in "\n".join(result.context).lower()
        response = result.to_json("PostToolUse")
        assert "timed out" in response["hookSpecificOutput"]["additionalContext"].lower()

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

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_handle_rustup_clippy_shim_not_installed_allows(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Acceptance Test 128 (cycle 2) regression.

        Rustup's clippy-driver shim resolves on PATH and runs successfully
        (no FileNotFoundError) even when the clippy component is absent, then
        exits non-zero reporting that -- it must degrade to an advisory
        ALLOW, not deny a valid file.
        """
        test_file = tmp_path / "valid.rs"
        test_file.write_text("pub fn hello() {}")

        pass_result = MagicMock()
        pass_result.returncode = 0
        pass_result.stdout = ""
        pass_result.stderr = ""

        fail_result = MagicMock()
        fail_result.returncode = 1
        fail_result.stdout = ""
        toolchain_name = "stable-x86_64-unknown-linux-gnu"
        fail_result.stderr = (
            "error: 'clippy-driver' is not installed for the " f"toolchain '{toolchain_name}'.\n"
        )

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        first_result, second_result = pass_result, fail_result
        mock_subprocess.run.side_effect = (first_result, second_result)

        result = handler.handle(hook_input)
        assert result.decision.value == "allow"

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_handle_real_clippy_finding_still_denies(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """A real clippy installation's genuine findings must still deny."""
        test_file = tmp_path / "valid.rs"
        test_file.write_text("pub fn hello() {}")

        pass_result = MagicMock()
        pass_result.returncode = 0
        pass_result.stdout = ""
        pass_result.stderr = ""

        clippy_fail_result = MagicMock()
        clippy_fail_result.returncode = 1
        clippy_fail_result.stdout = ""
        clippy_fail_result.stderr = "error: could not compile due to previous error\n"

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        first_result, second_result = pass_result, clippy_fail_result
        mock_subprocess.run.side_effect = (first_result, second_result)

        result = handler.handle(hook_input)
        assert result.decision.value == "deny"
        assert "could not compile" in (result.reason or "")


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
        """Test that default command can be overridden via config.

        ``custom-lint`` does not exist on this machine, and the handler now
        resolves a tool to a real path before running it (so venv-installed
        linters are found rather than reported missing). The resolver is stubbed
        to pass names through, so this test keeps exercising what it is about —
        that the OVERRIDE is the command that runs — rather than resolution.
        """
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
        with patch.object(handler, "_resolve_executable", side_effect=lambda name, *_: name):
            result = handler.handle(hook_input)
        assert result.decision.value == "allow"

        # Verify custom command was used (only called once since extended is None)
        assert mock_subprocess.run.call_count == 1
        call_args = mock_subprocess.run.call_args[0][0]
        assert "custom-lint" in call_args[0]

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_extended_command_override(self, mock_subprocess: MagicMock, tmp_path: Path) -> None:
        """Test that extended command can be overridden via config.

        Resolver stubbed for the same reason as the default-override test:
        ``custom-shellcheck`` is not installed, and tool resolution now happens
        before execution.
        """
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
        with patch.object(handler, "_resolve_executable", side_effect=lambda name, *_: name):
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


class TestModuleRoot:
    """Test module root detection and Go package-level vetting (Plan 00076 bug fix)."""

    def test_find_module_root_finds_go_mod(self, tmp_path: Path) -> None:
        """_find_module_root walks up to find go.mod."""
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("module example.com/project\n\ngo 1.24\n")
        pkg_dir = tmp_path / "internal" / "github"
        pkg_dir.mkdir(parents=True)
        go_file = pkg_dir / "client.go"
        go_file.write_text("package github\n")

        result = LintOnEditHandler._find_module_root(str(go_file), "go.mod")
        assert result == str(tmp_path)

    def test_find_module_root_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """_find_module_root returns None when marker not found."""
        go_file = tmp_path / "orphan.go"
        go_file.write_text("package main\n")

        result = LintOnEditHandler._find_module_root(str(go_file), "go.mod")
        assert result is None

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_go_lint_uses_module_root_as_cwd(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Go lint commands run with cwd set to module root."""
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("module example.com/project\n\ngo 1.24\n")
        pkg_dir = tmp_path / "internal" / "github"
        pkg_dir.mkdir(parents=True)
        go_file = pkg_dir / "client.go"
        go_file.write_text("package github\n")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_subprocess.run.return_value = mock_result

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(go_file)},
        }
        handler.handle(hook_input)

        call_kwargs = mock_subprocess.run.call_args[1]
        assert call_kwargs.get("cwd") == str(tmp_path)

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_go_lint_uses_package_dir_not_single_file(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Go lint vets the package directory, not a single file."""
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("module example.com/project\n\ngo 1.24\n")
        pkg_dir = tmp_path / "internal" / "github"
        pkg_dir.mkdir(parents=True)
        go_file = pkg_dir / "client.go"
        go_file.write_text("package github\n")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_subprocess.run.return_value = mock_result

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(go_file)},
        }
        handler.handle(hook_input)

        call_args = mock_subprocess.run.call_args[0][0]
        command_str = " ".join(call_args)
        assert "./internal/github/" in command_str
        assert str(go_file) not in command_str

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_non_marker_lint_runs_from_the_files_workspace(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """A language with no module-root marker runs from its own workspace.

        This previously asserted ``cwd is None`` -- i.e. the daemon's own
        working directory. That is wrong for every tool that discovers config
        relative to cwd: a Python file's ruff settings live in ITS workspace's
        pyproject.toml, not wherever the daemon happens to be running (Plan
        00296 Task 2.2). With no manifest above it, the workspace resolves to
        the fallback root, which is what is asserted here.
        """
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
        handler.handle(hook_input)

        call_kwargs = mock_subprocess.run.call_args[1]
        assert call_kwargs.get("cwd") == str(tmp_path)


class TestAcceptanceTests:
    def test_returns_list(self, handler: LintOnEditHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, handler: LintOnEditHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 1


class TestExcludePathsEscape:
    """`lint_on_edit` is the other handler Plan 00150's Non-Goals deferred.

    It DENIES on a lint failure, so a project with generated or vendored sources
    it cannot control had no way to exempt them: unlike the content blockers it
    consulted no `exclude_paths` at all, filtering only by LANGUAGE. Wired here
    alongside `tdd_enforcement` so the deferral is closed in full rather than by
    half (Plan 00251 Phase 2).
    """

    @staticmethod
    def _real_file(tmp_path: Path, *parts: str) -> str:
        """Create the file on disk and return its path.

        `matches()` ends in `Path(file_path).exists()` because PostToolUse runs
        AFTER the write, so a fictional path can never match and a test using one
        would pass for the wrong reason. Establishing the premise rather than
        assuming it is the point — the control tests below fail loudly if this
        stops being true.
        """
        target = tmp_path.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x = 1\n", encoding="utf-8")
        return str(target)

    @staticmethod
    def _write(file_path: str) -> dict:
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": "x = 1\n"},
        }

    def test_matches_an_unexcluded_source_file(self, tmp_path: Path) -> None:
        """Control: the premise — without exclusions it still fires."""
        handler = LintOnEditHandler()
        assert handler.matches(self._write(self._real_file(tmp_path, "src", "thing.py")))

    def test_a_handler_exclude_pattern_stops_it_firing(self, tmp_path: Path) -> None:
        handler = LintOnEditHandler()
        handler._exclude_paths = ["**/generated/**"]
        assert not handler.matches(self._write(self._real_file(tmp_path, "generated", "thing.py")))

    def test_a_project_wide_exclude_pattern_stops_it_firing(self, tmp_path: Path) -> None:
        handler = LintOnEditHandler()
        handler._project_exclude_paths = ["**/generated/**"]
        assert not handler.matches(self._write(self._real_file(tmp_path, "generated", "thing.py")))

    def test_an_exclusion_does_not_exempt_other_paths(self, tmp_path: Path) -> None:
        handler = LintOnEditHandler()
        handler._exclude_paths = ["**/generated/**"]
        assert handler.matches(self._write(self._real_file(tmp_path, "src", "thing.py")))


class TestLintOnEditGetRules:
    """get_rules() (Plan 00116): one rule, language dimension lives in the strategy registry."""

    def test_get_rules_returns_one_rule(self, handler: LintOnEditHandler) -> None:
        assert len(handler.get_rules()) == 1

    def test_get_rules_rule_id_is_constant(self, handler: LintOnEditHandler) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        assert handler.get_rules()[0].rule_id == RuleID.LINT_FAILURE

    def test_get_rules_verbose_is_non_empty(self, handler: LintOnEditHandler) -> None:
        assert handler.get_rules()[0].verbose


class TestLintOnEditEnforcementStatus:
    """get_enforcement_status() (Plan 00296 T4.1): degraded-mode visibility.

    Only the EXTENDED linter is probed -- the built-in default command is
    always available, so its absence is not a degradation worth reporting.
    """

    def test_nominal_when_every_extended_linter_resolves(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        with patch.object(handler, "_resolve_executable", side_effect=lambda name, *_: name):
            assert handler.get_enforcement_status(tmp_path) == []

    def test_reports_unresolvable_extended_linters(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        with patch.object(handler, "_resolve_executable", return_value=None):
            statuses = handler.get_enforcement_status(tmp_path)
        # Every registered strategy with an extended command is unresolved.
        extended_language_count = sum(
            1 for s in handler._registry.strategies() if s.extended_lint_command
        )
        assert extended_language_count > 0
        assert len(statuses) == extended_language_count
        for status in statuses:
            assert "lint_on_edit" in status
            assert "extended linter" in status
            assert str(tmp_path) in status

    def test_respects_language_filter(self, handler: LintOnEditHandler, tmp_path: Path) -> None:
        """A `languages` restriction narrows which strategies are probed."""
        handler._languages = ["Python"]
        with patch.object(handler, "_resolve_executable", return_value=None):
            statuses = handler.get_enforcement_status(tmp_path)
        assert all("Python" in status for status in statuses)


class TestLintOnEditDisclosureLadder:
    """Verbose-first/terse-after per (transcript_path, rule_id) (Plan 00116).

    The dynamic lint tool output is a POST-hoc failure report and must stay
    fully present in BOTH verbose and terse forms -- only the surrounding
    teaching prose goes terse.
    """

    @pytest.fixture(autouse=True)
    def _reset_disclosure_tracker(self):
        from claude_code_hooks_daemon.core import reset_data_layer

        reset_data_layer()
        yield
        reset_data_layer()

    @staticmethod
    def _hook_input(test_file: Path, transcript_path: str | None) -> dict[str, Any]:
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        if transcript_path is not None:
            hook_input["transcript_path"] = transcript_path
        return hook_input

    @staticmethod
    def _failing_subprocess(mock_subprocess: MagicMock) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "SyntaxError: invalid syntax"
        mock_result.stderr = ""
        mock_subprocess.run.return_value = mock_result

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_deny_reason_starts_with_rule_id_prefix(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1")
        self._failing_subprocess(mock_subprocess)
        result = handler.handle(self._hook_input(test_file, "/tmp/transcript-lint-a.jsonl"))
        assert result.reason.startswith(f"BLOCKED [{RuleID.LINT_FAILURE}]")

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_first_fire_is_verbose(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1")
        self._failing_subprocess(mock_subprocess)
        result = handler.handle(self._hook_input(test_file, "/tmp/transcript-lint-b.jsonl"))
        assert "ALREADY landed on disk" in result.reason
        assert "SyntaxError" in result.reason

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_second_fire_same_agent_is_terse_but_keeps_lint_output(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1")
        self._failing_subprocess(mock_subprocess)
        transcript = "/tmp/transcript-lint-c.jsonl"
        handler.handle(self._hook_input(test_file, transcript))
        second = handler.handle(self._hook_input(test_file, transcript))
        assert "ALREADY landed on disk" not in second.reason
        assert "SyntaxError" in second.reason

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_missing_transcript_path_always_verbose(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1")
        self._failing_subprocess(mock_subprocess)
        first = handler.handle(self._hook_input(test_file, None))
        second = handler.handle(self._hook_input(test_file, None))
        assert "ALREADY landed on disk" in first.reason
        assert "ALREADY landed on disk" in second.reason


class TestPerLanguageTimeout:
    """Plan 00309: extended lint timeout is configurable per language.

    Field report: a php-qa-ci extended lint (~5s warm) can exceed the
    hardcoded 15s Timeout.LINT_CHECK when cold/lock-contended, and the
    handler silently ALLOWS on timeout -- exactly the risky runs skip
    linting with no signal. A project must be able to raise the budget for
    one slow language without touching every other language's timeout.
    """

    # A configured per-language budget deliberately larger than the 15s
    # Timeout.LINT_CHECK default these tests contrast against.
    PHP_CONFIGURED_TIMEOUT_SECONDS = 30

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_default_timeout_is_lint_check_constant(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Task 1.1: pin current behaviour -- no option set, default timeout used."""
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
        handler.handle(hook_input)

        called_timeout = mock_subprocess.run.call_args.kwargs["timeout"]
        assert called_timeout == Timeout.LINT_CHECK

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_default_timeout_fires_allow(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Task 1.1: a timeout still ALLOWs -- fail-open semantics unchanged."""
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

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_configured_language_uses_its_own_timeout(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Task 1.2: PHP configured to 30 uses 30 seconds for its lint runs."""
        import subprocess

        handler._timeouts = {"PHP": self.PHP_CONFIGURED_TIMEOUT_SECONDS}

        test_file = tmp_path / "app.php"
        test_file.write_text("<?php echo 'x';")
        mock_subprocess.run.side_effect = subprocess.TimeoutExpired(
            cmd="php", timeout=self.PHP_CONFIGURED_TIMEOUT_SECONDS
        )
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        handler.handle(hook_input)

        called_timeout = mock_subprocess.run.call_args.kwargs["timeout"]
        assert called_timeout == self.PHP_CONFIGURED_TIMEOUT_SECONDS

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_unconfigured_language_stays_at_default_when_others_configured(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Task 1.2: Python unconfigured stays at 15 while PHP is raised to 30."""
        import subprocess

        handler._timeouts = {"PHP": 30}

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
        handler.handle(hook_input)

        called_timeout = mock_subprocess.run.call_args.kwargs["timeout"]
        assert called_timeout == Timeout.LINT_CHECK

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_configured_language_key_is_case_insensitive(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        import subprocess

        handler._timeouts = {"php": self.PHP_CONFIGURED_TIMEOUT_SECONDS}

        test_file = tmp_path / "app.php"
        test_file.write_text("<?php echo 'x';")
        mock_subprocess.run.side_effect = subprocess.TimeoutExpired(
            cmd="php", timeout=self.PHP_CONFIGURED_TIMEOUT_SECONDS
        )
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        handler.handle(hook_input)

        called_timeout = mock_subprocess.run.call_args.kwargs["timeout"]
        assert called_timeout == self.PHP_CONFIGURED_TIMEOUT_SECONDS

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_non_positive_timeout_is_rejected_and_falls_back_to_default(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Task 1.2: validated -- a non-positive number never crashes the handler."""
        import subprocess

        handler._timeouts = {"Python": -5}

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

        called_timeout = mock_subprocess.run.call_args.kwargs["timeout"]
        assert called_timeout == Timeout.LINT_CHECK
        assert result.decision.value == "allow"

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_non_numeric_timeout_is_rejected_and_falls_back_to_default(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        import subprocess

        handler._timeouts = {"Python": "fast"}

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

        called_timeout = mock_subprocess.run.call_args.kwargs["timeout"]
        assert called_timeout == Timeout.LINT_CHECK
        assert result.decision.value == "allow"

    def test_unknown_language_key_warns_but_does_not_crash(
        self, handler: LintOnEditHandler, tmp_path: Path, caplog: Any
    ) -> None:
        """Task 1.2: an unknown language key warns rather than raising."""
        import logging

        handler._timeouts = {"NotARealLanguage": 30}

        with caplog.at_level(logging.WARNING):
            # Any lintable write triggers timeout resolution/validation.
            test_file = tmp_path / "app.py"
            test_file.write_text("x = 1")
            hook_input: dict[str, Any] = {
                "tool_name": "Write",
                "tool_input": {"file_path": str(test_file)},
            }
            with patch(
                "claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess"
            ) as mock_subprocess:
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = ""
                mock_result.stderr = ""
                mock_subprocess.run.return_value = mock_result
                handler.handle(hook_input)

        assert any("NotARealLanguage" in record.message for record in caplog.records)

    @patch("claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess")
    def test_timeout_advisory_names_language_budget_and_config_key(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Task 1.3: a fired timeout becomes visible -- language, budget, config key."""
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

        context = "\n".join(result.context)
        assert "Python" in context
        assert str(Timeout.LINT_CHECK) in context
        assert "handlers.post_tool_use.lint_on_edit.options.timeouts.Python" in context
