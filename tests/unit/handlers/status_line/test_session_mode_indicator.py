"""The session-mode status segment (Plan 00501 Task 4.1).

Shows this session's top mode by precedence (usage-paused > goal-blocked >
awaiting-human > focus > unattended) plus a ``+N`` count, and the focus task
when focus is the top mode. Registry modes come from the in-memory registry
(no file read); usage-paused from its own record (mtime-gated); unattended from
the daemon mode. A registry or record that cannot be read is shown as a named
error, never as no mode.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from tests.support.autonomy import awaiting_human_entry, focus_entry, pin_session_modes

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant
from claude_code_hooks_daemon.core.data_layer import get_data_layer
from claude_code_hooks_daemon.handlers.status_line.session_mode_indicator import (
    SessionModeIndicatorHandler,
)
from claude_code_hooks_daemon.utils import usage_pause

_MODULE = "claude_code_hooks_daemon.handlers.status_line.session_mode_indicator"
_SID = "sess-status"


def _controller(mode: DaemonMode = DaemonMode.DEFAULT) -> Mock:
    controller = Mock()
    controller.get_mode.return_value = {ModeConstant.KEY_MODE: mode.value}
    return controller


@pytest.fixture
def untracked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    pin_session_modes(monkeypatch, tmp_path)
    return tmp_path


@pytest.fixture
def daemon_mode() -> Iterator[Mock]:
    controller = _controller()
    with patch(f"{_MODULE}.get_controller", return_value=controller):
        yield controller


def _render(handler: SessionModeIndicatorHandler, session_id: str = _SID) -> list[str]:
    hook_input: dict[str, Any] = {"session_id": session_id}
    assert handler.matches(hook_input) is True
    return list(handler.handle(hook_input).context)


def _pause(paused_at: float) -> usage_pause.UsagePause:
    return usage_pause.UsagePause(
        session_id=_SID,
        paused_at=paused_at,
        resume_at=paused_at + 3600,
        window=usage_pause.WINDOW_FIVE_HOUR,
        used_percentage=91.0,
        ceiling=90.0,
        reason="five_hour at 91%",
    )


class TestIdentity:
    def test_id_and_priority(self) -> None:
        handler = SessionModeIndicatorHandler()
        assert handler.handler_id is HandlerID.SESSION_MODE_INDICATOR
        assert handler.priority == Priority.SESSION_MODE_INDICATOR
        assert handler.terminal is False


@pytest.mark.usefixtures("daemon_mode")
class TestRender:
    def test_no_mode_renders_nothing(self, untracked: Path) -> None:
        assert _render(SessionModeIndicatorHandler()) == []

    def test_no_session_renders_nothing(self, untracked: Path) -> None:
        assert _render(SessionModeIndicatorHandler(), session_id="") == []

    def test_focus_shows_its_task(self, untracked: Path) -> None:
        get_data_layer().session_modes.enter(focus_entry(_SID, "write the release note"))
        [segment] = _render(SessionModeIndicatorHandler())
        assert "⚑ focus: write the release note" in segment
        assert segment.startswith("| ")

    def test_a_long_task_is_shortened(self, untracked: Path) -> None:
        get_data_layer().session_modes.enter(focus_entry(_SID, "x" * 80))
        [segment] = _render(SessionModeIndicatorHandler())
        assert "x" * 80 not in segment
        assert "…" in segment

    def test_top_mode_and_count(self, untracked: Path) -> None:
        registry = get_data_layer().session_modes
        registry.enter(focus_entry(_SID, "task"))
        registry.enter(awaiting_human_entry(_SID))
        [segment] = _render(SessionModeIndicatorHandler())
        assert "⚑ awaiting-human +1" in segment
        assert "task" not in segment

    def test_unattended_is_shown(self, untracked: Path, daemon_mode: Mock) -> None:
        daemon_mode.get_mode.return_value = {ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value}
        [segment] = _render(SessionModeIndicatorHandler())
        assert "⚑ unattended" in segment

    def test_usage_paused_is_shown_from_its_record(self, untracked: Path) -> None:
        usage_pause.write_usage_pause(untracked, _pause(time.time() - 10))
        [segment] = _render(SessionModeIndicatorHandler())
        assert "⚑ usage-paused" in segment

    def test_an_expired_pause_is_not_shown(self, untracked: Path) -> None:
        usage_pause.write_usage_pause(untracked, _pause(time.time() - 3 * 86400))
        assert _render(SessionModeIndicatorHandler()) == []

    def test_a_malformed_pause_record_is_a_named_error(
        self, untracked: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = usage_pause.pause_path(untracked, _SID)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            [segment] = _render(SessionModeIndicatorHandler())
        assert "usage-pause record unreadable" in segment
        assert "usage-pause" in caplog.text

    def test_an_unreadable_registry_is_a_named_error(
        self, untracked: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch(f"{_MODULE}.get_data_layer", side_effect=OSError("disk gone")),
            caplog.at_level(logging.WARNING),
        ):
            [segment] = _render(SessionModeIndicatorHandler())
        assert "modes unreadable" in segment
        assert "disk gone" in caplog.text

    def test_an_unknown_daemon_mode_is_not_unattended(
        self, untracked: Path, daemon_mode: Mock
    ) -> None:
        daemon_mode.get_mode.return_value = {}
        assert _render(SessionModeIndicatorHandler()) == []


class TestExplanation:
    def test_explanation_names_every_label_and_the_glyph(self) -> None:
        explanation = SessionModeIndicatorHandler().explain_segment()
        assert explanation.glyphs == ("⚑",)
        assert explanation.name == "Session Mode"
        for label in ("usage-paused", "goal-blocked", "awaiting-human", "focus", "unattended"):
            assert label in explanation.how_to_read
        assert "mode-history" in explanation.how_to_read

    def test_no_claude_md_and_one_acceptance_test(self) -> None:
        handler = SessionModeIndicatorHandler()
        assert handler.get_claude_md() is None
        assert len(handler.get_acceptance_tests()) == 1
