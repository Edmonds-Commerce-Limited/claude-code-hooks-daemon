"""Tests for claude_code_hooks_daemon.supervise.decision_log.DecisionLog."""

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.supervise.decision_log import DecisionLog


class TestDecisionLogExplicitPath:
    """Tests using an explicit path (no ProjectContext dependency)."""

    def test_write_appends_timestamped_line(self, tmp_path: Path) -> None:
        """write() appends a line containing the message and a timestamp."""
        log_path = tmp_path / "decision.log"
        log = DecisionLog(log_path)

        log.write("supervisor active (dry-run)")

        contents = log_path.read_text(encoding="utf-8")
        assert "supervisor active (dry-run)" in contents
        # ISO-8601 timestamps contain a 'T' date/time separator.
        assert "T" in contents.splitlines()[0]

    def test_write_appends_multiple_lines(self, tmp_path: Path) -> None:
        """Successive write() calls append rather than overwrite."""
        log_path = tmp_path / "decision.log"
        log = DecisionLog(log_path)

        log.write("first")
        log.write("second")

        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert lines[0].endswith("first")
        assert lines[1].endswith("second")

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """The parent directory is created if missing."""
        log_path = tmp_path / "nested" / "dir" / "decision.log"

        log = DecisionLog(log_path)
        log.write("hello")

        assert log_path.exists()

    def test_path_property_returns_configured_path(self, tmp_path: Path) -> None:
        """The `path` property exposes the resolved log file path."""
        log_path = tmp_path / "decision.log"
        log = DecisionLog(log_path)

        assert log.path == log_path

    def test_unwritable_path_raises(self, tmp_path: Path) -> None:
        """FAIL FAST: an unwritable path raises rather than being swallowed."""
        # Create a file where a directory is expected, so mkdir(parents=True)
        # fails with NotADirectoryError when trying to create the parent.
        blocker = tmp_path / "not_a_dir"
        blocker.write_text("i am a file, not a directory")
        log_path = blocker / "sub" / "decision.log"

        with pytest.raises(OSError):
            DecisionLog(log_path)


class TestDecisionLogDefaultPath:
    """Tests using the default (ProjectContext-derived) path."""

    def test_default_path_uses_project_context_untracked_dir(self, tmp_path: Path) -> None:
        """With no explicit path, the log lives under the daemon untracked dir."""
        untracked_dir = tmp_path / "untracked"

        with patch(
            "claude_code_hooks_daemon.supervise.decision_log.ProjectContext.daemon_untracked_dir",
            return_value=untracked_dir,
        ):
            log = DecisionLog()

        assert log.path == untracked_dir / "supervise" / "decision.log"
