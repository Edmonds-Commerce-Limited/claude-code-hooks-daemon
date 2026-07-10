"""Unit tests for the observe-only context sidecar handler (Plan 00135 Slice 1)."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.status_line.context_sidecar import (
    _SESSION_ID_FALLBACK,
    _SIDECAR_SUBDIR,
    ContextSidecarHandler,
)


def _hook_input(
    *,
    used_pct: float | None = 10.0,
    window_size: int | None = 200_000,
    session_id: str | None = "sess-abc",
    model_id: str = "claude-opus-4-8",
    cost_usd: float | None = None,
) -> dict[str, Any]:
    """Build a minimal Status-event payload for the sidecar handler."""
    payload: dict[str, Any] = {"model": {"id": model_id}}
    ctx: dict[str, Any] = {}
    if used_pct is not None:
        ctx["used_percentage"] = used_pct
    if window_size is not None:
        ctx["context_window_size"] = window_size
    payload["context_window"] = ctx
    if session_id is not None:
        payload["session_id"] = session_id
    if cost_usd is not None:
        payload["cost"] = {"total_cost_usd": cost_usd}
    return payload


class TestContextSidecarHandler:
    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        """Point daemon_untracked_dir at a tmp dir so the handler can write."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.status_line.context_sidecar."
                "ProjectContext.daemon_untracked_dir",
                classmethod(lambda cls: tmp_path),
            )
            self._untracked = tmp_path
            yield

    @pytest.fixture
    def handler(self) -> ContextSidecarHandler:
        return ContextSidecarHandler()

    def _sidecar_dir(self) -> Path:
        return self._untracked / _SIDECAR_SUBDIR

    def _read_sidecar(self, session_id: str) -> dict[str, Any]:
        path = self._sidecar_dir() / f"{session_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    # ---- init / metadata ------------------------------------------------

    def test_init_name(self, handler: ContextSidecarHandler) -> None:
        assert handler.name == HandlerID.CONTEXT_SIDECAR.display_name

    def test_init_priority(self, handler: ContextSidecarHandler) -> None:
        assert handler.priority == Priority.CONTEXT_SIDECAR

    def test_init_is_non_terminal(self, handler: ContextSidecarHandler) -> None:
        assert handler.terminal is False

    def test_init_tags(self, handler: ContextSidecarHandler) -> None:
        assert HandlerTag.STATUS in handler.tags
        assert HandlerTag.NON_TERMINAL in handler.tags

    def test_opt_in_by_default(self, handler: ContextSidecarHandler) -> None:
        assert handler.get_default_enabled() is False

    def test_shares_options_with_model_context(self, handler: ContextSidecarHandler) -> None:
        assert handler.shares_options_with == HandlerID.MODEL_CONTEXT.config_key

    # ---- matches --------------------------------------------------------

    def test_matches_always_true(self, handler: ContextSidecarHandler) -> None:
        assert handler.matches(_hook_input()) is True

    def test_matches_empty_input_true(self, handler: ContextSidecarHandler) -> None:
        assert handler.matches({}) is True

    # ---- handle: return value + display silence -------------------------

    def test_handle_returns_hook_result(self, handler: ContextSidecarHandler) -> None:
        assert isinstance(handler.handle(_hook_input()), HookResult)

    def test_handle_renders_nothing(self, handler: ContextSidecarHandler) -> None:
        result = handler.handle(_hook_input())
        assert result.context == []

    # ---- handle: file writing + schema ----------------------------------

    def test_handle_writes_sidecar_file(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(session_id="sess-abc"))
        assert (self._sidecar_dir() / "sess-abc.json").exists()

    def test_sidecar_has_schema_version(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(session_id="s"))
        assert self._read_sidecar("s")["schema_version"] == 1

    def test_sidecar_records_pct_and_window(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(used_pct=42.5, window_size=200_000, session_id="s"))
        data = self._read_sidecar("s")
        assert data["pct"] == 42.5
        assert data["window_size"] == 200_000

    def test_sidecar_records_model_and_session(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(model_id="claude-opus-4-8", session_id="s"))
        data = self._read_sidecar("s")
        assert data["model_id"] == "claude-opus-4-8"
        assert data["session_id"] == "s"

    # ---- handle: the `red` trigger signal (Decision J) ------------------

    def test_low_pct_is_not_red(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(used_pct=10.0, window_size=200_000, session_id="s"))
        data = self._read_sidecar("s")
        assert data["red"] is False
        assert data["tier"] == "green"

    def test_high_pct_is_red_at_200k(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(used_pct=80.0, window_size=200_000, session_id="s"))
        data = self._read_sidecar("s")
        assert data["red"] is True
        assert data["tier"] == "red"

    def test_red_respects_window_tier(self, handler: ContextSidecarHandler) -> None:
        # 40% is RED for a 1M window but only ORANGE for a 200k window.
        handler.handle(_hook_input(used_pct=40.0, window_size=1_000_000, session_id="big"))
        handler.handle(_hook_input(used_pct=40.0, window_size=200_000, session_id="std"))
        assert self._read_sidecar("big")["red"] is True
        assert self._read_sidecar("std")["red"] is False

    def test_red_respects_config_override(self, handler: ContextSidecarHandler) -> None:
        # Lower the 200k red threshold (as shares_options_with would from config).
        handler._200k_red_pct = 50
        handler.handle(_hook_input(used_pct=55.0, window_size=200_000, session_id="s"))
        assert self._read_sidecar("s")["red"] is True

    # ---- handle: missing / nullable fields ------------------------------

    def test_missing_context_window_defaults(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(used_pct=None, window_size=None, session_id="s"))
        data = self._read_sidecar("s")
        assert data["pct"] == 0.0
        assert data["window_size"] == 0
        assert data["red"] is False

    def test_cost_usd_null_when_absent(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(cost_usd=None, session_id="s"))
        assert self._read_sidecar("s")["cost_usd"] is None

    def test_cost_usd_populated_when_present(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(cost_usd=1.25, session_id="s"))
        assert self._read_sidecar("s")["cost_usd"] == 1.25

    # ---- handle: session id -> filename ---------------------------------

    def test_missing_session_id_uses_fallback_name(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(session_id=None))
        assert (self._sidecar_dir() / f"{_SESSION_ID_FALLBACK}.json").exists()

    def test_unsafe_session_id_is_sanitised(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(session_id="a/b/../c"))
        # No path traversal: everything unsafe collapses to underscores.
        assert (self._sidecar_dir() / "a_b_.._c.json").exists()

    # ---- handle: writer metadata ----------------------------------------

    def test_seq_increments_across_calls(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(session_id="s"))
        assert self._read_sidecar("s")["seq"] == 1
        handler.handle(_hook_input(session_id="s"))
        assert self._read_sidecar("s")["seq"] == 2

    def test_writer_pid_is_current_process(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(session_id="s"))
        assert self._read_sidecar("s")["writer_pid"] == os.getpid()

    def test_ts_uses_now_seam(
        self, handler: ContextSidecarHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(handler, "_now", lambda: 1234.5)
        handler.handle(_hook_input(session_id="s"))
        assert self._read_sidecar("s")["ts"] == 1234.5

    # ---- handle: atomicity ----------------------------------------------

    def test_no_tmp_file_left_behind(self, handler: ContextSidecarHandler) -> None:
        handler.handle(_hook_input(session_id="s"))
        leftovers = [p.name for p in self._sidecar_dir().iterdir() if p.suffix == ".tmp"]
        assert leftovers == []

    # ---- handle: resilience (explicit, logged, never silent) ------------

    def test_uninitialised_project_context_is_survived(
        self, handler: ContextSidecarHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(cls: Any) -> Path:
            raise RuntimeError("ProjectContext not initialised")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.status_line.context_sidecar."
            "ProjectContext.daemon_untracked_dir",
            classmethod(_raise),
        )
        # Must not raise; still returns a display-silent result.
        result = handler.handle(_hook_input(session_id="s"))
        assert result.context == []

    def test_os_error_is_survived(
        self, handler: ContextSidecarHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*args: Any, **kwargs: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.status_line.context_sidecar.os.replace",
            _raise,
        )
        result = handler.handle(_hook_input(session_id="s"))
        assert result.context == []

    # ---- guidance / acceptance ------------------------------------------

    def test_get_claude_md_is_none(self, handler: ContextSidecarHandler) -> None:
        assert handler.get_claude_md() is None

    def test_get_acceptance_tests_present(self, handler: ContextSidecarHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) == 1
