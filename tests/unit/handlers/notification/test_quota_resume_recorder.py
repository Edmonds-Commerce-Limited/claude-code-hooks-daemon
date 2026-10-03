"""QuotaResumeRecorderHandler: record usage-limit resume notifications (Plan 00470 Task 3.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.handlers.notification.quota_resume_recorder import (
    QuotaResumeRecorderHandler,
)
from claude_code_hooks_daemon.utils.limit_events import RESUME_KINDS, LimitEvent, read_events

_NOW = 5_000_000.0


class _Handler(QuotaResumeRecorderHandler):
    """The handler with a fixed clock and an event file under ``tmp_path``."""

    def __init__(self, path: Path | None) -> None:
        super().__init__()
        self.path = path

    def _events_path(self) -> Path | None:
        return self.path

    def _now(self) -> float:
        return _NOW


def _payload(
    notification_type: str = "quota_auto_resume_fired", **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "Notification",
        "session_id": "s1",
        "notification_type": notification_type,
        "message": "Usage limit reset, continuing",
    }
    payload.update(overrides)
    return payload


class TestIdentity:
    def test_it_is_wired_to_the_constants(self) -> None:
        handler = QuotaResumeRecorderHandler()
        assert handler.name == HandlerID.QUOTA_RESUME_RECORDER.display_name
        assert handler.priority == Priority.QUOTA_RESUME_RECORDER
        assert handler.config_key == "quota_resume_recorder"

    def test_it_is_not_terminal(self) -> None:
        assert QuotaResumeRecorderHandler().terminal is False

    def test_it_registers_for_the_notification_event(self) -> None:
        from claude_code_hooks_daemon.core.router import EventRouter
        from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()
        registry.register_all(
            router, config={"notification": {"quota_resume_recorder": {"enabled": True}}}
        )
        names = [h.name for h in router.get_chain(EventType.NOTIFICATION).handlers]
        assert names == [HandlerID.QUOTA_RESUME_RECORDER.display_name]


class TestMatching:
    @pytest.mark.parametrize("kind", sorted(RESUME_KINDS))
    def test_the_three_resume_types_match(self, kind: str) -> None:
        assert QuotaResumeRecorderHandler().matches(_payload(kind)) is True

    @pytest.mark.parametrize(
        "kind",
        [
            "permission_prompt",
            "idle_prompt",
            "auth_success",
            "agent_completed",
            "agent_needs_input",
            "quota_auto_resume_unheard_of",
        ],
    )
    def test_other_types_do_not_match(self, kind: str) -> None:
        assert QuotaResumeRecorderHandler().matches(_payload(kind)) is False

    def test_a_missing_type_does_not_match(self) -> None:
        assert QuotaResumeRecorderHandler().matches({"session_id": "s1"}) is False


class TestHandling:
    @pytest.mark.parametrize("kind", sorted(RESUME_KINDS))
    def test_the_event_is_recorded_with_session_kind_and_time(
        self, tmp_path: Path, kind: str
    ) -> None:
        path = tmp_path / "limit-events.json"
        _Handler(path).handle(_payload(kind))
        assert read_events(path) == [LimitEvent(session_id="s1", kind=kind, recorded_at=_NOW)]

    def test_the_answer_is_empty(self, tmp_path: Path) -> None:
        result = _Handler(tmp_path / "limit-events.json").handle(_payload())
        assert result.to_json("Notification") == {}

    def test_no_session_id_records_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        _Handler(path).handle(_payload(session_id=""))
        assert not path.exists()

    def test_no_project_context_records_nothing_and_does_not_raise(self) -> None:
        _Handler(None).handle(_payload())

    def test_the_notification_text_is_not_stored(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        _Handler(path).handle(_payload())
        assert "continuing" not in path.read_text(encoding="utf-8")


class TestDocumentation:
    def test_it_is_silent_so_it_ships_no_resident_guidance(self) -> None:
        assert QuotaResumeRecorderHandler().get_claude_md() is None

    def test_it_declares_an_acceptance_test(self) -> None:
        assert QuotaResumeRecorderHandler().get_acceptance_tests()
