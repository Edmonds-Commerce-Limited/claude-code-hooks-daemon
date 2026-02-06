"""Tests for HookResult.configuration_error() factory method.

Plan 00020: Configuration Validation at Daemon Startup
"""

from claude_code_hooks_daemon.core.hook_result import Decision, HookResult


class TestConfigurationErrorFactory:
    """Tests for HookResult.configuration_error() class method."""

    def test_configuration_error_returns_hook_result(self) -> None:
        """configuration_error() should return a HookResult instance."""
        result = HookResult.configuration_error(errors=["Missing required field: version"])
        assert isinstance(result, HookResult)

    def test_configuration_error_decision_is_allow(self) -> None:
        """configuration_error() should use ALLOW decision (fail-open)."""
        result = HookResult.configuration_error(errors=["Missing required field: version"])
        assert result.decision == Decision.ALLOW

    def test_configuration_error_has_reason(self) -> None:
        """configuration_error() should have a descriptive reason."""
        result = HookResult.configuration_error(errors=["Missing required field: version"])
        assert result.reason is not None
        assert "configuration" in result.reason.lower()

    def test_configuration_error_context_contains_errors(self) -> None:
        """configuration_error() context should contain the specific config errors."""
        errors = [
            "Missing required field: version",
            "Invalid handler name 'foo_bar' at 'handlers.pre_tool_use.foo_bar'",
        ]
        result = HookResult.configuration_error(errors=errors)

        context_text = "\n".join(result.context)
        assert "Missing required field: version" in context_text
        assert "foo_bar" in context_text

    def test_configuration_error_context_contains_warning(self) -> None:
        """configuration_error() context should contain a warning about degraded mode."""
        result = HookResult.configuration_error(errors=["Missing required field: version"])
        context_text = "\n".join(result.context)
        assert "WARNING" in context_text or "DEGRADED" in context_text

    def test_configuration_error_context_contains_remediation(self) -> None:
        """configuration_error() context should contain remediation steps."""
        result = HookResult.configuration_error(errors=["Missing required field: version"])
        context_text = "\n".join(result.context)
        # Should tell user to fix config and restart
        assert "hooks-daemon.yaml" in context_text or "restart" in context_text.lower()

    def test_configuration_error_multiple_errors(self) -> None:
        """configuration_error() should handle multiple config errors."""
        errors = [
            "Error 1: missing version",
            "Error 2: bad handler",
            "Error 3: invalid priority",
        ]
        result = HookResult.configuration_error(errors=errors)

        context_text = "\n".join(result.context)
        for error in errors:
            assert error in context_text

    def test_configuration_error_empty_errors_list(self) -> None:
        """configuration_error() should handle empty errors list gracefully."""
        result = HookResult.configuration_error(errors=[])
        assert isinstance(result, HookResult)
        assert result.decision == Decision.ALLOW

    def test_configuration_error_to_json_pre_tool_use(self) -> None:
        """configuration_error() should produce valid PreToolUse JSON."""
        result = HookResult.configuration_error(errors=["Missing required field: version"])
        output = result.to_json("PreToolUse")

        # Should have hookSpecificOutput with additionalContext (allow with context)
        assert "hookSpecificOutput" in output
        assert "additionalContext" in output["hookSpecificOutput"]
        # Should NOT have permissionDecision (it's allow)
        assert "permissionDecision" not in output["hookSpecificOutput"]

    def test_configuration_error_to_json_session_start(self) -> None:
        """configuration_error() should produce valid SessionStart JSON."""
        result = HookResult.configuration_error(errors=["Missing required field: version"])
        output = result.to_json("SessionStart")

        # SessionStart uses systemMessage format
        assert "systemMessage" in output
        assert "hookSpecificOutput" not in output
