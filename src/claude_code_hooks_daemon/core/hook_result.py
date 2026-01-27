"""HookResult model for standardised hook responses.

This module provides the Pydantic model for representing hook results
with full type safety, validation, and proper response formatting.
"""

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Decision(StrEnum):
    """Hook decision types."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    CONTINUE = "continue"


class HookResult(BaseModel):
    """Standardised hook result with decision, reason, and context.

    Represents the outcome of a hook handler execution with all
    fields needed for Claude Code response format.

    Attributes:
        decision: Hook decision (allow, deny, ask, continue)
        reason: Explanation for deny/ask decisions
        context: List of additional context lines for Claude
        guidance: Guidance text for allow-with-feedback scenarios
        handlers_matched: List of handler names that processed this event
    """

    model_config = ConfigDict(frozen=False, validate_assignment=True)

    decision: Decision = Field(default=Decision.ALLOW)
    reason: str | None = Field(default=None)
    context: list[str] = Field(default_factory=list)
    guidance: str | None = Field(default=None)
    handlers_matched: list[str] = Field(default_factory=list)

    @field_validator("decision", mode="before")
    @classmethod
    def coerce_decision(cls, v: str | Decision) -> Decision:
        """Coerce string to Decision enum for backward compatibility."""
        if isinstance(v, Decision):
            return v
        if isinstance(v, str):
            return Decision(v.lower())
        raise ValueError(f"Invalid decision: {v}")

    @field_validator("context", mode="before")
    @classmethod
    def coerce_context(cls, v: str | list[str] | None) -> list[str]:
        """Coerce string context to list for backward compatibility.

        Empty strings are filtered out to maintain silent allow behavior.
        """
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v else []  # Filter empty strings
        return [item for item in v if item]  # Filter empty items from list

    def __repr__(self) -> str:
        """Return string representation for debugging."""
        parts = [f"HookResult(decision={self.decision.value!r}"]
        if self.reason:
            reason_preview = self.reason[:50] + "..." if len(self.reason) > 50 else self.reason
            parts.append(f", reason={reason_preview!r}")
        if self.context:
            parts.append(f", context=[{len(self.context)} items]")
        if self.guidance:
            guidance_preview = (
                self.guidance[:50] + "..." if len(self.guidance) > 50 else self.guidance
            )
            parts.append(f", guidance={guidance_preview!r}")
        if self.handlers_matched:
            parts.append(f", handlers={self.handlers_matched}")
        parts.append(")")
        return "".join(parts)

    def add_context(self, *lines: str) -> Self:
        """Add context lines to the result.

        Args:
            *lines: Context lines to add

        Returns:
            Self for chaining
        """
        self.context.extend(lines)
        return self

    def add_handler(self, handler_name: str) -> Self:
        """Record that a handler processed this event.

        Args:
            handler_name: Name of the handler

        Returns:
            Self for chaining
        """
        if handler_name not in self.handlers_matched:
            self.handlers_matched.append(handler_name)
        return self

    def merge_context(self, other: "HookResult") -> Self:
        """Merge context from another result.

        Args:
            other: Result to merge context from

        Returns:
            Self for chaining
        """
        self.context.extend(other.context)
        self.handlers_matched.extend(
            h for h in other.handlers_matched if h not in self.handlers_matched
        )
        return self

    def to_json(self, event_name: str) -> dict[str, Any]:
        """Convert to Claude Code hook JSON format.

        Different event types require different response structures:
        - PreToolUse: hookSpecificOutput with permissionDecision
        - PostToolUse: Top-level decision + hookSpecificOutput
        - Stop/SubagentStop: Top-level decision only (NO hookSpecificOutput)
        - PermissionRequest: hookSpecificOutput with nested decision.behavior
        - SessionStart/SessionEnd/PreCompact/UserPromptSubmit/Notification:
          hookSpecificOutput with context only (NO decision fields)

        Args:
            event_name: Hook event type (PreToolUse, PostToolUse, etc.)

        Returns:
            Dictionary in Claude Code hook output format
        """
        # Silent allow with no context - valid for all events
        if self.decision == Decision.ALLOW and not self.context and not self.guidance:
            return {}

        # Event-specific formatting
        if event_name in ("Stop", "SubagentStop"):
            # Stop events: Top-level decision only, NO hookSpecificOutput
            return self._format_stop_response()
        elif event_name == "PostToolUse":
            # PostToolUse: Top-level decision + hookSpecificOutput
            return self._format_post_tool_use_response(event_name)
        elif event_name == "PermissionRequest":
            # PermissionRequest: Nested decision.behavior structure
            return self._format_permission_request_response(event_name)
        elif event_name == "PreToolUse":
            # PreToolUse: hookSpecificOutput with permissionDecision
            return self._format_pre_tool_use_response(event_name)
        else:
            # Context-only events: SessionStart, SessionEnd, PreCompact,
            # UserPromptSubmit, Notification
            return self._format_context_only_response(event_name)

    def _format_pre_tool_use_response(self, event_name: str) -> dict[str, Any]:
        """Format PreToolUse response (current format).

        Returns:
            hookSpecificOutput with permissionDecision
        """
        output: dict[str, Any] = {"hookEventName": event_name}

        if self.decision in (Decision.DENY, Decision.ASK):
            output["permissionDecision"] = self.decision.value
            if self.reason:
                output["permissionDecisionReason"] = self.reason

        if self.context:
            output["additionalContext"] = "\n\n".join(self.context)

        if self.guidance:
            output["guidance"] = self.guidance

        return {"hookSpecificOutput": output} if output else {}

    def _format_post_tool_use_response(self, event_name: str) -> dict[str, Any]:
        """Format PostToolUse response.

        Returns:
            Top-level decision + hookSpecificOutput with context
        """
        response: dict[str, Any] = {}
        hook_output: dict[str, Any] = {"hookEventName": event_name}

        # Top-level decision field (only for block/deny)
        if self.decision == Decision.DENY:
            response["decision"] = "block"
            if self.reason:
                response["reason"] = self.reason

        # hookSpecificOutput with context only
        if self.context:
            hook_output["additionalContext"] = "\n\n".join(self.context)

        if self.guidance:
            hook_output["guidance"] = self.guidance

        # Only include hookSpecificOutput if it has content beyond hookEventName
        if len(hook_output) > 1:
            response["hookSpecificOutput"] = hook_output

        return response

    def _format_stop_response(self) -> dict[str, Any]:
        """Format Stop/SubagentStop response.

        Returns:
            Top-level decision only (NO hookSpecificOutput)
        """
        response: dict[str, Any] = {}

        # Only include decision if blocking
        if self.decision == Decision.DENY:
            response["decision"] = "block"
            if self.reason:
                response["reason"] = self.reason

        return response

    def _format_permission_request_response(self, event_name: str) -> dict[str, Any]:
        """Format PermissionRequest response.

        Returns:
            hookSpecificOutput with nested decision.behavior
        """
        hook_output: dict[str, Any] = {"hookEventName": event_name}

        # Nested decision structure
        if self.decision in (Decision.ALLOW, Decision.DENY, Decision.ASK):
            hook_output["decision"] = {"behavior": self.decision.value}

        if self.context:
            hook_output["additionalContext"] = "\n\n".join(self.context)

        if self.guidance:
            hook_output["guidance"] = self.guidance

        return {"hookSpecificOutput": hook_output} if len(hook_output) > 1 else {}

    def _format_context_only_response(self, event_name: str) -> dict[str, Any]:
        """Format context-only response for SessionStart, SessionEnd, etc.

        Context-only events do NOT support deny/ask decisions - only ALLOW with optional context.
        If DENY/ASK is used, returns an invalid response that will fail schema validation.

        Args:
            event_name: Hook event type

        Returns:
            hookSpecificOutput with context only (NO decision fields)
        """
        hook_output: dict[str, Any] = {"hookEventName": event_name}

        # Context-only events don't support DENY/ASK - return invalid response if used
        if self.decision in (Decision.DENY, Decision.ASK):
            # Return response with permissionDecision (invalid for context-only events)
            # This will fail schema validation as expected
            hook_output["permissionDecision"] = self.decision.value
            if self.reason:
                hook_output["permissionDecisionReason"] = self.reason
            return {"hookSpecificOutput": hook_output}

        if self.context:
            hook_output["additionalContext"] = "\n\n".join(self.context)

        if self.guidance:
            hook_output["guidance"] = self.guidance

        return {"hookSpecificOutput": hook_output} if len(hook_output) > 1 else {}

    def to_response_dict(self, _event_name: str, timing_ms: float) -> dict[str, Any]:
        """Convert to full daemon response format (PRD 3.2.2).

        Args:
            event_name: Hook event type
            timing_ms: Processing time in milliseconds

        Returns:
            Complete response dictionary per PRD specification
        """
        return {
            "result": {
                "decision": self.decision.value,
                "reason": self.reason,
                "context": self.context,
            },
            "timing_ms": round(timing_ms, 2),
            "handlers_matched": self.handlers_matched,
        }

    @classmethod
    def allow(
        cls,
        *,
        context: list[str] | None = None,
        guidance: str | None = None,
    ) -> "HookResult":
        """Create an allow result.

        Args:
            context: Optional context lines
            guidance: Optional guidance text

        Returns:
            HookResult with allow decision
        """
        return cls(
            decision=Decision.ALLOW,
            context=context or [],
            guidance=guidance,
        )

    @classmethod
    def deny(cls, reason: str, *, context: list[str] | None = None) -> "HookResult":
        """Create a deny result.

        Args:
            reason: Reason for denial (required)
            context: Optional context lines

        Returns:
            HookResult with deny decision
        """
        return cls(
            decision=Decision.DENY,
            reason=reason,
            context=context or [],
        )

    @classmethod
    def ask(cls, reason: str, *, context: list[str] | None = None) -> "HookResult":
        """Create an ask result (prompt user for confirmation).

        Args:
            reason: Reason for asking (required)
            context: Optional context lines

        Returns:
            HookResult with ask decision
        """
        return cls(
            decision=Decision.ASK,
            reason=reason,
            context=context or [],
        )

    @classmethod
    def error(
        cls,
        error_type: str,
        error_details: str,
        *,
        include_debug_info: bool = True,
    ) -> "HookResult":
        """Create an error result per PRD 3.3.2 format.

        Fail-open: Returns allow decision but includes warning context.

        Args:
            error_type: Type of error (handler_exception, config_error, internal_error)
            error_details: Detailed error information

        Returns:
            HookResult with allow decision and error context
        """
        context_lines = [
            "WARNING: The hooks daemon encountered an error and is not functioning correctly.",
            f"ERROR TYPE: {error_type}",
            f"ERROR DETAILS: {error_details}",
        ]

        if include_debug_info:
            context_lines.extend(
                [
                    "",
                    "TO DEBUG: Run 'python -m claude_code_hooks_daemon.daemon.cli logs' to view daemon logs",
                    "",
                    "RECOMMENDED ACTION:",
                    "1. Pause current task immediately",
                    "2. Inform user that hooks protection is not active",
                    "3. Check daemon logs for error details",
                    "4. Debug and restart daemon before continuing work",
                    "",
                    "Working without hooks protection is dangerous - destructive operations will not be blocked.",
                ]
            )

        return cls(
            decision=Decision.ALLOW,
            reason="HOOKS DAEMON ERROR - Proceeding without protection",
            context=context_lines,
        )
