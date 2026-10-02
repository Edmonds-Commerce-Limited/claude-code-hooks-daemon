"""StopFailureRecorderHandler: record rate-limit and credential failures (Plan 00470 Task 3.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.handlers.stop_failure.stop_failure_recorder import (
    StopFailureRecorderHandler,
)
from claude_code_hooks_daemon.utils.stop_failure_records import (
    RECORDED_ERRORS,
    StopFailureRecord,
    read_records,
)

_NOW = 3_000_000.0


class _Handler(StopFailureRecorderHandler):
    """The handler with a fixed clock and a record file under ``tmp_path``."""

    def __init__(self, path: Path | None) -> None:
        super().__init__()
        self.path = path

    def _records_path(self) -> Path | None:
        return self.path

    def _now(self) -> float:
        return _NOW


def _payload(error: str = "rate_limit", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "StopFailure",
        "session_id": "s1",
        "error": error,
        "error_details": "429 Too Many Requests",
        "last_assistant_message": "API Error: Rate limit reached",
    }
    payload.update(overrides)
    return payload


class TestIdentity:
    def test_it_is_wired_to_the_constants(self) -> None:
        handler = StopFailureRecorderHandler()
        assert handler.name == HandlerID.STOP_FAILURE_RECORDER.display_name
        assert handler.priority == Priority.STOP_FAILURE_RECORDER
        assert handler.config_key == "stop_failure_recorder"

    def test_it_is_not_terminal(self) -> None:
        assert StopFailureRecorderHandler().terminal is False

    def test_it_registers_for_the_stop_failure_event(self) -> None:
        from claude_code_hooks_daemon.core.router import EventRouter
        from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()
        registry.register_all(
            router, config={"stop_failure": {"stop_failure_recorder": {"enabled": True}}}
        )
        names = [h.name for h in router.get_chain(EventType.STOP_FAILURE).handlers]
        assert names == [HandlerID.STOP_FAILURE_RECORDER.display_name]


class TestMatching:
    @pytest.mark.parametrize("error", sorted(RECORDED_ERRORS))
    def test_the_three_errors_match(self, error: str) -> None:
        assert StopFailureRecorderHandler().matches(_payload(error)) is True

    @pytest.mark.parametrize(
        "error", ["overloaded", "server_error", "max_output_tokens", "unknown", "billing_error"]
    )
    def test_other_errors_do_not_match(self, error: str) -> None:
        assert StopFailureRecorderHandler().matches(_payload(error)) is False

    def test_a_missing_error_does_not_match(self) -> None:
        assert StopFailureRecorderHandler().matches({"session_id": "s1"}) is False


class TestHandling:
    @pytest.mark.parametrize("error", sorted(RECORDED_ERRORS))
    def test_the_failure_is_recorded_with_session_error_and_time(
        self, tmp_path: Path, error: str
    ) -> None:
        path = tmp_path / "stop-failures.json"
        _Handler(path).handle(_payload(error))
        assert read_records(path) == [
            StopFailureRecord(session_id="s1", error=error, recorded_at=_NOW)
        ]

    def test_the_answer_is_empty(self, tmp_path: Path) -> None:
        result = _Handler(tmp_path / "stop-failures.json").handle(_payload())
        assert result.to_json("StopFailure") == {}

    def test_no_session_id_records_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        _Handler(path).handle(_payload(session_id=""))
        assert not path.exists()

    def test_no_project_context_records_nothing_and_does_not_raise(self) -> None:
        _Handler(None).handle(_payload())

    def test_the_error_details_and_message_are_not_stored(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        _Handler(path).handle(_payload())
        text = path.read_text(encoding="utf-8")
        assert "429" not in text
        assert "Rate limit" not in text


class TestDocumentation:
    def test_it_is_silent_so_it_ships_no_resident_guidance(self) -> None:
        assert StopFailureRecorderHandler().get_claude_md() is None

    def test_it_declares_an_acceptance_test(self) -> None:
        assert StopFailureRecorderHandler().get_acceptance_tests()
