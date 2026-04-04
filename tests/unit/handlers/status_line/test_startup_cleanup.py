"""Tests for StartupCleanupHandler."""

import json
import time
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.handlers.status_line.startup_cleanup import StartupCleanupHandler


class TestStartupCleanupHandler:
    """Tests for StartupCleanupHandler."""

    def _make_handler(self) -> StartupCleanupHandler:
        return StartupCleanupHandler()

    def test_init(self) -> None:
        h = self._make_handler()
        assert h.handler_id.config_key == "startup_cleanup"
        assert h.priority == 28
        assert h.terminal is False

    def test_matches_always_true(self) -> None:
        h = self._make_handler()
        assert h.matches({}) is True
        assert h.matches({"anything": "goes"}) is True

    def test_returns_empty_when_no_status_file(self, tmp_path: Path) -> None:
        h = self._make_handler()
        with patch(
            "claude_code_hooks_daemon.handlers.status_line.startup_cleanup.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            result = h.handle({})
        assert result.context == []

    def test_shows_brush_icon_during_startup_phase(self, tmp_path: Path) -> None:
        """Within first 5 seconds: show 🧹 only."""
        h = self._make_handler()
        status_file = tmp_path / "cleanup_status.json"
        status_file.write_text(json.dumps({"count": 3, "timestamp": time.time() - 2}))

        with patch(
            "claude_code_hooks_daemon.handlers.status_line.startup_cleanup.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            result = h.handle({})
        assert result.context == ["| 🧹"]

    def test_shows_count_in_result_phase(self, tmp_path: Path) -> None:
        """Between 5 and 30 seconds with files cleaned: show 🧹 N stale."""
        h = self._make_handler()
        status_file = tmp_path / "cleanup_status.json"
        status_file.write_text(json.dumps({"count": 7, "timestamp": time.time() - 10}))

        with patch(
            "claude_code_hooks_daemon.handlers.status_line.startup_cleanup.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            result = h.handle({})
        assert result.context == ["| 🧹 7 stale"]

    def test_shows_nothing_after_display_window(self, tmp_path: Path) -> None:
        """After 30 seconds: show nothing."""
        h = self._make_handler()
        status_file = tmp_path / "cleanup_status.json"
        status_file.write_text(json.dumps({"count": 5, "timestamp": time.time() - 60}))

        with patch(
            "claude_code_hooks_daemon.handlers.status_line.startup_cleanup.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            result = h.handle({})
        assert result.context == []

    def test_shows_nothing_in_result_phase_when_zero_cleaned(self, tmp_path: Path) -> None:
        """5-30 seconds but count=0: no result message needed."""
        h = self._make_handler()
        status_file = tmp_path / "cleanup_status.json"
        status_file.write_text(json.dumps({"count": 0, "timestamp": time.time() - 10}))

        with patch(
            "claude_code_hooks_daemon.handlers.status_line.startup_cleanup.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            result = h.handle({})
        assert result.context == []

    def test_shows_brush_icon_during_startup_phase_even_when_zero_cleaned(
        self, tmp_path: Path
    ) -> None:
        """Within first 5 seconds: show 🧹 even if 0 files cleaned."""
        h = self._make_handler()
        status_file = tmp_path / "cleanup_status.json"
        status_file.write_text(json.dumps({"count": 0, "timestamp": time.time() - 1}))

        with patch(
            "claude_code_hooks_daemon.handlers.status_line.startup_cleanup.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            result = h.handle({})
        assert result.context == ["| 🧹"]

    def test_handles_corrupt_status_file_gracefully(self, tmp_path: Path) -> None:
        """Malformed JSON returns empty context without crashing."""
        h = self._make_handler()
        (tmp_path / "cleanup_status.json").write_text("not valid json{{{")

        with patch(
            "claude_code_hooks_daemon.handlers.status_line.startup_cleanup.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            result = h.handle({})
        assert result.context == []

    def test_handles_oserror_gracefully(self, tmp_path: Path) -> None:
        """OSError reading the file returns empty context without crashing."""
        h = self._make_handler()

        with patch(
            "claude_code_hooks_daemon.handlers.status_line.startup_cleanup.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.read_text", side_effect=OSError("disk error")):
                    result = h.handle({})
        assert result.context == []
