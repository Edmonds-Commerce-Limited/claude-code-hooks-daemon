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

    # ---- origin attribution (Plan 00399) ---------------------------------
    #
    # The supervisor recognises a compaction, and whose it is, from this record
    # rather than from the keystrokes it forwarded: a Tab-completed `/compact`
    # emits none of the bytes a keystroke match needs.

    def test_manual_without_instructions_is_human(self, handler: CompactionSignalHandler) -> None:
        # `/comp` + Tab + Enter: Claude Code reports a manual compaction with
        # no custom instructions, exactly as for a fully typed `/compact`.
        handler.handle({"session_id": "abc", "trigger": "manual", "custom_instructions": None})
        data = self._signal("abc")
        assert data["trigger"] == "manual"
        assert data["origin"] == "human"

    def test_manual_with_human_instructions_is_human(
        self, handler: CompactionSignalHandler
    ) -> None:
        handler.handle(
            {"session_id": "abc", "trigger": "manual", "custom_instructions": "prep for release"}
        )
        assert self._signal("abc")["origin"] == "human"

    def test_manual_with_supervisor_prefix_is_supervisor(
        self, handler: CompactionSignalHandler
    ) -> None:
        handler.handle(
            {
                "session_id": "abc",
                "trigger": "manual",
                "custom_instructions": (
                    "🤖 [ccy-supervisor 2026-09-24 15:52:20] After compacting, "
                    "immediately resume and continue the work that was in progress."
                ),
            }
        )
        assert self._signal("abc")["origin"] == "supervisor"

    def test_auto_trigger_is_auto(self, handler: CompactionSignalHandler) -> None:
        handler.handle({"session_id": "abc", "trigger": "auto", "custom_instructions": None})
        data = self._signal("abc")
        assert data["trigger"] == "auto"
        assert data["origin"] == "auto"

    def test_missing_trigger_is_unknown(self, handler: CompactionSignalHandler) -> None:
        handler.handle({"session_id": "abc"})
        data = self._signal("abc")
        assert data["trigger"] is None
        assert data["origin"] == "unknown"

    def test_unrecognised_trigger_is_unknown(self, handler: CompactionSignalHandler) -> None:
        handler.handle({"session_id": "abc", "trigger": "scheduled"})
        assert self._signal("abc")["origin"] == "unknown"

    def test_human_instructions_are_not_written(self, handler: CompactionSignalHandler) -> None:
        # The record carries WHO, never the human's own text.
        handler.handle(
            {"session_id": "abc", "trigger": "manual", "custom_instructions": "prep for release"}
        )
        raw = (self._untracked / _SIGNAL_SUBDIR / f"abc{_SIGNAL_SUFFIX}").read_text(
            encoding="utf-8"
        )
        assert "prep for release" not in raw

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

    def test_no_project_context_survived(self, handler: CompactionSignalHandler) -> None:
        def _raise(cls: Any) -> Path:
            raise RuntimeError("no project context")

        # A local context, not the `monkeypatch` fixture: this class's autouse
        # fixture has already patched this same attribute, and two patches on
        # one attribute unwind in fixture-teardown order rather than nesting
        # order — leaving the FIXTURE's value installed process-wide (Plan
        # 00348).
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
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

        # Path.replace delegates to os.replace; the handler does not import os.
        monkeypatch.setattr("os.replace", _raise)
        assert handler.handle({"session_id": "abc"}).decision is Decision.ALLOW

    def test_get_claude_md_none(self, handler: CompactionSignalHandler) -> None:
        assert handler.get_claude_md() is None
