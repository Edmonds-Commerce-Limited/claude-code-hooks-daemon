"""Unit tests for the CompactionSignalHandler (Plan 00135)."""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, HookResult
from claude_code_hooks_daemon.handlers.pre_compact.compaction_signal import (
    _SIGNAL_SUBDIR,
    _SIGNAL_SUFFIX,
    CompactionSignalHandler,
)


class TestCompactionSignalHandler:
    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "claude_code_hooks_daemon.handlers.pre_compact.compaction_signal."
                "ProjectContext.daemon_untracked_dir",
                classmethod(lambda cls: tmp_path),
            )
            self._untracked = tmp_path
            yield

    @pytest.fixture
    def handler(self) -> CompactionSignalHandler:
        return CompactionSignalHandler()

    def _signal(self, session_id: str) -> dict[str, Any]:
        path = self._untracked / _SIGNAL_SUBDIR / f"{session_id}{_SIGNAL_SUFFIX}"
        return json.loads(path.read_text(encoding="utf-8"))

    # ---- metadata -------------------------------------------------------

    def test_init_name(self, handler: CompactionSignalHandler) -> None:
        assert handler.name == HandlerID.COMPACTION_SIGNAL.display_name

    def test_init_priority(self, handler: CompactionSignalHandler) -> None:
        assert handler.priority == Priority.COMPACTION_SIGNAL

    def test_init_non_terminal(self, handler: CompactionSignalHandler) -> None:
        assert handler.terminal is False

    def test_init_tags(self, handler: CompactionSignalHandler) -> None:
        assert HandlerTag.NON_TERMINAL in handler.tags

    def test_opt_in_by_default(self, handler: CompactionSignalHandler) -> None:
        assert handler.get_default_enabled() is False

    # ---- behaviour ------------------------------------------------------

    def test_matches_always_true(self, handler: CompactionSignalHandler) -> None:
        assert handler.matches({}) is True

    def test_writes_signal_file(self, handler: CompactionSignalHandler) -> None:
        handler.handle({"session_id": "abc"})
        assert (self._untracked / _SIGNAL_SUBDIR / f"abc{_SIGNAL_SUFFIX}").exists()

    def test_signal_not_a_json_sidecar(self, handler: CompactionSignalHandler) -> None:
        # The signal must not end in .json (the supervisor sidecar glob).
        handler.handle({"session_id": "abc"})
        files = list((self._untracked / _SIGNAL_SUBDIR).iterdir())
        assert all(not f.name.endswith(".json") for f in files)

    def test_signal_has_ts_and_session(self, handler: CompactionSignalHandler) -> None:
        handler.handle({"session_id": "abc"})
        data = self._signal("abc")
        assert isinstance(data["ts"], float)
        assert data["session_id"] == "abc"

    def test_ts_uses_now_seam(
        self, handler: CompactionSignalHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(handler, "_now", lambda: 4242.0)
        handler.handle({"session_id": "abc"})
        assert self._signal("abc")["ts"] == 4242.0

    def test_missing_session_id_uses_fallback(self, handler: CompactionSignalHandler) -> None:
        handler.handle({})
        assert (self._untracked / _SIGNAL_SUBDIR / f"unknown{_SIGNAL_SUFFIX}").exists()

    def test_unsafe_session_id_sanitised(self, handler: CompactionSignalHandler) -> None:
        handler.handle({"session_id": "a/b"})
        assert (self._untracked / _SIGNAL_SUBDIR / f"a_b{_SIGNAL_SUFFIX}").exists()

    def test_returns_allow(self, handler: CompactionSignalHandler) -> None:
        result = handler.handle({"session_id": "abc"})
        assert isinstance(result, HookResult)
        assert result.decision is Decision.ALLOW

    # ---- resilience -----------------------------------------------------

    def test_no_project_context_survived(
        self, handler: CompactionSignalHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(cls: Any) -> Path:
            raise RuntimeError("no project context")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.pre_compact.compaction_signal."
            "ProjectContext.daemon_untracked_dir",
            classmethod(_raise),
        )
        assert handler.handle({"session_id": "abc"}).decision is Decision.ALLOW

    def test_os_error_survived(
        self, handler: CompactionSignalHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*args: Any, **kwargs: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.pre_compact.compaction_signal.os.replace",
            _raise,
        )
        assert handler.handle({"session_id": "abc"}).decision is Decision.ALLOW

    def test_get_claude_md_none(self, handler: CompactionSignalHandler) -> None:
        assert handler.get_claude_md() is None
