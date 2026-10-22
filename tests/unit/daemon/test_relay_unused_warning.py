"""The daemon names an unused relay binary on every relay-eligible answer (Plan 00529).

The generated relay guard falls through to the bash path when the configured
relay binary is missing or cannot run, and the request envelope then carries
``relay_unused``. Every answer to such a request carries one warning line; the
verdict is never changed by it.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.events import wired_event_metas
from claude_code_hooks_daemon.constants.protocol import RequestEnvelopeField
from claude_code_hooks_daemon.core.chain import ChainExecutionResult
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.response_schemas import validate_response
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.daemon.relay_unused_warning import (
    RELAY_UNUSED_WARNING_PREFIX,
    add_relay_unused_warning,
    is_relay_eligible_event,
    relay_unused_warning_text,
)
from claude_code_hooks_daemon.install.relay_deploy import relay_binary_missing_warning
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command

_BINARY = "/project/untracked/relay/hooks-relay"

_ELIGIBLE: tuple[EventType, ...] = tuple(
    m.wire_key for m in wired_event_metas() if m.relay_eligible
)
_INELIGIBLE: tuple[EventType, ...] = tuple(
    m.wire_key for m in wired_event_metas() if not m.relay_eligible
)

#: Keys that only carry TEXT for the agent or the user. Everything else in a
#: response can carry or shape a decision, and must never change.
_TEXT_KEYS = frozenset({"systemMessage", "additionalContext", "hookEventName"})


def _decision_view(response: dict[str, Any]) -> dict[str, Any]:
    """The response with every text-only key removed."""
    view: dict[str, Any] = {}
    for key, value in response.items():
        if key in _TEXT_KEYS:
            continue
        if key == "hookSpecificOutput":
            inner = {k: v for k, v in value.items() if k not in _TEXT_KEYS}
            if inner:
                view[key] = inner
            continue
        view[key] = value
    return view


def _results() -> list[tuple[str, HookResult]]:
    return [
        ("silent-allow", HookResult(decision=Decision.ALLOW)),
        ("allow-with-context", HookResult(decision=Decision.ALLOW, context=["handler advice"])),
        ("deny", HookResult.deny("handler said no")),
    ]


def _expected_text() -> str:
    return RELAY_UNUSED_WARNING_PREFIX + relay_binary_missing_warning(
        Path(_BINARY), daemon_cli_command("transport", "on")
    )


class TestWarningText:
    def test_text_is_the_shared_warning_with_the_fix_command(self) -> None:
        text = relay_unused_warning_text(_BINARY)
        assert text == _expected_text()
        assert _BINARY in text
        assert "transport on" in text
        assert text.startswith("WARNING: ")


class TestEligibility:
    def test_eligible_events_match_the_catalogue(self) -> None:
        for event in _ELIGIBLE:
            assert is_relay_eligible_event(event)
        for event in _INELIGIBLE:
            assert not is_relay_eligible_event(event)

    def test_pretooluse_is_eligible_and_status_and_stop_are_not(self) -> None:
        assert is_relay_eligible_event(EventType.PRE_TOOL_USE)
        assert not is_relay_eligible_event(EventType.STATUS_LINE)
        assert not is_relay_eligible_event(EventType.STOP)


class TestAddWarning:
    @pytest.mark.parametrize("event", _ELIGIBLE, ids=lambda e: e.value)
    @pytest.mark.parametrize("label_result", _results(), ids=lambda lr: lr[0])
    def test_every_eligible_event_carries_the_line_and_keeps_its_decision(
        self, event: EventType, label_result: tuple[str, HookResult]
    ) -> None:
        _label, result = label_result
        if result.decision == Decision.DENY and validate_response(
            event.value, result.to_json(event.value)
        ):
            pytest.skip(f"{event.value} cannot express a deny")
        baseline = result.to_json(event.value)
        warned = add_relay_unused_warning(baseline, event, _BINARY)

        assert _decision_view(warned) == _decision_view(baseline)
        assert validate_response(event.value, warned) == []
        assert _expected_text() in repr(warned)

    def test_pretooluse_silent_allow_gains_additional_context_and_no_decision(self) -> None:
        warned = add_relay_unused_warning({}, EventType.PRE_TOOL_USE, _BINARY)
        assert warned == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": _expected_text(),
            }
        }

    def test_permission_request_silent_allow_is_not_turned_into_an_approval(self) -> None:
        warned = add_relay_unused_warning({}, EventType.PERMISSION_REQUEST, _BINARY)
        assert "decision" not in warned["hookSpecificOutput"]
        assert warned["hookSpecificOutput"]["additionalContext"] == _expected_text()

    def test_existing_context_is_kept_and_the_line_appended(self) -> None:
        baseline = HookResult.deny("no", context=["first"]).to_json("PreToolUse")
        warned = add_relay_unused_warning(baseline, EventType.PRE_TOOL_USE, _BINARY)
        out = warned["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny"
        assert (
            out["permissionDecisionReason"]
            == baseline["hookSpecificOutput"]["permissionDecisionReason"]
        )
        assert out["additionalContext"] == "first\n\n" + _expected_text()

    def test_event_without_context_channel_uses_system_message(self) -> None:
        warned = add_relay_unused_warning({}, EventType.NOTIFICATION, _BINARY)
        assert warned == {"systemMessage": _expected_text()}

    def test_existing_system_message_is_kept(self) -> None:
        warned = add_relay_unused_warning(
            {"systemMessage": "earlier"}, EventType.NOTIFICATION, _BINARY
        )
        assert warned == {"systemMessage": "earlier\n" + _expected_text()}

    def test_input_response_is_not_mutated(self) -> None:
        baseline = HookResult.deny("no", context=["first"]).to_json("PreToolUse")
        snapshot = repr(baseline)
        add_relay_unused_warning(baseline, EventType.PRE_TOOL_USE, _BINARY)
        assert repr(baseline) == snapshot

    def test_ineligible_event_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not relay-eligible"):
            add_relay_unused_warning({}, EventType.STOP, _BINARY)


class TestProcessRequest:
    """``DaemonController.process_request`` reads the envelope field."""

    def _respond(
        self, event: EventType, result: HookResult, *, relay_unused: object = None
    ) -> dict[str, Any]:
        controller = DaemonController()
        request: dict[str, Any] = {
            "event": event.value,
            "hook_input": {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        }
        if relay_unused is not None:
            request[RequestEnvelopeField.RELAY_UNUSED] = relay_unused
        chain = ChainExecutionResult(result=result, execution_time_ms=0.0)
        with patch.object(DaemonController, "process_event", return_value=chain):
            return controller.process_request(request)

    @pytest.mark.parametrize("decision", ["allow", "deny", "ask"])
    def test_marker_adds_the_line_and_keeps_the_pretooluse_decision(self, decision: str) -> None:
        def make() -> HookResult:
            if decision == "deny":
                return HookResult.deny("blocked by rule")
            if decision == "ask":
                return HookResult.ask("confirm")
            return HookResult(decision=Decision.ALLOW)

        plain = self._respond(EventType.PRE_TOOL_USE, make())
        warned = self._respond(EventType.PRE_TOOL_USE, make(), relay_unused=_BINARY)

        assert _decision_view(warned) == _decision_view(plain)
        assert _expected_text() in warned["hookSpecificOutput"]["additionalContext"]

    def test_no_marker_adds_nothing(self) -> None:
        plain = self._respond(EventType.PRE_TOOL_USE, HookResult.deny("x"))
        assert "additionalContext" not in plain["hookSpecificOutput"]

    def test_empty_marker_adds_nothing(self) -> None:
        response = self._respond(EventType.PRE_TOOL_USE, HookResult.deny("x"), relay_unused="")
        assert "additionalContext" not in response["hookSpecificOutput"]

    def test_ineligible_event_is_unchanged(self) -> None:
        plain = self._respond(EventType.STOP, HookResult.deny("keep going"))
        warned = self._respond(EventType.STOP, HookResult.deny("keep going"), relay_unused=_BINARY)
        assert warned == plain

    def test_non_string_marker_is_rejected_loudly_without_changing_the_verdict(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        plain = self._respond(EventType.PRE_TOOL_USE, HookResult.deny("x"))
        warned = self._respond(EventType.PRE_TOOL_USE, HookResult.deny("x"), relay_unused=42)
        assert warned == plain
        assert "relay_unused" in caplog.text
