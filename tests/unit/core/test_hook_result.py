"""Comprehensive tests for HookResult."""

from claude_code_hooks_daemon.core.hook_result import Decision, HookResult


class TestHookResultInit:
    """Test HookResult initialization."""

    def test_init_with_defaults(self):
        """Should initialize with default values."""
        result = HookResult()
        assert result.decision == Decision.ALLOW
        assert result.reason is None
        assert result.context == []  # Now defaults to empty list
        assert result.guidance is None

    def test_init_with_decision_only(self):
        """Should initialize with only decision parameter."""
        result = HookResult(decision=Decision.DENY)
        assert result.decision == Decision.DENY
        assert result.reason is None
        assert result.context == []  # Now defaults to empty list
        assert result.guidance is None

    def test_init_with_all_parameters(self):
        """Should initialize with all parameters."""
        result = HookResult(
            decision=Decision.ASK,
            reason="Need confirmation",
            context="Additional info",  # String is coerced to list
            guidance="Suggested action",
        )
        assert result.decision == Decision.ASK
        assert result.reason == "Need confirmation"
        assert result.context == ["Additional info"]  # Coerced to list
        assert result.guidance == "Suggested action"

    def test_init_with_deny_and_reason(self):
        """Should initialize deny with reason."""
        result = HookResult(decision=Decision.DENY, reason="Operation blocked")
        assert result.decision == Decision.DENY
        assert result.reason == "Operation blocked"

    def test_init_with_allow_and_context(self):
        """Should initialize allow with context."""
        result = HookResult(decision=Decision.ALLOW, context="Helpful info")
        assert result.decision == Decision.ALLOW
        assert result.context == ["Helpful info"]  # Coerced to list

    def test_init_with_allow_and_guidance(self):
        """Should initialize allow with guidance."""
        result = HookResult(decision=Decision.ALLOW, guidance="Consider this...")
        assert result.decision == Decision.ALLOW
        assert result.guidance == "Consider this..."


class TestToJsonSilentAllow:
    """Test to_json() with silent allow (empty JSON)."""

    def test_to_json_silent_allow_returns_empty_dict(self):
        """Silent allow should return empty dict."""
        result = HookResult(decision=Decision.ALLOW)
        output = result.to_json("PreToolUse")
        assert output == {}

    def test_to_json_allow_without_context_or_guidance(self):
        """Allow without context/guidance should return empty dict."""
        result = HookResult(decision=Decision.ALLOW, reason=None, context=None, guidance=None)
        output = result.to_json("PreToolUse")
        assert output == {}

    def test_to_json_allow_with_none_values(self):
        """Allow with explicit None values should return empty dict."""
        result = HookResult(decision=Decision.ALLOW, reason=None, context=None, guidance=None)
        output = result.to_json("PostToolUse")
        assert output == {}


class TestToJsonDenyDecision:
    """Test to_json() with deny decision."""

    def test_to_json_deny_without_reason(self):
        """Deny without reason should include decision."""
        result = HookResult(decision=Decision.DENY)
        output = result.to_json("PreToolUse")

        assert "hookSpecificOutput" in output
        assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert output["hookSpecificOutput"]["permissionDecision"] == Decision.DENY
        assert "permissionDecisionReason" not in output["hookSpecificOutput"]

    def test_to_json_deny_with_reason(self):
        """Deny with reason should include both decision and reason."""
        result = HookResult(decision=Decision.DENY, reason="Operation blocked")
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["permissionDecision"] == Decision.DENY
        assert output["hookSpecificOutput"]["permissionDecisionReason"] == "Operation blocked"

    def test_to_json_deny_with_reason_and_context(self):
        """Deny with reason and context should include all fields."""
        result = HookResult(decision=Decision.DENY, reason="Blocked", context="Extra info")
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["permissionDecision"] == Decision.DENY
        assert output["hookSpecificOutput"]["permissionDecisionReason"] == "Blocked"
        assert output["hookSpecificOutput"]["additionalContext"] == "Extra info"

    def test_to_json_deny_with_guidance(self):
        """Deny can include guidance field."""
        result = HookResult(decision=Decision.DENY, reason="Blocked", guidance="Try this instead")
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["permissionDecision"] == Decision.DENY
        assert output["hookSpecificOutput"]["guidance"] == "Try this instead"

    def test_to_json_deny_multiline_reason(self):
        """Deny with multiline reason should preserve formatting."""
        reason = "Line 1\nLine 2\nLine 3"
        result = HookResult(decision=Decision.DENY, reason=reason)
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["permissionDecisionReason"] == reason


