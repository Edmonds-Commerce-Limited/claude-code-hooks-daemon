"""Tests for DaemonDataLayer - unified API facade.

TDD RED phase: These tests define the expected API for DaemonDataLayer.
"""

import threading
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import ToolName
from claude_code_hooks_daemon.core.data_layer import (
    DaemonDataLayer,
    get_data_layer,
    reset_data_layer,
)
from claude_code_hooks_daemon.core.disclosure_tracker import DisclosureTracker
from claude_code_hooks_daemon.core.handler_history import HandlerHistory
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.session_mode_log import TRANSITION_LOG_FILENAME
from claude_code_hooks_daemon.core.session_mode_registry import NoticeKind, SessionModeRegistry
from claude_code_hooks_daemon.core.session_state import SessionState
from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader
from claude_code_hooks_daemon.utils.blockage_marker import MARKER_FILENAME, write_json_atomically
from claude_code_hooks_daemon.utils.session_modes import (
    ModeSource,
    SessionMode,
    SessionModeEntry,
)
from claude_code_hooks_daemon.utils.session_signal_paths import SIGNAL_SUBDIR


def _legacy_marker(path: Path) -> None:
    """A live awaiting-human marker in the shape an older daemon left on disk."""
    write_json_atomically(path, {"session_id": "sid", "recorded_at": time.time()})


class TestDaemonDataLayerInit:
    """Test DaemonDataLayer initialization."""

    def test_session_returns_session_state(self) -> None:
        """session property should return a SessionState instance."""
        dl = DaemonDataLayer()
        assert isinstance(dl.session, SessionState)

    def test_transcript_returns_transcript_reader(self) -> None:
        """transcript property should return a TranscriptReader instance."""
        dl = DaemonDataLayer()
        assert isinstance(dl.transcript, TranscriptReader)

    def test_history_returns_handler_history(self) -> None:
        """history property should return a HandlerHistory instance."""
        dl = DaemonDataLayer()
        assert isinstance(dl.history, HandlerHistory)

    def test_disclosure_returns_disclosure_tracker(self) -> None:
        """disclosure property should return a DisclosureTracker instance."""
        dl = DaemonDataLayer()
        assert isinstance(dl.disclosure, DisclosureTracker)

    def test_session_is_same_instance(self) -> None:
        """session should return the same instance on multiple accesses."""
        dl = DaemonDataLayer()
        assert dl.session is dl.session

    def test_transcript_is_same_instance(self) -> None:
        """transcript should return the same instance on multiple accesses."""
        dl = DaemonDataLayer()
        assert dl.transcript is dl.transcript

    def test_history_is_same_instance(self) -> None:
        """history should return the same instance on multiple accesses."""
        dl = DaemonDataLayer()
        assert dl.history is dl.history

    def test_disclosure_is_same_instance(self) -> None:
        """disclosure should return the same instance on multiple accesses."""
        dl = DaemonDataLayer()
        assert dl.disclosure is dl.disclosure


class TestDaemonDataLayerReset:
    """Test DaemonDataLayer.reset()."""

    def test_reset_clears_session_state(self) -> None:
        """reset() should clear session state."""
        dl = DaemonDataLayer()
        dl.session.update_from_status_event(
            {
                "model": {"id": "claude-opus-4-6", "display_name": "Opus"},
                "context_window": {"used_percentage": 75.0},
            }
        )
        dl.reset()
        assert dl.session.model_id is None
        assert dl.session.is_populated is False

    def test_reset_clears_handler_history(self) -> None:
        """reset() should clear handler history."""
        dl = DaemonDataLayer()
        dl.history.record(
            handler_id="test",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
        )
        dl.reset()
        assert dl.history.total_count == 0

    def test_reset_clears_disclosure_tracker(self) -> None:
        """reset() should clear disclosure tracker state for every agent."""
        dl = DaemonDataLayer()
        transcript_path = "/tmp/agent/transcript.jsonl"
        dl.disclosure.mark_disclosed(transcript_path, "R-GIT-RESET-HARD")
        dl.reset()
        assert dl.disclosure.was_disclosed(transcript_path, "R-GIT-RESET-HARD") is False


