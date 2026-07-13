"""Unit tests for the multithread-indicator status handler (Plan 00158 Phase 6).

The handler is the I/O shell around the pure ``thread_registry`` helpers: on
every Status render it upserts this session's heartbeat and renders ``🧵 Y/X``
(rank among live sibling threads) — or nothing when the session is alone.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.status_line.multithread_indicator import (
    MultithreadIndicatorHandler,
)
from claude_code_hooks_daemon.handlers.status_line.thread_registry import (
    _REGISTRY_SUBDIR,
    upsert_heartbeat,
)

_UNTRACKED_ATTR = (
    "claude_code_hooks_daemon.handlers.status_line.multithread_indicator."
    "ProjectContext.daemon_untracked_dir"
)


def _hook_input(
    *,
    session_id: str | None = "sess-a",
    session_name: str | None = "thread A",
    agent_type: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if session_id is not None:
        payload["session_id"] = session_id
    if session_name is not None:
        payload["session_name"] = session_name
    if agent_type is not None:
        payload["agent_type"] = agent_type
    return payload


def _freeze_now(mp: pytest.MonkeyPatch, handler: MultithreadIndicatorHandler, now: float) -> None:
    """Pin the handler's ``_now`` seam to a fixed epoch for deterministic tests."""
    mp.setattr(handler, "_now", lambda: now)


class TestMultithreadIndicatorHandler:
    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        """Point daemon_untracked_dir at a tmp dir so the handler can write."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(_UNTRACKED_ATTR, classmethod(lambda cls: tmp_path))
            self._untracked = tmp_path
            yield

    @pytest.fixture
    def handler(self) -> MultithreadIndicatorHandler:
        return MultithreadIndicatorHandler()

    def _registry_dir(self) -> Path:
        return self._untracked / _REGISTRY_SUBDIR

    # ---- init / metadata ------------------------------------------------

    def test_init_name(self, handler: MultithreadIndicatorHandler) -> None:
        assert handler.name == HandlerID.MULTITHREAD_INDICATOR.display_name

    def test_init_priority(self, handler: MultithreadIndicatorHandler) -> None:
        assert handler.priority == Priority.MULTITHREAD_INDICATOR

    def test_is_non_terminal(self, handler: MultithreadIndicatorHandler) -> None:
        assert handler.terminal is False

    def test_carries_statusline_tag(self, handler: MultithreadIndicatorHandler) -> None:
        assert HandlerTag.STATUSLINE in handler.tags

    def test_default_enabled_is_opt_out(self, handler: MultithreadIndicatorHandler) -> None:
        # Silent when alone → safe to ship on by default (opt-out).
        assert handler.get_default_enabled() is True

    def test_matches_every_status_event(self, handler: MultithreadIndicatorHandler) -> None:
        assert handler.matches(_hook_input()) is True

    # ---- heartbeat write ------------------------------------------------

    def test_writes_own_heartbeat_keyed_by_session_id(
        self, handler: MultithreadIndicatorHandler
    ) -> None:
        handler.handle(_hook_input(session_id="sess-a", session_name="thread A"))
        written = self._registry_dir() / "sess-a.json"
        assert written.exists()
        entry = json.loads(written.read_text(encoding="utf-8"))
        assert entry["session_id"] == "sess-a"
        assert entry["session_name"] == "thread A"

    def test_captures_agent_type_when_present(self, handler: MultithreadIndicatorHandler) -> None:
        handler.handle(_hook_input(session_id="sess-a", agent_type="code-reviewer"))
        entry = json.loads((self._registry_dir() / "sess-a.json").read_text(encoding="utf-8"))
        assert entry["agent_type"] == "code-reviewer"

    # ---- render behaviour -----------------------------------------------

    def test_single_session_renders_nothing(self, handler: MultithreadIndicatorHandler) -> None:
        result = handler.handle(_hook_input(session_id="sess-a"))
        assert isinstance(result, HookResult)
        assert result.context == []

    def test_two_live_sessions_render_rank_segment(
        self, handler: MultithreadIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A sibling thread already has a fresh heartbeat with an EARLIER
        # first_seen, so it ranks first and our session ranks second.
        _freeze_now(monkeypatch, handler, 1000.0)
        upsert_heartbeat(self._registry_dir(), "sibling", "thread B", None, now=990.0)
        result = handler.handle(_hook_input(session_id="sess-a", session_name="thread A"))
        assert result.context == ["| 🧵 2/2"]

    def test_stale_sibling_is_pruned_so_we_are_alone(
        self, handler: MultithreadIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_now(monkeypatch, handler, 1000.0)
        # Sibling last pinged long ago → aged out → we render nothing.
        upsert_heartbeat(self._registry_dir(), "sibling", "thread B", None, now=1.0)
        result = handler.handle(_hook_input(session_id="sess-a"))
        assert result.context == []

    def test_missing_session_id_does_not_crash(self, handler: MultithreadIndicatorHandler) -> None:
        result = handler.handle(_hook_input(session_id=None, session_name=None))
        assert isinstance(result, HookResult)

    def test_render_is_fail_open_when_untracked_dir_unavailable(
        self, handler: MultithreadIndicatorHandler
    ) -> None:
        with pytest.MonkeyPatch.context() as mp:

            def _boom(cls: Any) -> Path:
                raise RuntimeError("no project context")

            mp.setattr(_UNTRACKED_ATTR, classmethod(_boom))
            result = handler.handle(_hook_input(session_id="sess-a"))
        # Never propagate into the status render — degrade to no segment.
        assert result.context == []

    def test_render_is_fail_open_on_registry_oserror(
        self, handler: MultithreadIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise_oserror(*args: Any, **kwargs: Any) -> None:
            raise OSError("registry unwritable")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.status_line.multithread_indicator."
            "upsert_heartbeat",
            _raise_oserror,
        )
        result = handler.handle(_hook_input(session_id="sess-a"))
        # A registry write failure degrades to no segment, never a crash.
        assert result.context == []

    # ---- claude md / acceptance ----------------------------------------

    def test_get_claude_md_is_none(self, handler: MultithreadIndicatorHandler) -> None:
        # Display-only handler; nothing for an agent to avoid fighting.
        assert handler.get_claude_md() is None

    def test_has_acceptance_tests(self, handler: MultithreadIndicatorHandler) -> None:
        assert len(handler.get_acceptance_tests()) >= 1