class TestToJsonAskDecision:
    """Test to_json() with ask decision."""

    def test_to_json_ask_without_reason(self):
        """Ask without reason should include decision."""
        result = HookResult(decision=Decision.ASK)
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["permissionDecision"] == Decision.ASK
        assert "permissionDecisionReason" not in output["hookSpecificOutput"]

    def test_to_json_ask_with_reason(self):
        """Ask with reason should include both decision and reason."""
        result = HookResult(decision=Decision.ASK, reason="Needs confirmation")
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["permissionDecision"] == Decision.ASK
        assert output["hookSpecificOutput"]["permissionDecisionReason"] == "Needs confirmation"

    def test_to_json_ask_with_context(self):
        """Ask with context should include additionalContext."""
        result = HookResult(decision=Decision.ASK, reason="Confirm?", context="Details here")
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["permissionDecision"] == Decision.ASK
        assert output["hookSpecificOutput"]["additionalContext"] == "Details here"

    def test_to_json_ask_with_guidance(self):
        """Ask with guidance should include guidance field."""
        result = HookResult(
            decision=Decision.ASK, reason="Confirm", guidance="Recommended approach"
        )
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["guidance"] == "Recommended approach"

    def test_to_json_ask_with_all_fields(self):
        """Ask with all fields should include everything."""
        result = HookResult(
            decision=Decision.ASK,
            reason="Need approval",
            context="Context info",
            guidance="Guidance text",
        )
        output = result.to_json("PreToolUse")

        hso = output["hookSpecificOutput"]
        assert hso["permissionDecision"] == Decision.ASK
        assert hso["permissionDecisionReason"] == "Need approval"
        assert hso["additionalContext"] == "Context info"
        assert hso["guidance"] == "Guidance text"


class TestToJsonContext:
    """Test to_json() with context field."""

    def test_to_json_allow_with_context(self):
        """Allow with context should include additionalContext."""
        result = HookResult(decision=Decision.ALLOW, context="Helpful information")
        output = result.to_json("PreToolUse")

        assert "hookSpecificOutput" in output
        assert output["hookSpecificOutput"]["additionalContext"] == "Helpful information"
        assert "permissionDecision" not in output["hookSpecificOutput"]

    def test_to_json_context_multiline(self):
        """Context with multiple lines should preserve formatting."""
        context = "Line 1\n\nLine 2\n\nLine 3"
        result = HookResult(decision=Decision.ALLOW, context=context)
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["additionalContext"] == context

    def test_to_json_context_with_special_characters(self):
        """Context with special characters should be preserved."""
        context = "Special: \t\n\r 'quotes' \"double\" \\ backslash"
        result = HookResult(decision=Decision.ALLOW, context=context)
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["additionalContext"] == context

    def test_to_json_deny_with_context_no_reason(self):
        """Deny with context but no reason."""
        result = HookResult(decision=Decision.DENY, context="Additional info")
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["permissionDecision"] == Decision.DENY
        assert output["hookSpecificOutput"]["additionalContext"] == "Additional info"
        assert "permissionDecisionReason" not in output["hookSpecificOutput"]


class TestToJsonGuidance:
    """Test to_json() with guidance field."""

    def test_to_json_allow_with_guidance(self):
        """Allow with guidance should include guidance field."""
        result = HookResult(decision=Decision.ALLOW, guidance="Consider this approach")
        output = result.to_json("PreToolUse")

        assert "hookSpecificOutput" in output
        assert output["hookSpecificOutput"]["guidance"] == "Consider this approach"
        assert "permissionDecision" not in output["hookSpecificOutput"]

    def test_to_json_guidance_multiline(self):
        """Guidance with multiple lines should preserve formatting."""
        guidance = "Step 1: Do this\nStep 2: Do that\nStep 3: Done"
        result = HookResult(decision=Decision.ALLOW, guidance=guidance)
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["guidance"] == guidance

    def test_to_json_allow_with_context_and_guidance(self):
        """Allow with both context and guidance should include both."""
        result = HookResult(
            decision=Decision.ALLOW,
            context="Background info",
            guidance="Recommended action",
        )
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["additionalContext"] == "Background info"
        assert output["hookSpecificOutput"]["guidance"] == "Recommended action"

    def test_to_json_guidance_empty_string_not_included(self):
        """Empty guidance string is falsy, so not included."""
        result = HookResult(decision=Decision.ALLOW, guidance="")
        output = result.to_json("PreToolUse")

        # Empty string is falsy, so silent allow
        assert output == {}


