"""Tests for AgentTerminatedEarlyFailureDetectorHandler.

N46 review 2's follow-up (Plan 00466 ledger 16): a foreground Agent/Task
dispatch killed by a harness usage limit with `is_error: true` delivers its
death through PostToolUseFailure's `error` field, not through PostToolUse --
budget_exhaustion_detector (the PostToolUse sibling) never receives this
event at all. Covers: the real (redacted) transcript shape firing for both
Task and Agent, both limit kinds, channel scoping (a non-dispatch tool never
fires), the anchor (mid-response quoting does not match), the NIT-6 stable
tail requirement, and the advisory's identity preference.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers import post_tool_use_failure as ptuf

AgentTerminatedEarlyFailureDetectorHandler = ptuf.AgentTerminatedEarlyFailureDetectorHandler


@pytest.fixture
def handler() -> "AgentTerminatedEarlyFailureDetectorHandler":
    """Create a fresh handler instance for each test."""
    return AgentTerminatedEarlyFailureDetectorHandler()


def _failure_input(
    tool_name: str, error: Any, tool_input: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build a PostToolUseFailure hook input (contracts/claude-code-hooks/
    PostToolUseFailure.json shape). No real session/transcript ids."""
    return {
        "hook_event_name": "PostToolUseFailure",
        "session_id": "sess-1",
        "transcript_path": (
            "/root/.claude/projects/-workspace/" "00000000-0000-0000-0000-000000000000.jsonl"
        ),
        "tool_name": tool_name,
        "tool_input": tool_input or {},
        "tool_use_id": "toolu_example",
        "error": error,
        "is_interrupt": False,
        "duration_ms": 1000,
    }


# ─── The real (redacted) transcript shape ─────────────────────────────────

# A REDACTED copy of the real is_error occurrence's toolUseResult (a bare
# string beginning "Error: Agent terminated early..."), per
# hooks.md:2118-2151 ("the error string is generally the same text Claude
# receives as the failed tool's result"). No real request id or session id.
_WEEKLY_LIMIT_ERROR = (
    "Error: Agent terminated early due to an API error: You've hit your "
    "weekly limit · resets Sep 27, 8am (UTC) (error type rate_limit, "
    "HTTP 429, request id req_example, model claude-sonnet-5)."
)

_SESSION_LIMIT_ERROR = (
    "Error: Agent terminated early due to an API error: You've hit your "
    "session limit · resets 12:50am (UTC) (error type rate_limit, "
    "HTTP 429, request id req_example, model claude-sonnet-5)."
)


class TestRealTranscriptShapeFires:
    @pytest.mark.parametrize("tool_name", ["Task", "Agent"])
    @pytest.mark.parametrize(
        "error_text",
        [_WEEKLY_LIMIT_ERROR, _SESSION_LIMIT_ERROR],
        ids=["weekly-limit", "session-limit"],
    )
    def test_the_real_shape_fires(
        self,
        handler: "AgentTerminatedEarlyFailureDetectorHandler",
        tool_name: str,
        error_text: str,
    ) -> None:
        hook_input = _failure_input(tool_name, error_text)
        assert handler.matches(hook_input) is True

    def test_decision_is_always_allow(
        self, handler: "AgentTerminatedEarlyFailureDetectorHandler"
    ) -> None:
        hook_input = _failure_input("Agent", _WEEKLY_LIMIT_ERROR)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW


class TestChannelScoped:
    def test_a_non_dispatch_tool_never_fires(
        self, handler: "AgentTerminatedEarlyFailureDetectorHandler"
    ) -> None:
        """The same error TEXT through Bash -- a command's own failed stderr,
        say -- must never fire: this signal only arrives from a sub-agent
        dispatch tool's own failure."""
        hook_input = _failure_input("Bash", _WEEKLY_LIMIT_ERROR)
        assert handler.matches(hook_input) is False

    def test_error_field_missing_or_non_string_never_fires(
        self, handler: "AgentTerminatedEarlyFailureDetectorHandler"
    ) -> None:
        hook_input = _failure_input("Agent", None)
        assert handler.matches(hook_input) is False


class TestAnchorAndTail:
    def test_mid_response_quoting_does_not_fire(
        self, handler: "AgentTerminatedEarlyFailureDetectorHandler"
    ) -> None:
        quoted = "Exit code 1\nThe transcript shows: '" + _WEEKLY_LIMIT_ERROR + "' verbatim."
        hook_input = _failure_input("Agent", quoted)
        assert handler.matches(hook_input) is False

    def test_bare_phrase_without_the_stable_tail_does_not_fire(
        self, handler: "AgentTerminatedEarlyFailureDetectorHandler"
    ) -> None:
        """N46 review 2, NIT-6 parity with the PostToolUse sibling: the
        anchor alone is not enough without the rate-limit error-type tail
        nearby."""
        bare = (
            "Error: Agent terminated early due to an API error: You've hit "
            "your weekly limit, according to the transcript I was reviewing."
        )
        hook_input = _failure_input("Agent", bare)
        assert handler.matches(hook_input) is False


class TestAdvisoryIdentity:
    def test_advisory_names_the_agent_and_demands_a_re_brief(
        self, handler: "AgentTerminatedEarlyFailureDetectorHandler"
    ) -> None:
        hook_input = _failure_input(
            "Task",
            _WEEKLY_LIMIT_ERROR,
            tool_input={"description": "review the diff for N23", "subagent_type": "fork"},
        )
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context
        combined = "\n".join(result.context)
        assert "review the diff for N23" in combined
        assert "re-brief" in combined.lower() or "rebrief" in combined.lower()
        assert "SUB-AGENT DIED" in combined

    def test_advisory_prefers_name_over_description(
        self, handler: "AgentTerminatedEarlyFailureDetectorHandler"
    ) -> None:
        hook_input = _failure_input(
            "Agent",
            _WEEKLY_LIMIT_ERROR,
            tool_input={"name": "n46-fix", "description": "review N23"},
        )
        result = handler.handle(hook_input)
        combined = "\n".join(result.context)
        assert "n46-fix" in combined
        assert "review N23" not in combined

    def test_unnamed_dispatch_when_nothing_identifies_it(
        self, handler: "AgentTerminatedEarlyFailureDetectorHandler"
    ) -> None:
        hook_input = _failure_input("Agent", _WEEKLY_LIMIT_ERROR, tool_input={})
        result = handler.handle(hook_input)
        combined = "\n".join(result.context)
        assert "an unnamed dispatch" in combined


class TestHandlerMetadata:
    def test_default_enabled(self, handler: "AgentTerminatedEarlyFailureDetectorHandler") -> None:
        assert handler.get_default_enabled() is True

    def test_never_blocks(self, handler: "AgentTerminatedEarlyFailureDetectorHandler") -> None:
        hook_input = _failure_input("Agent", _WEEKLY_LIMIT_ERROR)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
