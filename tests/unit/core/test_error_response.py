"""Tests for error_response CLI utility."""

import json
import subprocess
import sys

import pytest

from claude_code_hooks_daemon.core.error_response import generate_daemon_error_response
from claude_code_hooks_daemon.core.response_schemas import validate_response


class TestGenerateDaemonErrorResponse:
    """Tests for generate_daemon_error_response function."""

    def test_stop_event_format(self) -> None:
        """Stop events should use decision/reason format, not hookSpecificOutput."""
        response = generate_daemon_error_response(
            "Stop", "daemon_startup_failed", "Failed to start daemon"
        )

        # Should have top-level decision and reason
        assert "decision" in response
        assert response["decision"] == "block"
        assert "reason" in response
        assert "not running" in response["reason"].lower()

        # Should NOT have hookSpecificOutput
        assert "hookSpecificOutput" not in response

        # Validate against schema
        errors = validate_response("Stop", response)
        assert not errors, f"Schema validation failed: {errors}"

    def test_subagent_stop_event_format(self) -> None:
        """SubagentStop events should use same format as Stop."""
        response = generate_daemon_error_response(
            "SubagentStop", "daemon_startup_failed", "Failed to start daemon"
        )

        # Should have top-level decision and reason
        assert "decision" in response
        assert response["decision"] == "block"
        assert "reason" in response

        # Should NOT have hookSpecificOutput
        assert "hookSpecificOutput" not in response

        # Validate against schema
        errors = validate_response("SubagentStop", response)
        assert not errors, f"Schema validation failed: {errors}"

    def test_pre_tool_use_format(self) -> None:
        """PreToolUse events should use hookSpecificOutput format."""
        response = generate_daemon_error_response(
            "PreToolUse", "daemon_startup_failed", "Failed to start daemon"
        )

        # Should have hookSpecificOutput
        assert "hookSpecificOutput" in response
        assert response["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "additionalContext" in response["hookSpecificOutput"]

        # Context should contain error details
        context = response["hookSpecificOutput"]["additionalContext"]
        assert "daemon_startup_failed" in context
        assert "Failed to start daemon" in context
        assert "PROTECTION NOT ACTIVE" in context

        # Validate against schema
        errors = validate_response("PreToolUse", response)
        assert not errors, f"Schema validation failed: {errors}"

    def test_post_tool_use_format(self) -> None:
        """PostToolUse events should use hookSpecificOutput format."""
        response = generate_daemon_error_response("PostToolUse", "socket_timeout", "Socket timeout")

        # Should have hookSpecificOutput
        assert "hookSpecificOutput" in response
        assert response["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        assert "additionalContext" in response["hookSpecificOutput"]

        # Context should contain error details
        context = response["hookSpecificOutput"]["additionalContext"]
        assert "socket_timeout" in context
        assert "Socket timeout" in context

        # Validate against schema
        errors = validate_response("PostToolUse", response)
        assert not errors, f"Schema validation failed: {errors}"

    def test_user_prompt_submit_format(self) -> None:
        """UserPromptSubmit events should use hookSpecificOutput format."""
        response = generate_daemon_error_response(
            "UserPromptSubmit", "connection_refused", "Connection refused"
        )

        # Should have hookSpecificOutput
        assert "hookSpecificOutput" in response
        assert response["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        assert "additionalContext" in response["hookSpecificOutput"]

        # Validate against schema
        errors = validate_response("UserPromptSubmit", response)
        assert not errors, f"Schema validation failed: {errors}"

    def test_session_start_format(self) -> None:
        """SessionStart events should use hookSpecificOutput format."""
        response = generate_daemon_error_response(
            "SessionStart", "init_path_error", "Could not find .claude directory"
        )

        # Should have hookSpecificOutput
        assert "hookSpecificOutput" in response
        assert response["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "additionalContext" in response["hookSpecificOutput"]

        # Validate against schema
        errors = validate_response("SessionStart", response)
        assert not errors, f"Schema validation failed: {errors}"

    def test_error_context_content(self) -> None:
        """Error context should contain all critical information."""
        response = generate_daemon_error_response(
            "PreToolUse", "daemon_startup_failed", "Failed to start daemon"
        )

        context = response["hookSpecificOutput"]["additionalContext"]

        # Should contain all critical warnings
        assert "PROTECTION NOT ACTIVE" in context
        assert "CRITICAL" in context
        assert "stop work immediately" in context.lower()

        # Should contain error details
        assert "daemon_startup_failed" in context
        assert "Failed to start daemon" in context

        # Should contain specific risks
        assert "Destructive git operations are NOT being blocked" in context
        assert "Code quality checks are NOT running" in context
        assert "Safety guardrails are NOT active" in context

        # Should contain remediation steps
        assert "python -m claude_code_hooks_daemon.daemon.cli status" in context
        assert "python -m claude_code_hooks_daemon.daemon.cli logs" in context
        assert "python -m claude_code_hooks_daemon.daemon.cli restart" in context


class TestErrorResponseCLI:
    """Tests for CLI entry point."""

    def test_cli_stop_event(self) -> None:
        """CLI should generate valid Stop event JSON."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_code_hooks_daemon.core.error_response",
                "Stop",
                "daemon_startup_failed",
                "Failed to start daemon",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Should output valid JSON
        response = json.loads(result.stdout)

        # Should match Stop event format
        assert "decision" in response
        assert response["decision"] == "block"
        assert "reason" in response
        assert "hookSpecificOutput" not in response

        # Validate against schema
        errors = validate_response("Stop", response)
        assert not errors, f"Schema validation failed: {errors}"

    def test_cli_pre_tool_use_event(self) -> None:
        """CLI should generate valid PreToolUse event JSON."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_code_hooks_daemon.core.error_response",
                "PreToolUse",
                "socket_timeout",
                "Socket timeout (30s)",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Should output valid JSON
        response = json.loads(result.stdout)

        # Should match PreToolUse event format
        assert "hookSpecificOutput" in response
        assert response["hookSpecificOutput"]["hookEventName"] == "PreToolUse"

        # Validate against schema
        errors = validate_response("PreToolUse", response)
        assert not errors, f"Schema validation failed: {errors}"

    def test_cli_missing_args(self) -> None:
        """CLI should error if required args missing."""
        result = subprocess.run(
            [sys.executable, "-m", "claude_code_hooks_daemon.core.error_response"],
            capture_output=True,
            text=True,
        )

        # Should exit with error
        assert result.returncode != 0
        assert "Usage:" in result.stderr

    def test_cli_with_special_characters(self) -> None:
        """CLI should handle special characters in error details."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_code_hooks_daemon.core.error_response",
                "Stop",
                "error_type",
                'Error with "quotes" and\nnewlines',
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Should output valid JSON despite special characters
        response = json.loads(result.stdout)
        assert "decision" in response

        # Validate against schema
        errors = validate_response("Stop", response)
        assert not errors, f"Schema validation failed: {errors}"


class TestAllEventTypes:
    """Comprehensive tests for all event types."""

    @pytest.mark.parametrize(
        "event_name",
        [
            "PreToolUse",
            "PostToolUse",
            "Stop",
            "SubagentStop",
            "SessionStart",
            "SessionEnd",
            "PreCompact",
            "UserPromptSubmit",
            "Notification",
            "PermissionRequest",
        ],
    )
    def test_all_events_generate_valid_json(self, event_name: str) -> None:
        """All event types should generate schema-valid JSON."""
        response = generate_daemon_error_response(event_name, "test_error", "Test error details")

        # Should be a dict
        assert isinstance(response, dict)

        # Should validate against event schema
        errors = validate_response(event_name, response)
        assert not errors, f"Schema validation failed for {event_name}: {errors}"

    @pytest.mark.parametrize(
        "event_name,should_have_hook_specific",
        [
            ("Stop", False),
            ("SubagentStop", False),
            ("PreToolUse", True),
            ("PostToolUse", True),
            ("SessionStart", True),
            ("UserPromptSubmit", True),
        ],
    )
    def test_hook_specific_output_presence(
        self, event_name: str, should_have_hook_specific: bool
    ) -> None:
        """Verify hookSpecificOutput presence based on event type."""
        response = generate_daemon_error_response(event_name, "test_error", "Test details")

        if should_have_hook_specific:
            assert "hookSpecificOutput" in response
        else:
            assert "hookSpecificOutput" not in response


class TestMainFunction:
    """Tests for main() function."""

    def test_main_with_correct_args(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() should generate JSON output when called with correct args."""
        monkeypatch.setattr(
            sys, "argv", ["error_response.py", "PreToolUse", "test_error", "Test error message"]
        )

        from claude_code_hooks_daemon.core.error_response import main

        main()

        captured = capsys.readouterr()
        # Should output valid JSON
        response = json.loads(captured.out)
        assert "hookSpecificOutput" in response

    def test_main_with_stop_event(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() should handle Stop events correctly."""
        monkeypatch.setattr(
            sys, "argv", ["error_response.py", "Stop", "daemon_error", "Daemon failed"]
        )

        from claude_code_hooks_daemon.core.error_response import main

        main()

        captured = capsys.readouterr()
        response = json.loads(captured.out)
        assert "decision" in response
        assert response["decision"] == "block"

    def test_main_with_insufficient_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() should exit with error if insufficient args."""
        monkeypatch.setattr(sys, "argv", ["error_response.py", "PreToolUse"])

        from claude_code_hooks_daemon.core.error_response import main

        with pytest.raises(SystemExit) as excinfo:
            main()

        assert excinfo.value.code == 1

    def test_main_with_no_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() should exit with error if no args."""
        monkeypatch.setattr(sys, "argv", ["error_response.py"])

        from claude_code_hooks_daemon.core.error_response import main

        with pytest.raises(SystemExit) as excinfo:
            main()

        assert excinfo.value.code == 1

    def test_main_prints_usage_on_error(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() should print usage message when args are incorrect."""
        monkeypatch.setattr(sys, "argv", ["error_response.py", "only-one-arg"])

        from claude_code_hooks_daemon.core.error_response import main

        with pytest.raises(SystemExit):
            main()

        captured = capsys.readouterr()
        assert "Usage:" in captured.err
        assert "error_response" in captured.err