class TestToJsonEventName:
    """Test to_json() with different event names."""

    def test_to_json_includes_event_name(self):
        """Output should include hookEventName."""
        result = HookResult(decision=Decision.DENY, reason="Blocked")
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"

    def test_to_json_different_event_names(self):
        """Should work with different event names and event-specific formats."""
        # Test PreToolUse format (hookSpecificOutput with permissionDecision)
        result = HookResult(decision=Decision.DENY, reason="Test")
        output = result.to_json("PreToolUse")
        assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert output["hookSpecificOutput"]["permissionDecision"] == Decision.DENY

        # Test PostToolUse format (top-level decision, hookSpecificOutput only if context present)
        output = result.to_json("PostToolUse")
        assert output["decision"] == "block"
        # No hookSpecificOutput if no context (valid PostToolUse response)

        # Test PostToolUse with context
        result_with_context = HookResult(
            decision=Decision.DENY, reason="Test", context=["Error details"]
        )
        output = result_with_context.to_json("PostToolUse")
        assert output["decision"] == "block"
        assert output["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        assert output["hookSpecificOutput"]["additionalContext"] == "Error details"

        # Test Stop format (top-level decision only, no hookSpecificOutput)
        output = result.to_json("Stop")
        assert output["decision"] == "block"
        assert "hookSpecificOutput" not in output

        # Test SessionStart format (systemMessage only, NOT hookSpecificOutput)
        result_session = HookResult(decision=Decision.ALLOW, context=["Test context"])
        output = result_session.to_json("SessionStart")
        assert "systemMessage" in output
        assert output["systemMessage"] == "Test context"
        assert "hookSpecificOutput" not in output

    def test_to_json_silent_allow_no_event_name(self):
        """Silent allow should not include hookEventName (empty dict)."""
        result = HookResult(decision=Decision.ALLOW)
        output = result.to_json("PreToolUse")

        assert output == {}  # No hookSpecificOutput at all


class TestToJsonEdgeCases:
    """Test to_json() edge cases."""

    def test_to_json_empty_reason_not_included(self):
        """Empty string reason should not be included."""
        result = HookResult(decision=Decision.DENY, reason="")
        output = result.to_json("PreToolUse")

        assert "permissionDecisionReason" not in output["hookSpecificOutput"]

    def test_to_json_empty_context_not_included(self):
        """Empty string context should not trigger output."""
        result = HookResult(decision=Decision.ALLOW, context="")
        output = result.to_json("PreToolUse")

        # Empty context is falsy, so no output
        assert output == {}

    def test_to_json_allow_with_reason_ignored(self):
        """Allow decision should not include reason (not in spec)."""
        result = HookResult(decision=Decision.ALLOW, reason="This is ignored")
        output = result.to_json("PreToolUse")

        # Silent allow (reason not used)
        assert output == {}

    def test_to_json_whitespace_only_context(self):
        """Whitespace-only context should be included (not filtered)."""
        result = HookResult(decision=Decision.ALLOW, context="   \n\n   ")
        output = result.to_json("PreToolUse")

        # Truthy, so should create output
        assert "hookSpecificOutput" in output
        assert output["hookSpecificOutput"]["additionalContext"] == "   \n\n   "

    def test_to_json_unicode_characters(self):
        """Should handle unicode characters in strings."""
        result = HookResult(
            decision=Decision.DENY,
            reason="⚠️ Warning: blocked",
            context="Context with emoji 🔒",
            guidance="Guidance with unicode: ✅",
        )
        output = result.to_json("PreToolUse")

        assert "⚠️" in output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "🔒" in output["hookSpecificOutput"]["additionalContext"]
        assert "✅" in output["hookSpecificOutput"]["guidance"]


class TestHookResultIntegration:
    """Integration tests for HookResult usage patterns."""

    def test_typical_deny_workflow(self):
        """Typical deny workflow with reason."""
        result = HookResult(decision=Decision.DENY, reason="Git operation not allowed")
        output = result.to_json("PreToolUse")

        assert output["hookSpecificOutput"]["permissionDecision"] == Decision.DENY
        assert "Git operation" in output["hookSpecificOutput"]["permissionDecisionReason"]

    def test_typical_guidance_workflow(self):
        """Typical guidance workflow (allow with feedback)."""
        result = HookResult(
            decision=Decision.ALLOW,
            guidance="Consider using relative paths instead of absolute paths",
        )
        output = result.to_json("PreToolUse")

        assert "hookSpecificOutput" in output
        assert "permissionDecision" not in output["hookSpecificOutput"]
        assert "relative paths" in output["hookSpecificOutput"]["guidance"]

    def test_typical_context_workflow(self):
        """Typical context workflow (allow with information)."""
        result = HookResult(
            decision=Decision.ALLOW,
            context="Detected plan workflow. Make sure to update PLAN.md",
        )
        output = result.to_json("SessionStart")

        assert "systemMessage" in output
        assert "PLAN.md" in output["systemMessage"]
        assert "hookSpecificOutput" not in output

    def test_deny_with_guidance_and_context(self):
        """Complex deny with guidance and context."""
        result = HookResult(
            decision=Decision.DENY,
            reason="TDD violation: Test file missing",
            context="Handler: example_handler.py\nTest file: test_example_handler.py (NOT FOUND)",
            guidance="Create test file first following TDD workflow",
        )
        output = result.to_json("PreToolUse")

        hso = output["hookSpecificOutput"]
        assert hso["permissionDecision"] == Decision.DENY
        assert "TDD violation" in hso["permissionDecisionReason"]
        assert "test_example_handler.py" in hso["additionalContext"]
        assert "Create test file" in hso["guidance"]


class TestHookResultCoercionValidation:
    """Test field validation and coercion."""

    def test_coerce_decision_with_invalid_type(self):
        """Should raise ValueError for invalid decision type."""
        import pytest

        with pytest.raises(ValueError, match="Invalid decision"):
            HookResult(decision=123)  # type: ignore

    def test_coerce_decision_with_string(self):
        """Should coerce string decision to Decision enum."""
        result = HookResult(decision=Decision.ALLOW)
        assert result.decision == Decision.ALLOW

    def test_coerce_decision_with_enum(self):
        """Should accept Decision enum directly."""
        from claude_code_hooks_daemon.core.hook_result import Decision

        result = HookResult(decision=Decision.DENY)
        assert result.decision == Decision.DENY


class TestHookResultChaining:
    """Test method chaining functionality."""

    def test_add_context_single_line(self):
        """Should add single context line and return self."""
        result = HookResult(decision=Decision.ALLOW)
        returned = result.add_context("Line 1")

        assert returned is result  # Returns self for chaining
        assert result.context == ["Line 1"]

    def test_add_context_multiple_lines(self):
        """Should add multiple context lines."""
        result = HookResult(decision=Decision.ALLOW)
        result.add_context("Line 1", "Line 2", "Line 3")

        assert result.context == ["Line 1", "Line 2", "Line 3"]

    def test_add_context_chaining(self):
        """Should support method chaining."""
        result = (
            HookResult(decision=Decision.ALLOW)
            .add_context("Line 1")
            .add_context("Line 2")
            .add_context("Line 3")
        )

        assert result.context == ["Line 1", "Line 2", "Line 3"]

    def test_merge_context_from_other_result(self):
        """Should merge context and handlers from another result."""
        result1 = HookResult(decision=Decision.ALLOW, context=["Line 1"])
        result1.handlers_matched.append("handler1")

        result2 = HookResult(decision=Decision.ALLOW, context=["Line 2"])
        result2.handlers_matched.append("handler2")

        returned = result1.merge_context(result2)

        assert returned is result1  # Returns self for chaining
        assert result1.context == ["Line 1", "Line 2"]
        assert "handler1" in result1.handlers_matched
        assert "handler2" in result1.handlers_matched

    def test_merge_context_avoids_duplicate_handlers(self):
        """Should not duplicate handlers when merging."""
        result1 = HookResult(decision=Decision.ALLOW)
        result1.handlers_matched.append("handler1")

        result2 = HookResult(decision=Decision.ALLOW)
        result2.handlers_matched.extend(["handler1", "handler2"])

        result1.merge_context(result2)

        # handler1 should appear only once
        assert result1.handlers_matched.count("handler1") == 1
        assert "handler2" in result1.handlers_matched


class TestHookResultFactoryMethods:
    """Test factory method constructors."""

    def test_ask_factory_creates_ask_result(self):
        """HookResult.ask() should create ask decision result."""
        result = HookResult.ask("Need confirmation")

        assert result.decision == Decision.ASK
        assert result.reason == "Need confirmation"
        assert result.context == []

    def test_ask_factory_with_context(self):
        """HookResult.ask() should accept optional context."""
        result = HookResult.ask("Need confirmation", context=["Detail 1", "Detail 2"])

        assert result.decision == Decision.ASK
        assert result.reason == "Need confirmation"
        assert result.context == ["Detail 1", "Detail 2"]


class TestHookResultPostToolUseFormat:
    """Test PostToolUse-specific response format."""

    def test_post_tool_use_deny_with_guidance(self):
        """PostToolUse deny should support guidance field."""
        result = HookResult(
            decision=Decision.DENY, reason="Error detected", guidance="Fix the error"
        )
        output = result.to_json("PostToolUse")

        assert output["decision"] == "block"
        assert output["reason"] == "Error detected"
        assert output["hookSpecificOutput"]["guidance"] == "Fix the error"

    def test_post_tool_use_allow_with_guidance(self):
        """PostToolUse allow should support guidance field."""
        result = HookResult(decision=Decision.ALLOW, guidance="Consider optimizing")
        output = result.to_json("PostToolUse")

        assert "decision" not in output
        assert output["hookSpecificOutput"]["guidance"] == "Consider optimizing"


class TestHookResultPermissionRequestFormat:
    """Test PermissionRequest-specific response format."""

    def test_permission_request_with_guidance(self):
        """PermissionRequest should support guidance field."""
        result = HookResult(
            decision=Decision.ALLOW, context=["File access"], guidance="Use read-only mode"
        )
        output = result.to_json("PermissionRequest")

        hso = output["hookSpecificOutput"]
        assert hso["decision"]["behavior"] == Decision.ALLOW
        assert hso["additionalContext"] == "File access"
        assert hso["guidance"] == "Use read-only mode"


class TestHookResultContextOnlyFormat:
    """Test context-only event response format (systemMessage based)."""

    def test_context_only_with_guidance(self):
        """SessionStart/SessionEnd/PreCompact/Notification use systemMessage (NOT hookSpecificOutput)."""
        result = HookResult(
            decision=Decision.ALLOW, context=["Session info"], guidance="Remember to commit"
        )
        output = result.to_json("SessionStart")

        # Should use systemMessage, NOT hookSpecificOutput
        assert "systemMessage" in output
        assert "Session info" in output["systemMessage"]
        assert "Remember to commit" in output["systemMessage"]
        assert "hookSpecificOutput" not in output

    def test_context_only_notification_with_guidance(self):
        """Notification event should use systemMessage (NOT hookSpecificOutput)."""
        result = HookResult(decision=Decision.ALLOW, guidance="Check logs for details")
        output = result.to_json("Notification")

        # Should use systemMessage, NOT hookSpecificOutput
        assert "systemMessage" in output
        assert "Check logs for details" in output["systemMessage"]
        assert "hookSpecificOutput" not in output


class TestHookResultContextOnlyDenyFormat:
    """Test context-only response formatting with DENY decision."""

    def test_context_only_deny_returns_invalid_response(self):
        """UserPromptSubmit with DENY returns invalid response for schema validation."""
        result = HookResult(decision=Decision.DENY, reason="Blocked prompt")
        output = result.to_json("UserPromptSubmit")

        # Should return hookSpecificOutput with permissionDecision (invalid for context-only)
        assert "hookSpecificOutput" in output
        assert output["hookSpecificOutput"]["permissionDecision"] == Decision.DENY
        assert output["hookSpecificOutput"]["permissionDecisionReason"] == "Blocked prompt"

    def test_context_only_deny_with_guidance(self):
        """UserPromptSubmit DENY should not include guidance since it returns invalid response."""
        result = HookResult(decision=Decision.DENY, reason="Blocked", guidance="Try something else")
        output = result.to_json("UserPromptSubmit")

        assert "hookSpecificOutput" in output
        assert output["hookSpecificOutput"]["permissionDecision"] == Decision.DENY


class TestHookResultSystemMessageDenyFormat:
    """Test system message response formatting with DENY decision."""

    def test_system_message_deny_returns_invalid_response(self):
        """SessionStart with DENY returns deliberately invalid response."""
        result = HookResult(decision=Decision.DENY, reason="Session rejected")
        output = result.to_json("SessionStart")

        # Should return decision field (invalid for systemMessage-only events)
        assert "decision" in output
        assert output["decision"] == "deny"
        assert output["reason"] == "Session rejected"
        assert "systemMessage" not in output

    def test_system_message_deny_without_reason(self):
        """SessionStart with DENY and no reason returns decision only."""
        result = HookResult(decision=Decision.DENY)
        output = result.to_json("SessionStart")

        assert "decision" in output
        assert output["decision"] == "deny"
        assert "reason" not in output

    def test_system_message_allow_no_context_no_guidance_returns_empty(self):
        """SessionStart with ALLOW and no context/guidance returns empty dict."""
        result = HookResult(decision=Decision.ALLOW)
        output = result.to_json("SessionStart")

        assert output == {}

    def test_pre_compact_deny_returns_invalid_response(self):
        """PreCompact with DENY returns deliberately invalid response."""
        result = HookResult(decision=Decision.DENY, reason="Compact rejected")
        output = result.to_json("PreCompact")

        assert "decision" in output
        assert output["decision"] == "deny"


class TestHookResultErrorFactory:
    """Test HookResult.error() factory method."""

    def test_error_with_include_debug_info_true(self):
        """HookResult.error() with include_debug_info=True includes debug instructions."""
        result = HookResult.error(
            error_type="handler_exception",
            error_details="Handler crashed",
            include_debug_info=True,
        )

        assert result.decision == Decision.ALLOW
        context_text = "\n".join(result.context)
        assert "handler_exception" in context_text
        assert "Handler crashed" in context_text
        assert "TO DEBUG" in context_text
        assert "RECOMMENDED ACTION" in context_text

    def test_error_with_include_debug_info_false(self):
        """HookResult.error() with include_debug_info=False omits debug instructions."""
        result = HookResult.error(
            error_type="internal_error",
            error_details="Something went wrong",
            include_debug_info=False,
        )

        assert result.decision == Decision.ALLOW
        context_text = "\n".join(result.context)
        assert "internal_error" in context_text
        assert "Something went wrong" in context_text
        # Should NOT include debug/recommended action
        assert "TO DEBUG" not in context_text
        assert "RECOMMENDED ACTION" not in context_text


class TestHookResultStatusFormat:
    """Test Status event response format (plain text)."""

    def test_status_with_context_returns_plain_text(self):
        """Status event should return plain text in {"text": "..."} format."""
        result = HookResult(decision=Decision.ALLOW, context=["Sonnet | Ctx: 42%", "| main"])
        output = result.to_json("Status")

        assert "text" in output
        assert output["text"] == "Sonnet | Ctx: 42% | main"
        assert "hookSpecificOutput" not in output

    def test_status_empty_context_returns_default(self):
        """Status event with no context should return default text."""
        result = HookResult(decision=Decision.ALLOW)
        output = result.to_json("Status")

        assert output["text"] == "Claude"

    def test_status_single_context_item(self):
        """Status event with single context item."""
        result = HookResult(decision=Decision.ALLOW, context=["Model: Sonnet"])
        output = result.to_json("Status")

        assert output["text"] == "Model: Sonnet"

    def test_status_multiple_context_items(self):
        """Status event with multiple context items joined with spaces."""
        result = HookResult(decision=Decision.ALLOW, context=["Part 1", "Part 2", "Part 3"])
        output = result.to_json("Status")

        assert output["text"] == "Part 1 Part 2 Part 3"

    def test_status_ignores_decision_field(self):
        """Status event should not include decision field."""
        result = HookResult(decision=Decision.DENY, reason="Test")
        output = result.to_json("Status")

        # Should still return plain text format (Status events don't support deny)
        assert "text" in output
        assert "decision" not in output
        assert "reason" not in output
