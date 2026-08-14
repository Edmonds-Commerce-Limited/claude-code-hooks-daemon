"""Tests for StartupCleanupHandler."""

import json
import os
import time
from pathlib import Path
from typing import Any
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
        # A REAL file, so the read is genuinely attempted. Patching `exists` to
        # lie about a file that is not there made this vacuous once the read
        # moved behind an mtime gate: stat() failed first and read_text was
        # never reached, so the test passed without exercising anything.
        (tmp_path / "cleanup_status.json").write_text("{}")

        with patch(
            "claude_code_hooks_daemon.handlers.status_line.startup_cleanup.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            with patch("pathlib.Path.read_text", side_effect=OSError("disk error")):
                result = h.handle({})
        assert result.context == []

    def test_a_non_object_json_document_does_not_crash_the_render(self, tmp_path: Path) -> None:
        """A JSON array parsed fine and then blew up on ``.get``.

        The old body caught OSError/JSONDecodeError/KeyError, none of which is
        the AttributeError a list produces — so a malformed-but-valid cleanup
        file would have propagated out of ``handle()`` and taken the whole
        status line with it. Status-line reads are fail-silent by contract
        (see this directory's CLAUDE.md).
        """
        h = self._make_handler()
        (tmp_path / "cleanup_status.json").write_text("[1, 2, 3]")

        with patch(
            "claude_code_hooks_daemon.handlers.status_line.startup_cleanup.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            result = h.handle({})
        assert result.context == []


class TestTheReadIsMtimeGated:
    """Plan 00238 Task 3.2 — ``cleanup_status.json`` is written ONCE, at daemon
    startup, and then read on every render for the life of the process.

    After the 30-second display window the handler can never emit a segment
    again, yet it kept paying ``exists()`` + ``read_text()`` + ``json.loads()``
    ~3,100 times an hour to re-learn that. The mtime gate keeps the stat (so a
    rewritten file is still noticed, preserving the display) and drops the rest.
    """

    def _make_handler(self) -> StartupCleanupHandler:
        return StartupCleanupHandler()

    def test_repeat_renders_do_not_reread_the_file(self, tmp_path: Path) -> None:
        status_file = tmp_path / "cleanup_status.json"
        status_file.write_text(json.dumps({"timestamp": time.time(), "count": 3}))
        real_read_text = Path.read_text
        reads: list[str] = []

        def counting_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
            reads.append(str(self))
            return real_read_text(self, *args, **kwargs)

        with patch(
            "claude_code_hooks_daemon.handlers.status_line.startup_cleanup.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            with patch("pathlib.Path.read_text", counting_read_text):
                for _ in range(5):
                    self._make_handler().handle({})

        assert reads.count(str(status_file)) == 1

    def test_a_rewritten_file_is_still_picked_up(self, tmp_path: Path) -> None:
        """Anti-vacuity companion: the gate must not LATCH.

        A second ``hooks-daemon start`` against a live daemon rewrites this
        file; a handler that stopped looking would silently never show 🧹
        again. That would be a display change, which this plan forbids.
        """
        status_file = tmp_path / "cleanup_status.json"
        status_file.write_text(json.dumps({"timestamp": time.time() - 100, "count": 3}))
        handler = self._make_handler()

        with patch(
            "claude_code_hooks_daemon.handlers.status_line.startup_cleanup.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            assert handler.handle({}).context == []

            status_file.write_text(json.dumps({"timestamp": time.time(), "count": 7}))
            stat = status_file.stat()
            os.utime(status_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

            assert handler.handle({}).context == ["| 🧹"]
