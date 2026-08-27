"""Unit tests for the downgrade-indicator status handler (Plan 00278).

The handler is the I/O shell around the pure `downgrade_state` helpers: on
every Status render it resolves the current model's family/rank, updates this
session's high-water state, and renders a warning segment naming the drop
(e.g. ``fable→opus``) — or nothing when there is no active downgrade.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.status_line.downgrade_indicator import (
    DowngradeIndicatorHandler,
)
from claude_code_hooks_daemon.handlers.status_line.downgrade_state import (
    _STATE_SUBDIR,
    write_high_water,
)

_UNTRACKED_ATTR = (
    "claude_code_hooks_daemon.handlers.status_line.downgrade_indicator."
    "ProjectContext.daemon_untracked_dir"
)


def _hook_input(
    *,
    session_id: str | None = "sess-a",
    model_id: str | None = "claude-opus-4-6",
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if session_id is not None:
        payload["session_id"] = session_id
    if model_id is not None:
        payload["model"] = {"id": model_id, "display_name": "Opus"}
    return payload


class TestDowngradeIndicatorHandler:
    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        """Point daemon_untracked_dir at a tmp dir so the handler can write."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(_UNTRACKED_ATTR, classmethod(lambda cls: tmp_path))
            self._untracked = tmp_path
            yield

    @pytest.fixture
    def handler(self) -> DowngradeIndicatorHandler:
        return DowngradeIndicatorHandler()

    def _state_dir(self) -> Path:
        return self._untracked / _STATE_SUBDIR

    # ---- init / metadata ------------------------------------------------

    def test_init_name(self, handler: DowngradeIndicatorHandler) -> None:
        assert handler.name == HandlerID.DOWNGRADE_INDICATOR.display_name

    def test_init_priority(self, handler: DowngradeIndicatorHandler) -> None:
        assert handler.priority == Priority.DOWNGRADE_INDICATOR

    def test_priority_sits_right_after_model_context(
        self, handler: DowngradeIndicatorHandler
    ) -> None:
        assert handler.priority > Priority.MODEL_CONTEXT

    def test_is_non_terminal(self, handler: DowngradeIndicatorHandler) -> None:
        assert handler.terminal is False

    def test_carries_status_tag(self, handler: DowngradeIndicatorHandler) -> None:
        assert HandlerTag.STATUS in handler.tags

    def test_default_enabled_is_opt_out(self, handler: DowngradeIndicatorHandler) -> None:
        assert handler.get_default_enabled() is True

    def test_matches_every_status_event(self, handler: DowngradeIndicatorHandler) -> None:
        assert handler.matches(_hook_input()) is True

    # ---- family-from-model-id mapping (via the render path) -------------

    def test_fable_model_sets_high_water_and_emits_nothing(
        self, handler: DowngradeIndicatorHandler
    ) -> None:
        result = handler.handle(_hook_input(session_id="sess-a", model_id="claude-fable-1-0"))
        assert result.context == []
        entry = json.loads((self._state_dir() / "sess-a.json").read_text(encoding="utf-8"))
        assert entry["high_water_family"] == "fable"

    def test_opus_after_fable_high_water_emits_downgrade_segment(
        self, handler: DowngradeIndicatorHandler
    ) -> None:
        handler.handle(_hook_input(session_id="sess-a", model_id="claude-fable-1-0"))
        result = handler.handle(_hook_input(session_id="sess-a", model_id="claude-opus-4-6"))
        assert len(result.context) == 1
        segment = result.context[0]
        assert "fable" in segment
        assert "opus" in segment

    def test_render_back_on_fable_after_downgrade_is_silent_recovery(
        self, handler: DowngradeIndicatorHandler
    ) -> None:
        handler.handle(_hook_input(session_id="sess-a", model_id="claude-fable-1-0"))
        handler.handle(_hook_input(session_id="sess-a", model_id="claude-opus-4-6"))
        result = handler.handle(_hook_input(session_id="sess-a", model_id="claude-fable-1-0"))
        assert result.context == []
        # High-water must still read fable -- the downgrade render must not
        # have clobbered it.
        entry = json.loads((self._state_dir() / "sess-a.json").read_text(encoding="utf-8"))
        assert entry["high_water_family"] == "fable"

    def test_session_started_on_opus_never_reports_downgrade(
        self, handler: DowngradeIndicatorHandler
    ) -> None:
        # A session that STARTS on opus (its own high-water) must never be
        # mislabelled a downgrade merely because opus outranks lower tiers.
        result = handler.handle(_hook_input(session_id="sess-a", model_id="claude-opus-4-6"))
        assert result.context == []
        result_again = handler.handle(_hook_input(session_id="sess-a", model_id="claude-opus-4-6"))
        assert result_again.context == []

    def test_unknown_model_id_emits_nothing_and_leaves_high_water_untouched(
        self, handler: DowngradeIndicatorHandler
    ) -> None:
        write_high_water(self._state_dir(), "sess-a", "fable", 3)
        result = handler.handle(_hook_input(session_id="sess-a", model_id="some-future-model-9-9"))
        assert result.context == []
        entry = json.loads((self._state_dir() / "sess-a.json").read_text(encoding="utf-8"))
        assert entry["high_water_family"] == "fable"

    def test_missing_session_id_does_not_crash(self, handler: DowngradeIndicatorHandler) -> None:
        result = handler.handle(_hook_input(session_id=None))
        assert isinstance(result, HookResult)
        assert result.context == []

    def test_state_file_missing_is_silent(self, handler: DowngradeIndicatorHandler) -> None:
        result = handler.handle(_hook_input(session_id="brand-new-session"))
        assert isinstance(result, HookResult)

    def test_corrupt_state_file_does_not_crash(self, handler: DowngradeIndicatorHandler) -> None:
        state_dir = self._state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "sess-a.json").write_text("not json", encoding="utf-8")
        result = handler.handle(_hook_input(session_id="sess-a", model_id="claude-opus-4-6"))
        assert isinstance(result, HookResult)
        # Corrupt state is treated as "no prior state" -- it is replaced with
        # the current render becoming the new high-water, not a downgrade.
        assert result.context == []

    # ---- fail-open behaviour ---------------------------------------------

    def test_render_is_fail_open_when_untracked_dir_unavailable(
        self, handler: DowngradeIndicatorHandler
    ) -> None:
        with pytest.MonkeyPatch.context() as mp:

            def _boom(cls: Any) -> Path:
                raise RuntimeError("no project context")

            mp.setattr(_UNTRACKED_ATTR, classmethod(_boom))
            result = handler.handle(_hook_input(session_id="sess-a"))
        assert result.context == []

    def test_render_is_fail_open_on_state_oserror(
        self, handler: DowngradeIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise_oserror(*args: Any, **kwargs: Any) -> None:
            raise OSError("state dir unwritable")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.status_line.downgrade_indicator."
            "evaluate_downgrade",
            _raise_oserror,
        )
        result = handler.handle(_hook_input(session_id="sess-a"))
        assert result.context == []

    # ---- claude md / acceptance -------------------------------------------

    def test_get_claude_md_is_none(self, handler: DowngradeIndicatorHandler) -> None:
        # Status-line renderer: the segment never reaches the agent's own
        # context (it is rendered by the Claude Code CLI terminal UI), so
        # there is no agent-facing action for resident guidance to change.
        assert handler.get_claude_md() is None

    def test_has_acceptance_tests(self, handler: DowngradeIndicatorHandler) -> None:
        assert len(handler.get_acceptance_tests()) >= 1