class TestGetDataLayer:
    """Test get_data_layer() singleton accessor."""

    def setup_method(self) -> None:
        """Reset global state before each test."""
        reset_data_layer()

    def teardown_method(self) -> None:
        """Reset global state after each test."""
        reset_data_layer()

    def test_returns_daemon_data_layer(self) -> None:
        """get_data_layer() should return a DaemonDataLayer instance."""
        dl = get_data_layer()
        assert isinstance(dl, DaemonDataLayer)

    def test_returns_same_instance(self) -> None:
        """get_data_layer() should return the same instance on multiple calls."""
        dl1 = get_data_layer()
        dl2 = get_data_layer()
        assert dl1 is dl2

    def test_reset_creates_new_instance(self) -> None:
        """reset_data_layer() should cause get_data_layer() to create new instance."""
        dl1 = get_data_layer()
        reset_data_layer()
        dl2 = get_data_layer()
        assert dl1 is not dl2


class TestDaemonDataLayerIntegration:
    """Test DaemonDataLayer components work together."""

    def test_session_update_accessible_after_set(self) -> None:
        """Data set via session should be accessible."""
        dl = DaemonDataLayer()
        dl.session.update_from_status_event(
            {
                "model": {"id": "claude-opus-4-6", "display_name": "Claude Opus 4.6"},
                "context_window": {"used_percentage": 42.0},
            }
        )
        assert dl.session.is_opus() is True
        assert dl.session.context_used_percentage == 42.0

    def test_history_record_accessible(self) -> None:
        """Decisions recorded via history should be queryable."""
        dl = DaemonDataLayer()
        dl.history.record(
            handler_id="destructive-git",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
            reason="Blocked force push",
        )
        assert dl.history.was_blocked(ToolName.BASH) is True
        assert dl.history.count_blocks() == 1


class TestSessionModesProperty:
    """The session-modes registry is built lazily from the daemon untracked dir (Plan 00501)."""

    @pytest.fixture
    def untracked(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(
            ProjectContext, "daemon_untracked_dir", classmethod(lambda cls: tmp_path)
        )
        return tmp_path

    def _surviving_file(self, untracked: Path) -> SessionModeEntry:
        entry = SessionModeEntry(
            mode=SessionMode.FOCUS,
            session_id="sid",
            entered_at=time.time(),
            expires_at=time.time() + 3600,
            source=ModeSource.HUMAN,
            detail="the task",
        )
        writer = SessionModeRegistry(untracked / SIGNAL_SUBDIR)
        writer.load()
        writer.enter(entry)
        return entry

    def test_builds_once_and_loads_the_state_dir(self, untracked: Path) -> None:
        entry = self._surviving_file(untracked)
        dl = DaemonDataLayer()
        registry = dl.session_modes
        assert registry is dl.session_modes
        assert registry.path_for("sid").parent == untracked / SIGNAL_SUBDIR
        assert registry.active("sid") == (entry,)
        assert [notice.kind for notice in registry.take_notices("sid")] == [
            NoticeKind.SURVIVED_RESTART
        ]

    def test_concurrent_first_access_builds_one_registry(self, untracked: Path) -> None:
        dl = DaemonDataLayer()
        seen: list[SessionModeRegistry] = []
        threads = [threading.Thread(target=lambda: seen.append(dl.session_modes)) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len({id(registry) for registry in seen}) == 1

    def test_no_project_context_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def uninitialised(cls: type[ProjectContext]) -> Path:
            raise RuntimeError("ProjectContext not initialized")

        monkeypatch.setattr(ProjectContext, "daemon_untracked_dir", classmethod(uninitialised))
        dl = DaemonDataLayer()
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = dl.session_modes

    def test_imports_the_legacy_marker_once(self, untracked: Path) -> None:
        marker = untracked / MARKER_FILENAME
        _legacy_marker(marker)
        registry = DaemonDataLayer().session_modes
        assert registry.policy("sid").is_blocked is True
        assert not marker.exists()
        assert DaemonDataLayer().session_modes.policy("sid").is_blocked is True

    def test_the_registry_logs_transitions_under_the_untracked_dir(self, untracked: Path) -> None:
        registry = DaemonDataLayer().session_modes
        log = registry.transition_log
        assert log is not None
        assert log.path == untracked / TRANSITION_LOG_FILENAME

    def test_the_legacy_import_is_logged_with_its_evidence(self, untracked: Path) -> None:
        _legacy_marker(untracked / MARKER_FILENAME)
        log = DaemonDataLayer().session_modes.transition_log
        assert log is not None
        [record] = log.recent(5)
        assert "legacy" in record.evidence

    def test_reset_drops_the_registry(self, untracked: Path) -> None:
        dl = DaemonDataLayer()
        first = dl.session_modes
        dl.reset()
        assert dl.session_modes is not first
