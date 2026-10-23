"""No automated goal is written OR cleared for a session in manual goals (Plan 00501 Task 8.3).

The gate is per TARGET session (the retirement fan-out writes other sessions'
signals), fails closed on an unreadable registry, and leaves the human's own
``inject-goal`` (``write_goal_signal``) ungated. The retirement clears are gated
the same way; the goal-loop detector's loop-breaking clear is not.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tests.support.autonomy import pin_session_modes

from claude_code_hooks_daemon.core.data_layer import DaemonDataLayer
from claude_code_hooks_daemon.handlers.post_tool_use import goal_injection
from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import (
    GoalInjectionHandler,
    clear_automated_goal_signal,
    write_automated_goal_signal,
)
from claude_code_hooks_daemon.plan_qa.model import TERMINAL_STATUSES
from claude_code_hooks_daemon.utils.session_modes import ModeSource, manual_goals_entry

_MODULE = "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection"
_MANUAL = "sess-manual"
_AUTO = "sess-auto"


@pytest.fixture
def writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """A registry with ``_MANUAL`` in manual goals, and a recorder for the raw writes."""
    pin_session_modes(
        monkeypatch,
        tmp_path / "modes",
        manual_goals_entry(_MANUAL, entered_at=time.time(), source=ModeSource.HUMAN),
    )
    recorder = MagicMock(return_value=tmp_path / "written.goal-intent")
    monkeypatch.setattr(goal_injection, "write_goal_signal", recorder)
    return recorder


def _targets(recorder: MagicMock) -> list[str]:
    return [call.args[0] for call in recorder.call_args_list]


class TestHelper:
    def test_a_manual_session_gets_no_automated_goal(self, writes: MagicMock) -> None:
        assert write_automated_goal_signal(_MANUAL, "00501", "goal", "status-flip") is None
        writes.assert_not_called()

    def test_another_session_gets_its_goal(self, writes: MagicMock) -> None:
        assert write_automated_goal_signal(_AUTO, "00501", "goal", "status-flip") is not None
        assert _targets(writes) == [_AUTO]

    def test_an_unreadable_registry_fails_closed_with_a_warning(
        self,
        writes: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(
            DaemonDataLayer,
            "session_modes",
            property(lambda _self: (_ for _ in ()).throw(RuntimeError("no project context"))),
        )
        with caplog.at_level(logging.WARNING):
            assert write_automated_goal_signal(_AUTO, "00501", "goal", "status-flip") is None
        writes.assert_not_called()
        assert "no project context" in caplog.text


class TestCallers:
    def test_the_fallback_write_is_gated(self, writes: MagicMock) -> None:
        assert GoalInjectionHandler._write_fallback(_MANUAL, "goal", "00501") is None
        GoalInjectionHandler._write_fallback(_AUTO, "goal", "00501")
        assert _targets(writes) == [_AUTO]

    @pytest.mark.parametrize("session_id", [_MANUAL, _AUTO])
    def test_the_flip_and_reassert_combined_write_is_gated(
        self, writes: MagicMock, tmp_path: Path, session_id: str
    ) -> None:
        handler = GoalInjectionHandler()
        ledger = MagicMock()
        ledger.live_plan_refs.return_value = [MagicMock()]
        with (
            patch.object(handler, "_open_ledger", return_value=ledger),
            patch.object(handler, "_plan_root", return_value=tmp_path),
            patch.object(handler, "_render_combined", return_value=("00501", "goal")),
            patch.object(handler, "_extend_ownership"),
        ):
            handler._write_combined_signal(
                session_id, tmp_path / "PLAN.md", fallback="goal", fallback_plan_number="00501"
            )
        assert _targets(writes) == ([] if session_id == _MANUAL else [_AUTO])

    def test_the_retirement_fan_out_skips_only_the_manual_owner(
        self, writes: MagicMock, tmp_path: Path
    ) -> None:
        handler = GoalInjectionHandler()
        ledger = MagicMock()
        ledger.owning_sessions.return_value = [_MANUAL, _AUTO]
        ledger.live_plan_refs.return_value = [MagicMock()]
        doc = MagicMock()
        doc.status = next(iter(TERMINAL_STATUSES))
        with (
            patch(f"{_MODULE}.PlanDoc") as plan_doc,
            patch.object(handler, "_resolve_transition", return_value=(True, False)),
            patch.object(handler, "_open_ledger", return_value=ledger),
            patch.object(handler, "_plan_root", return_value=tmp_path),
            patch.object(handler, "_render_combined", return_value=("00501", "goal")),
        ):
            plan_doc.parse.return_value = doc
            handler._maybe_refresh_on_retirement(_AUTO, "00501", tmp_path / "PLAN.md", "", {})
        assert _targets(writes) == [_AUTO]


@pytest.fixture
def clears(writes: MagicMock, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """A recorder for the raw goal clears, beside the ``writes`` registry."""
    recorder = MagicMock(return_value=True)
    monkeypatch.setattr(goal_injection, "clear_goal_signal", recorder)
    return recorder


class TestAutomatedClears:
    """The human owns a manual-goals session's goal, so no automated clear removes it."""

    def test_the_helper_clears_only_an_auto_session(self, clears: MagicMock) -> None:
        assert clear_automated_goal_signal(_MANUAL) is False
        assert clear_automated_goal_signal(_AUTO) is True
        assert _targets(clears) == [_AUTO]

    def test_an_unreadable_registry_clears_nothing_with_a_warning(
        self,
        clears: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(
            DaemonDataLayer,
            "session_modes",
            property(lambda _self: (_ for _ in ()).throw(RuntimeError("no project context"))),
        )
        with caplog.at_level(logging.WARNING):
            assert clear_automated_goal_signal(_AUTO) is False
        clears.assert_not_called()
        assert any(
            r.levelno == logging.WARNING and "no project context" in r.getMessage()
            for r in caplog.records
        )

    def test_the_fallback_clear_is_gated(self, clears: MagicMock) -> None:
        assert GoalInjectionHandler._write_fallback(_MANUAL, None, "00501") is None
        assert GoalInjectionHandler._write_fallback(_AUTO, None, "00501") is None
        assert _targets(clears) == [_AUTO]

    def test_the_retirement_clear_skips_only_the_manual_owner(
        self, clears: MagicMock, tmp_path: Path
    ) -> None:
        handler = GoalInjectionHandler()
        ledger = MagicMock()
        ledger.owning_sessions.return_value = [_MANUAL, _AUTO]
        ledger.live_plan_refs.return_value = []
        doc = MagicMock()
        doc.status = next(iter(TERMINAL_STATUSES))
        with (
            patch(f"{_MODULE}.PlanDoc") as plan_doc,
            patch.object(handler, "_resolve_transition", return_value=(True, False)),
            patch.object(handler, "_open_ledger", return_value=ledger),
            patch.object(handler, "_plan_root", return_value=tmp_path),
        ):
            plan_doc.parse.return_value = doc
            handler._maybe_refresh_on_retirement(_AUTO, "00501", tmp_path / "PLAN.md", "", {})
        assert _targets(clears) == [_AUTO]
