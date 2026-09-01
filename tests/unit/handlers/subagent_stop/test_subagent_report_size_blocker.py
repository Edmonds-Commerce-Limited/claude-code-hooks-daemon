"""Block an oversized subagent final message until it is routed through a file.

Plan 00307 Task 3.1. Task 1.1's live reproduction dispatched a subagent
instructed to return a ~24k-token final message inline: the harness silently
elided the MIDDLE of the payload (an explicit truncation marker appeared,
mid-section, with both start/end sentinels surviving) — so the coordinator
can receive a report that LOOKS complete while content is missing. Prevention
at dispatch (``dispatch_declaration``) cannot catch an agent that ignores the
contract; this handler is the backstop at return time: it reads
``last_assistant_message`` directly off the SubagentStop hook input (no
transcript parse needed — the vendored contract delivers it verbatim) and
blocks the stop when it exceeds a configured character threshold.

Design constraints pinned:

- **Fail open** on any missing/malformed input — a handler that cannot judge
  size must never block.
- **Re-entry guard** — ``stop_hook_active: true`` must never be blocked
  again, or the subagent loops forever.
- **Reads the CURRENT field name** — ``last_assistant_message``, not the
  stale ``subagent_id``/``subagent_type`` the input schema used to declare
  exclusively.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.subagent_stop.subagent_report_size_blocker import (
    SubagentReportSizeBlockerHandler,
)


def _subagent_stop_input(message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "SubagentStop",
        "agent_id": "agent-1",
        "agent_type": "Explore",
        "last_assistant_message": message,
        "stop_hook_active": False,
    }
    payload.update(extra)
    return payload


@pytest.fixture
def handler() -> SubagentReportSizeBlockerHandler:
    return SubagentReportSizeBlockerHandler()


class TestIdentity:
    def test_exposes_claude_md_guidance(self, handler: SubagentReportSizeBlockerHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "subagent-reports" in guidance


class TestMatching:
    def test_matches_normal_subagent_stop(self, handler: SubagentReportSizeBlockerHandler) -> None:
        assert handler.matches(_subagent_stop_input("short report")) is True

    def test_does_not_match_re_entry(self, handler: SubagentReportSizeBlockerHandler) -> None:
        hook_input = _subagent_stop_input("x" * 10_000, stop_hook_active=True)
        assert handler.matches(hook_input) is False


class TestSizeThreshold:
    def test_allows_short_message(self, handler: SubagentReportSizeBlockerHandler) -> None:
        result = handler.handle(_subagent_stop_input("done, wrote report to disk"))

        assert result.decision == Decision.ALLOW

    def test_blocks_oversized_message(self, handler: SubagentReportSizeBlockerHandler) -> None:
        oversized = "x" * (handler._threshold_chars + 1)

        result = handler.handle(_subagent_stop_input(oversized))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "subagent-reports" in result.reason

    def test_allows_message_exactly_at_threshold(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        at_threshold = "x" * handler._threshold_chars

        result = handler.handle(_subagent_stop_input(at_threshold))

        assert result.decision == Decision.ALLOW

    def test_threshold_is_configurable(self, handler: SubagentReportSizeBlockerHandler) -> None:
        handler._threshold_chars = 10

        result = handler.handle(_subagent_stop_input("this message is longer than ten chars"))

        assert result.decision == Decision.DENY


class TestFailOpen:
    def test_allows_when_last_assistant_message_missing(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        hook_input = {"hook_event_name": "SubagentStop", "stop_hook_active": False}

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW

    def test_allows_when_last_assistant_message_is_not_a_string(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        hook_input = _subagent_stop_input("placeholder")
        hook_input["last_assistant_message"] = {"not": "a string"}

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW

    def test_matches_returns_true_on_malformed_hook_input(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        # matches() must not raise on a hook_input missing expected keys; the
        # fail-open decision is made in handle(), not by silently skipping.
        assert handler.matches({}) is True
