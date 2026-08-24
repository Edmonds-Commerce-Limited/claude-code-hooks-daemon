"""HookResult model for standardised hook responses.

This module provides the Pydantic model for representing hook results
with full type safety, validation, and proper response formatting.
"""

import logging
import re
import unicodedata
from enum import StrEnum
from typing import Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


class Decision(StrEnum):
    """Hook decision types."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    CONTINUE = "continue"


# Universal suffix appended to all PreToolUse DENY reasons.
# Agents sometimes interpret a blocked tool as a signal to stop working.
# This suffix makes the expected behaviour explicit: adapt and continue.
_DENY_CONTINUATION_SUFFIX = (
    "\n\n⚠️ Any tool calls batched with this one were CANCELLED — re-issue any Edit/Write/commit "
    "separately, and don't batch them with blockable commands. Then adapt and continue."
)

# Separator between top-level status-line segments. Each segment historically
# self-embeds this on its leading or trailing edge; the Status renderer
# normalises those away and re-joins so segment ORDER can never drop a boundary.
_STATUS_SEGMENT_SEPARATOR = "|"
# Fallback text when no status segment produced any content.
_STATUS_DEFAULT_TEXT = "Claude"
# Rendered separator between two adjacent status segments (a space-padded pipe).
_STATUS_JOIN = f" {_STATUS_SEGMENT_SEPARATOR} "
# One terminal row per newline: Claude Code renders multi-line statusLine output.
_STATUS_ROW_SEPARATOR = "\n"
# WorktreeCreate raw-path response (Plan 00188). The daemon→forwarder envelope
# key carrying the created worktree path; the forwarder extracts it and prints
# the raw path (Claude Code parses the WorktreeCreate hook's stdout as a path).
_WORKTREE_CREATE_EVENT_NAME = "WorktreeCreate"
_WORKTREE_PATH_KEY = "worktreePath"

# Which events can actually CARRY each refusal on the wire. Anything absent here
# drops that decision, and the resulting response is still schema-VALID — so the
# contract check cannot see it. Stop and PostToolUse express `block` but have no
# `ask`; Status renders a status line and expresses nothing at all.
#
# Without this table those drops are silent: a handler asks to interrupt, gets
# `{}`, and believes it succeeded. Unreachable in this repository (Decision.ASK
# appears in no handler here) but NOT unreachable for a client, whose project
# handlers are a supported extension point that no test in this repo sweeps.
# Kept honest by tests that assert every claim against the emitted response.
#
# Public because ``core.decision_capability`` answers the same question ahead of
# time for project handlers, which no test in this repository can sweep. One
# table, two surfaces, so a client's pre-flight check cannot drift from what the
# serialiser actually does at runtime.
REFUSAL_CAPABLE_EVENTS: Final[dict[Decision, frozenset[str]]] = {
    Decision.DENY: frozenset(
        {
            "PreToolUse",  # permissionDecision: deny
            "PostToolUse",  # decision: block
            "Stop",  # decision: block
            "SubagentStop",  # decision: block
            "PermissionRequest",  # decision.behavior: deny
        }
    ),
    Decision.ASK: frozenset(
        {
            "PreToolUse",  # permissionDecision: ask
            "PermissionRequest",  # decision.behavior: ask
        }
    ),
}
# Matches ANSI SGR/CSI escape sequences so colour codes are excluded from the
# DISPLAYED width when wrapping (they occupy zero visible columns).
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _display_width(text: str) -> int:
    """Approximate the terminal column width of a rendered status fragment.

    ANSI colour escapes are stripped (zero visible width); East-Asian wide and
    fullwidth code points (most emoji) count as two columns; combining marks and
    format code points (the ZWJ / emoji variation selector) count as zero. This
    is a dependency-free heuristic accurate to within ~1 column — good enough
    because wrapping only ever breaks at whole-segment boundaries, never
    mid-segment.
    """
    stripped = _ANSI_ESCAPE_RE.sub("", text)
    width = 0
    for ch in stripped:
        if unicodedata.combining(ch) or unicodedata.category(ch) == "Cf":
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _wrap_status_parts(parts: list[str], columns: int) -> str:
    """Pack status segments into rows no wider than ``columns`` (Plan 00167).

    Greedy first-fit at ``' | '`` boundaries: each row grows until the next
    segment would exceed the width, then a new row starts. A single segment
    wider than ``columns`` occupies its own row (it cannot be split). Rows are
    joined with a newline, which Claude Code renders as separate terminal rows,
    so no right-hand segment is lost on a narrow screen.
    """
    sep_width = _display_width(_STATUS_JOIN)
    rows: list[str] = []
    current: list[str] = []
    current_width = 0
    for part in parts:
        part_width = _display_width(part)
        if not current:
            current = [part]
            current_width = part_width
        elif current_width + sep_width + part_width <= columns:
            current.append(part)
            current_width += sep_width + part_width
        else:
            rows.append(_STATUS_JOIN.join(current))
            current = [part]
            current_width = part_width
    if current:
        rows.append(_STATUS_JOIN.join(current))
    return _STATUS_ROW_SEPARATOR.join(rows)


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
    # WorktreeCreate raw-path output (Plan 00188). Claude Code parses the
    # WorktreeCreate hook's stdout as the *created worktree path* (not a JSON
    # decision), so the handler carries the absolute path here and to_json emits
    # {"worktreePath": ...} which the forwarder prints raw.
    worktree_path: str | None = Field(default=None)
    # Optional sub-classification of WHICH internal check/pattern produced this
    # decision (Plan 00209 verdict log). Purely internal metadata consumed by
    # the verdict-log writer — never part of the Claude Code hook response, so
    # to_json() never emits it. Most handlers never set it; that is fine, the
    # verdict log records it as null in that case.
    rule: str | None = Field(default=None)

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

    def to_json(
        self,
        event_name: str,
        *,
        stop_hook_active: bool = False,
        terminal_columns: int | None = None,
    ) -> dict[str, Any]:
        """Convert to Claude Code hook JSON format, enforcing the response contract.

        This is the single choke point: ``front_controller``, ``daemon/server``
        and ``daemon/controller`` all serialise through here, so a response that
        violates its event's schema cannot reach Claude Code by any route.

        Enforcement matters most for the case the serialiser already knew about.
        ``_format_system_message_response`` DELIBERATELY emits ``{"decision": ...}``
        for a DENY/ASK on an event that cannot express one, so that validation
        rejects it — but validation never ran in production, so the deny was
        silently dropped instead: the handler believed it blocked and nothing did.

        Args:
            event_name: Hook event type (PreToolUse, PostToolUse, etc.)
            stop_hook_active: Only meaningful for Stop/SubagentStop.
            terminal_columns: Only meaningful for Status.

        Returns:
            A response dictionary that satisfies its event's schema.
        """
        response = self._build_wire_response(
            event_name,
            stop_hook_active=stop_hook_active,
            terminal_columns=terminal_columns,
        )
        return self._enforce_response_contract(event_name, response)

    def _enforce_response_contract(
        self, event_name: str, response: dict[str, Any]
    ) -> dict[str, Any]:
        """Return ``response`` if it satisfies its schema, else a safe substitute.

        The substitute is chosen to be NEVER WEAKER than what the handler asked
        for. It deliberately does NOT reuse ``generate_daemon_error_response``,
        which is fail-open for every event but Stop/SubagentStop: routing a
        failed DENY through that would turn a block into a permit, which is a
        worse outcome than the bug being fixed.

        An event with no schema at all is passed through with a warning rather
        than rejected. That is not leniency about a violated contract — it is
        the absence of one, and a newly-wired event must not hard-fail here.

        Cost, measured rather than assumed, since this now runs on every hook
        dispatch: 0.034 ms for a silent allow and 0.060 ms for a deny, against
        the ~1.8 ms daemon-side dispatch this project advertises — 1.9% and 3.3%.
        A violation is logged at ERROR every time it occurs, deliberately
        unthrottled: it should never happen (every shipped handler validates),
        so a flood is a signal worth its volume rather than noise to suppress.
        """
        from claude_code_hooks_daemon.core.response_schemas import (
            RESPONSE_SCHEMAS,
            validate_response,
        )

        if event_name not in RESPONSE_SCHEMAS:
            logger.warning(
                "No response schema for event %s; emitting %s unvalidated",
                event_name,
                response,
            )
            return response

        errors = validate_response(event_name, response)
        if not errors:
            self._report_dropped_refusal(event_name)
            return response

        logger.error(
            "RESPONSE CONTRACT VIOLATION on %s: %s violates its schema (%s). "
            "Handler decision was %s. Emitting a safe substitute instead.",
            event_name,
            response,
            "; ".join(errors),
            self.decision.value,
        )

        substitute = self._safe_substitute_response(event_name)
        remaining = validate_response(event_name, substitute)
        if remaining:
            # FAIL FAST: a substitute that is itself invalid would put us back
            # to emitting rubbish, silently. Better to crash with the reason.
            raise RuntimeError(
                f"Response contract substitute for {event_name} is itself invalid: "
                f"{substitute} -> {remaining}"
            )
        return substitute

    def _report_dropped_refusal(self, event_name: str) -> None:
        """Log a refusal this event drops even though the response is VALID.

        The schema check cannot catch these: ``Stop`` and ``PostToolUse`` express
        ``block`` but have no ``ask``, and ``Status`` expresses nothing, so an
        ASK on the first two and any refusal on the last serialise to a
        perfectly valid ``{}`` or ``{"text": ...}``. Enforcement sees nothing
        wrong, and the handler is left believing it interrupted something.

        Nothing is substituted, because the response is already the best the
        event permits — a status line genuinely cannot refuse, and injecting an
        error into it would put noise on every prompt forever. The gap is the
        absence of a RECORD, so a record is what this adds.
        """
        if self.decision not in REFUSAL_CAPABLE_EVENTS:
            return
        if event_name in REFUSAL_CAPABLE_EVENTS[self.decision]:
            return

        logger.error(
            "DROPPED REFUSAL on %s: a handler returned '%s', which this event "
            "cannot carry on the wire. The response is valid but the refusal was "
            "NOT enforced. Reason given: %s",
            event_name,
            self.decision.value,
            self.reason or "(none)",
        )

    def _safe_substitute_response(self, event_name: str) -> dict[str, Any]:
        """Build a schema-valid response that does not weaken a refusal.

        For an event that CAN carry a refusal, re-emit one through that event's
        own formatter. For an event that cannot, the refusal is impossible on
        the wire — so the reason is surfaced as a loud ``systemMessage`` rather
        than discarded, which is the outcome the old code got wrong.
        """
        if self.decision in (Decision.DENY, Decision.ASK):
            if event_name in ("Stop", "SubagentStop"):
                return self._format_stop_response(event_name, False)
            if event_name == "PostToolUse":
                return self._format_post_tool_use_response(event_name)
            if event_name == "PermissionRequest":
                return self._format_permission_request_response(event_name)
            if event_name == "PreToolUse":
                return self._format_pre_tool_use_response(event_name)

        detail = f": {self.reason}" if self.reason else ""
        if self.decision in (Decision.DENY, Decision.ASK):
            message = (
                f"⚠️ HOOKS DAEMON: a handler returned '{self.decision.value}' for "
                f"{event_name}, which cannot express it. The request was NOT "
                f"enforced{detail}"
            )
        else:
            # Reaching here for a non-refusal means the response was malformed
            # for some other reason. Saying "cannot express it" would be false —
            # every event expresses allow — and would mislead whoever reads it.
            message = (
                f"⚠️ HOOKS DAEMON: a handler produced an invalid {event_name} "
                f"response for decision '{self.decision.value}'{detail}"
            )

        # The advisory channel differs per event, and picking the wrong one just
        # swaps one contract violation for another. Status accepts only `text`;
        # the five decision-capable events and UserPromptSubmit accept only
        # `hookSpecificOutput`; the systemMessage-only events accept neither.
        # Assuming systemMessage here previously made the SUBSTITUTE invalid for
        # those six, so the FAIL FAST below would have raised out of to_json.
        if event_name == "Status":
            return {"text": message}
        if event_name in (
            "PreToolUse",
            "PostToolUse",
            "Stop",
            "SubagentStop",
            "PermissionRequest",
            "UserPromptSubmit",
        ):
            return {
                "hookSpecificOutput": {
                    "hookEventName": event_name,
                    "additionalContext": message,
                }
            }
        return {"systemMessage": message}

    def _build_wire_response(
        self,
        event_name: str,
        *,
        stop_hook_active: bool = False,
        terminal_columns: int | None = None,
    ) -> dict[str, Any]:
        """Convert to Claude Code hook JSON format.

        Different event types require different response structures:
        - Status: Plain text response {"text": "..."} (NOT JSON hookSpecificOutput)
        - PreToolUse: hookSpecificOutput with permissionDecision
        - PostToolUse: Top-level decision + hookSpecificOutput
        - Stop/SubagentStop: Top-level decision only (NO hookSpecificOutput)
        - PermissionRequest: hookSpecificOutput with nested decision.behavior
        - UserPromptSubmit: hookSpecificOutput with context only (NO decision fields)
        - SessionStart/SessionEnd/PreCompact/Notification: systemMessage ONLY (NO hookSpecificOutput)

        Args:
            event_name: Hook event type (PreToolUse, PostToolUse, etc.)
            stop_hook_active: Only meaningful for Stop/SubagentStop. True when
                the caller's hook_input signals this Stop check is itself a
                re-entry (Claude Code re-fired Stop after a prior response).
                Used to break the ALLOW-with-context infinite loop - see
                ``_format_stop_response``.

        Returns:
            Dictionary in Claude Code hook output format
        """
        # Special case: Status event returns plain text
        if event_name == "Status":
            # Join status segments with a single ' | ' separator. Segments
            # self-embed a leading OR trailing '|'; whichever side they chose
            # used to decide whether a boundary got a separator, so a
            # config-driven REORDER could place two same-side segments adjacent
            # and drop the '|' between them (e.g. '📦 podman 👤 user'). Strip
            # each fragment's OUTER separator/whitespace and re-join so every
            # boundary is consistent regardless of order; a fragment's INTERNAL
            # '|' (e.g. model_context's '🤖 Opus | ◔ 5%') is preserved.
            sep = _STATUS_SEGMENT_SEPARATOR
            parts: list[str] = []
            for fragment in self.context:
                normalised = fragment.strip()
                if normalised.startswith(sep):
                    normalised = normalised[len(sep) :].strip()
                if normalised.endswith(sep):
                    normalised = normalised[: -len(sep)].strip()
                if normalised:
                    parts.append(normalised)
            if not parts:
                return {"text": _STATUS_DEFAULT_TEXT}
            # Plan 00167: when Claude Code forwards the real terminal width
            # (init.sh -> terminal_columns), wrap at ' | ' segment boundaries so
            # no segment runs off a narrow screen. No/invalid width -> the
            # single-line join (backwards-compatible with older clients).
            if isinstance(terminal_columns, int) and terminal_columns > 0:
                return {"text": _wrap_status_parts(parts, terminal_columns)}
            return {"text": _STATUS_JOIN.join(parts)}

        # Special case: WorktreeCreate returns the created worktree path. Claude
        # Code parses this hook's stdout as a raw path, so an empty {} would be
        # taken literally as the path "/<cwd>/{}" and fail creation (Plan 00188).
        # The forwarder extracts .worktreePath and prints it raw.
        if event_name == _WORKTREE_CREATE_EVENT_NAME and self.worktree_path:
            return {_WORKTREE_PATH_KEY: self.worktree_path}

        # Silent allow with no context - valid for all events
        if self.decision == Decision.ALLOW and not self.context and not self.guidance:
            return {}

        # Event-specific formatting
        if event_name in ("Stop", "SubagentStop"):
            # Stop events: top-level decision for DENY, plus
            # hookSpecificOutput.additionalContext for non-blocking advisory context
            return self._format_stop_response(event_name, stop_hook_active)
        elif event_name == "PostToolUse":
            # PostToolUse: Top-level decision + hookSpecificOutput
            return self._format_post_tool_use_response(event_name)
        elif event_name == "PermissionRequest":
            # PermissionRequest: Nested decision.behavior structure
            return self._format_permission_request_response(event_name)
        elif event_name == "PreToolUse":
            # PreToolUse: hookSpecificOutput with permissionDecision
            return self._format_pre_tool_use_response(event_name)
        elif event_name == "UserPromptSubmit":
            # UserPromptSubmit: hookSpecificOutput with context only
            return self._format_context_only_response(event_name)
        else:
            # SessionStart, SessionEnd, PreCompact, Notification: systemMessage ONLY
            # These events do NOT support hookSpecificOutput in Claude Code
            return self._format_system_message_response()

    def _format_pre_tool_use_response(self, event_name: str) -> dict[str, Any]:
        """Format PreToolUse response (current format).

        Returns:
            hookSpecificOutput with permissionDecision
        """
        output: dict[str, Any] = {"hookEventName": event_name}

        if self.decision in (Decision.DENY, Decision.ASK):
            output["permissionDecision"] = self.decision.value
            if self.reason:
                reason = self.reason
                if self.decision == Decision.DENY:
                    reason = reason + _DENY_CONTINUATION_SUFFIX
                output["permissionDecisionReason"] = reason

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

    def _format_stop_response(self, event_name: str, stop_hook_active: bool) -> dict[str, Any]:
        """Format Stop/SubagentStop response.

        Per Claude Code's hooks documentation, Stop and SubagentStop accept
        `hookSpecificOutput.additionalContext` for non-blocking advisory
        feedback that continues the conversation, in addition to the
        top-level `decision`/`reason` blocking mechanism.

        LOOP-BREAKER (Sev-1 shipped in v3.31.0): Claude Code treats ANY
        non-empty additionalContext as "continue the conversation" -
        regardless of decision - and sets stop_hook_active=true on the next
        Stop check. An unconditional advisory handler on Stop — one that
        contributes context regardless of what happened — adds non-empty
        context on every single Stop event, so once one
        ALLOW-with-context response goes out, nothing ever makes context
        empty again, and the daemon keeps re-triggering "continue" forever.
        DENY is unaffected (a real block is supposed to force attention no
        matter how many times it re-fires); only non-blocking ALLOW context
        is subject to the one-shot rule: surface it on the first check
        (stop_hook_active falsy), then go silent on every re-entry so Claude
        Code can actually return control to the user.

        Returns:
            Top-level decision for DENY (context always included), plus
            hookSpecificOutput.additionalContext for ALLOW only on the first
            stop check of a run (empty dict on any ALLOW re-entry).
        """
        response: dict[str, Any] = {}

        if self.decision == Decision.DENY:
            response["decision"] = "block"
            if self.reason:
                response["reason"] = self.reason
            if self.context:
                response["hookSpecificOutput"] = {
                    "hookEventName": event_name,
                    "additionalContext": "\n\n".join(self.context),
                }
            return response

        if stop_hook_active:
            # Non-blocking re-entry - already advised once, go silent.
            return response

        if self.context:
            response["hookSpecificOutput"] = {
                "hookEventName": event_name,
                "additionalContext": "\n\n".join(self.context),
            }

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

        # The reason shares additionalContext with context, because the nested
        # decision object permits only `behavior` and `updatedInput` — there is
        # nowhere else in this event's schema for an explanation to go. Without
        # this the refusal arrived bare: AutoApproveReadsHandler denies a
        # non-read tool with a three-line explanation that was discarded in
        # full, leaving the user refused and told nothing. The sibling
        # PreToolUse formatter has always emitted permissionDecisionReason.
        explanation: list[str] = []
        if self.reason and self.decision in (Decision.DENY, Decision.ASK):
            explanation.append(self.reason)
        explanation.extend(self.context)

        if explanation:
            hook_output["additionalContext"] = "\n\n".join(explanation)

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

    def _format_system_message_response(self) -> dict[str, Any]:
        """Format response for events that only support systemMessage.

        These events do NOT support hookSpecificOutput or decision fields:
        - PreCompact
        - SessionStart
        - SessionEnd
        - Notification

        Returns:
            systemMessage with combined context, or empty dict for silent allow.
            If DENY/ASK is used, returns deliberately invalid response for schema validation.
        """
        # These events don't support DENY/ASK - return invalid response if used
        if self.decision in (Decision.DENY, Decision.ASK):
            # Return response with decision field (invalid for systemMessage-only events)
            # This will fail schema validation as expected
            response: dict[str, Any] = {"decision": self.decision.value}
            if self.reason:
                response["reason"] = self.reason
            return response

        # Context/guidance gets combined into systemMessage
        messages = []
        if self.context:
            messages.extend(self.context)
        if self.guidance:
            messages.append(self.guidance)

        if not messages:
            return {}

        return {"systemMessage": "\n\n".join(messages)}

    def to_response_dict(self, _event_name: str, timing_ms: float) -> dict[str, Any]:
        """Convert to full daemon response format (PRD 3.2.2).

        Args:
            _event_name: Hook event type. Accepted for call-site symmetry with
                ``to_json`` but unused: the PRD 3.2.2 response shape is the same
                for every event, so the value does not affect the output.
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
                    "TO DEBUG: Use the hooks-daemon skill to check logs (Skill tool: skill=hooks-daemon, args=logs)",
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

    @classmethod
    def configuration_error(cls, errors: list[str]) -> "HookResult":
        """Create a configuration error result for degraded mode.

        Fail-open: Returns allow decision but includes warning context about
        invalid configuration. Used when daemon starts with invalid config
        and enters degraded mode.

        Args:
            errors: List of configuration validation error messages

        Returns:
            HookResult with allow decision and configuration error context
        """
        context_lines = [
            "WARNING: DEGRADED MODE - Hooks daemon configuration is invalid.",
            "The daemon is running but handlers may not be configured correctly.",
            "",
        ]

        if errors:
            context_lines.append(f"CONFIGURATION ERRORS ({len(errors)}):")
            for error in errors:
                context_lines.append(f"  - {error}")
            context_lines.append("")

        context_lines.extend(
            [
                "REMEDIATION:",
                "1. Fix the configuration in .claude/hooks-daemon.yaml",
                "2. Use the hooks-daemon skill to restart (Skill tool: skill=hooks-daemon, args=restart)",
                "",
                "Working in degraded mode - some handlers may not be active.",
            ]
        )

        return cls(
            decision=Decision.ALLOW,
            reason="HOOKS DAEMON DEGRADED - Configuration invalid",
            context=context_lines,
        )
