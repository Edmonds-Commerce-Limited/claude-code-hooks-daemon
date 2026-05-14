"""Comprehensive tests for CleanupHandler."""

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.session_end.cleanup_handler import CleanupHandler


class TestCleanupHandler:
    """Test suite for CleanupHandler."""

    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        """Patch ProjectContext.daemon_untracked_dir so handler resolves into tmp_path."""
        with patch(
            "claude_code_hooks_daemon.handlers.session_end.cleanup_handler.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            yield

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return CleanupHandler()

    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'session-cleanup'."""
        assert handler.name == "session-cleanup"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 100."""
        assert handler.priority == 100

    def test_init_is_non_terminal(self, handler):
        """Handler should be non-terminal."""
        assert handler.terminal is False

    def test_matches_always_returns_true(self, handler):
        """Should match all session end events."""
        hook_input = {"reason": "user_exit"}
        assert handler.matches(hook_input) is True

    def test_handle_cleans_temp_directory(self, handler, tmp_path: Path):
        """Should delete files in untracked/temp/hooks/."""
        temp_dir = tmp_path / "temp" / "hooks"
        temp_dir.mkdir(parents=True)
        (temp_dir / "file1.txt").write_text("a")
        (temp_dir / "file2.txt").write_text("b")

        handler.handle({})

        assert not (temp_dir / "file1.txt").exists()
        assert not (temp_dir / "file2.txt").exists()

    def test_handle_temp_dir_not_exists(self, handler, tmp_path: Path):
        """Should handle gracefully when temp dir doesn't exist."""
        # No temp/hooks created under tmp_path.
        result = handler.handle({})
        assert result.decision == "allow"

    def test_handle_returns_allow_decision(self, handler):
        """Should return allow decision."""
        result = handler.handle({})
        assert result.decision == "allow"

    def test_handle_gracefully_handles_deletion_errors(self, handler, tmp_path: Path):
        """Should handle file deletion errors gracefully."""
        temp_dir = tmp_path / "temp" / "hooks"
        temp_dir.mkdir(parents=True)
        target = temp_dir / "stuck.txt"
        target.write_text("x")

        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            result = handler.handle({})

        assert result.decision == "allow"

    def test_handle_skips_non_files(self, handler, tmp_path: Path):
        """Should skip directories and only delete files."""
        temp_dir = tmp_path / "temp" / "hooks"
        temp_dir.mkdir(parents=True)
        (temp_dir / "real_file.txt").write_text("a")
        (temp_dir / "subdir").mkdir()

        handler.handle({})

        assert not (temp_dir / "real_file.txt").exists()
        assert (temp_dir / "subdir").is_dir()

    def test_handle_returns_hook_result_instance(self, handler):
        """Should return HookResult instance."""
        result = handler.handle({})
        assert isinstance(result, HookResult)

    def test_handle_has_no_context(self, handler):
        """Should not provide context."""
        result = handler.handle({})
        assert result.context == []

    # Path resolution test (regression: Issue 3 — relative path → never finds
    # temp dir when daemon CWD is /). Temp dir must be resolved under
    # ProjectContext.daemon_untracked_dir(), not a CWD-relative path.
    def test_handle_resolves_temp_dir_under_project_untracked_dir(
        self, handler, tmp_path: Path
    ):
        """Cleanup must operate on temp dir under daemon_untracked_dir()."""
        temp_dir = tmp_path / "temp" / "hooks"
        temp_dir.mkdir(parents=True)
        stale_file = temp_dir / "stale.txt"
        stale_file.write_text("delete me")

        result = handler.handle({})

        assert result.decision == "allow"
        assert not stale_file.exists(), "Stale file should have been cleaned up"
