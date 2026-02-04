"""Tests for daemon path generation.

Tests project-aware socket and PID file path generation using MD5 hashing.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.daemon.paths import (
    cleanup_pid_file,
    cleanup_socket,
    get_log_path,
    get_pid_path,
    get_project_hash,
    get_project_name,
    get_socket_path,
    is_pid_alive,
    read_pid_file,
    write_pid_file,
)


class TestPathGeneration(unittest.TestCase):
    """Test suite for daemon path generation functions."""

    def test_get_socket_path_format(self):
        """Test socket path follows expected format."""
        project_dir = Path("/home/dev/my-project")
        socket_path = get_socket_path(project_dir)

        # Should be in project's untracked directory
        self.assertIn(".claude/hooks-daemon/untracked", str(socket_path))

        # Should have .sock extension (may include hostname suffix: daemon-laptop.sock)
        self.assertTrue(str(socket_path).endswith(".sock"))
        self.assertIn("daemon", socket_path.name)

        # Should be under the project directory
        self.assertTrue(str(socket_path).startswith("/home/dev/my-project/"))

    def test_get_pid_path_format(self):
        """Test PID path follows expected format."""
        project_dir = Path("/home/dev/my-project")
        pid_path = get_pid_path(project_dir)

        # Should be in project's untracked directory
        self.assertIn(".claude/hooks-daemon/untracked", str(pid_path))

        # Should have .pid extension (may include hostname suffix: daemon-laptop.pid)
        self.assertTrue(str(pid_path).endswith(".pid"))
        self.assertIn("daemon", pid_path.name)

        # Should be under the project directory
        self.assertTrue(str(pid_path).startswith("/home/dev/my-project/"))

    def test_same_project_returns_same_socket(self):
        """Test same project directory returns identical socket path."""
        project_dir = Path("/home/dev/project-alpha")

        socket1 = get_socket_path(project_dir)
        socket2 = get_socket_path(project_dir)

        self.assertEqual(socket1, socket2)

    def test_same_project_returns_same_pid(self):
        """Test same project directory returns identical PID path."""
        project_dir = Path("/home/dev/project-alpha")

        pid1 = get_pid_path(project_dir)
        pid2 = get_pid_path(project_dir)

        self.assertEqual(pid1, pid2)

    def test_different_projects_get_different_sockets(self):
        """Test different project directories get different socket paths."""
        project_alpha = Path("/home/dev/project-alpha")
        project_beta = Path("/home/dev/project-beta")

        socket_alpha = get_socket_path(project_alpha)
        socket_beta = get_socket_path(project_beta)

        self.assertNotEqual(socket_alpha, socket_beta)

    def test_different_projects_get_different_pids(self):
        """Test different project directories get different PID paths."""
        project_alpha = Path("/home/dev/project-alpha")
        project_beta = Path("/home/dev/project-beta")

        pid_alpha = get_pid_path(project_alpha)
        pid_beta = get_pid_path(project_beta)

        self.assertNotEqual(pid_alpha, pid_beta)

    def test_hash_uniqueness(self):
        """Test paths are unique for different projects."""
        project1 = Path("/home/dev/project-alpha")
        project2 = Path("/home/dev/project-beta")

        socket1 = get_socket_path(project1)
        socket2 = get_socket_path(project2)

        # Paths should be different (each in their own project directory)
        self.assertNotEqual(socket1, socket2)

        # Verify they're in different project directories
        self.assertIn("project-alpha", str(socket1))
        self.assertIn("project-beta", str(socket2))

    def test_hash_consistency(self):
        """Test path is consistent for same absolute path."""
        project = Path("/home/dev/my-project")

        socket1 = get_socket_path(project)
        socket2 = get_socket_path(project)

        # Paths should be identical for same project
        self.assertEqual(socket1, socket2)

    def test_project_name_truncation(self):
        """Test long project names are handled correctly."""
        long_name = "this-is-a-very-long-project-name-that-exceeds-twenty-characters"
        project_dir = Path(f"/home/dev/{long_name}")

        socket_path = get_socket_path(project_dir)

        # Path should be under the project directory (no truncation needed)
        self.assertIn(long_name, str(socket_path))

        # Should still be in untracked directory
        self.assertIn(".claude/hooks-daemon/untracked", str(socket_path))

    def test_relative_vs_absolute_paths(self):
        """Test relative and absolute paths produce different hashes."""
        relative_path = Path("my-project")
        absolute_path = Path("/home/dev/my-project")

        socket_rel = get_socket_path(relative_path)
        socket_abs = get_socket_path(absolute_path)

        # Should be different because absolute path is different
        self.assertNotEqual(socket_rel, socket_abs)

    def test_socket_and_pid_have_same_directory(self):
        """Test socket and PID paths are in the same directory for same project."""
        project_dir = Path("/home/dev/my-project")

        socket_path = get_socket_path(project_dir)
        pid_path = get_pid_path(project_dir)

        # Both should be in the same untracked directory
        self.assertEqual(socket_path.parent, pid_path.parent)

        # Both should be in the untracked directory
        self.assertIn(".claude/hooks-daemon/untracked", str(socket_path.parent))

    def test_returns_path_objects(self):
        """Test functions return Path objects, not strings."""
        project_dir = Path("/home/dev/my-project")

        socket_path = get_socket_path(project_dir)
        pid_path = get_pid_path(project_dir)

        self.assertIsInstance(socket_path, Path)
        self.assertIsInstance(pid_path, Path)

    def test_special_characters_in_path(self):
        """Test path generation handles special characters safely."""
        # Project path with spaces, dots, etc.
        project_dir = Path("/home/dev/my project.v2/sub-dir")

        socket_path = get_socket_path(project_dir)
        pid_path = get_pid_path(project_dir)

        # Should still generate valid paths in untracked directory
        self.assertIn(".claude/hooks-daemon/untracked", str(socket_path))
        self.assertIn(".claude/hooks-daemon/untracked", str(pid_path))

        # Paths should have expected extensions (may include hostname suffix)
        self.assertTrue(str(socket_path).endswith(".sock"))
        self.assertTrue(str(pid_path).endswith(".pid"))
        self.assertIn("daemon", socket_path.name)
        self.assertIn("daemon", pid_path.name)

    def test_accepts_string_paths(self):
        """Test functions accept string paths for backward compatibility."""
        project_str = "/home/dev/my-project"
        project_path = Path(project_str)

        # Both should produce identical results
        socket_from_str = get_socket_path(project_str)
        socket_from_path = get_socket_path(project_path)

        self.assertEqual(socket_from_str, socket_from_path)

        pid_from_str = get_pid_path(project_str)
        pid_from_path = get_pid_path(project_path)

        self.assertEqual(pid_from_str, pid_from_path)


class TestUtilityFunctions(unittest.TestCase):
    """Test suite for utility functions."""

    def test_get_project_hash_returns_8_characters(self):
        """Test get_project_hash returns 8-character hash."""
        project_path = Path("/home/dev/my-project")
        hash_result = get_project_hash(project_path)

        self.assertEqual(len(hash_result), 8)
        self.assertTrue(hash_result.isalnum())

    def test_get_project_hash_consistent(self):
        """Test get_project_hash returns same hash for same path."""
        project_path = Path("/home/dev/my-project")

        hash1 = get_project_hash(project_path)
        hash2 = get_project_hash(project_path)

        self.assertEqual(hash1, hash2)

    def test_get_project_hash_different_for_different_paths(self):
        """Test get_project_hash returns different hashes for different paths."""
        path1 = Path("/home/dev/project1")
        path2 = Path("/home/dev/project2")

        hash1 = get_project_hash(path1)
        hash2 = get_project_hash(path2)

        self.assertNotEqual(hash1, hash2)

    def test_get_project_hash_accepts_string(self):
        """Test get_project_hash accepts string paths."""
        project_str = "/home/dev/my-project"
        project_path = Path(project_str)

        hash_from_str = get_project_hash(project_str)
        hash_from_path = get_project_hash(project_path)

        self.assertEqual(hash_from_str, hash_from_path)

    def test_get_project_name_returns_last_component(self):
        """Test get_project_name returns directory name."""
        project_path = Path("/home/dev/my-awesome-project")
        name = get_project_name(project_path)

        self.assertEqual(name, "my-awesome-project")

    def test_get_project_name_truncates_long_names(self):
        """Test get_project_name truncates names longer than 20 characters."""
        long_name = "this-is-a-very-long-project-name-that-exceeds-twenty-characters"
        project_path = Path(f"/home/dev/{long_name}")

        name = get_project_name(project_path)

        self.assertLessEqual(len(name), 20)
        self.assertEqual(name, long_name[:20])

    def test_get_project_name_handles_root(self):
        """Test get_project_name handles root directory."""
        project_path = Path("/")
        name = get_project_name(project_path)

        # Root directory returns empty string (edge case)
        self.assertIsInstance(name, str)

    def test_get_log_path_format(self):
        """Test get_log_path follows expected format."""
        project_dir = Path("/home/dev/my-project")
        log_path = get_log_path(project_dir)

        # Should be in project's untracked directory
        self.assertIn(".claude/hooks-daemon/untracked", str(log_path))

        # Should have .log extension (may include hostname suffix: daemon-laptop.log)
        self.assertTrue(str(log_path).endswith(".log"))
        self.assertIn("daemon", log_path.name)

        # Should be under the project directory
        self.assertTrue(str(log_path).startswith("/home/dev/my-project/"))

    def test_get_log_path_consistent(self):
        """Test get_log_path returns same path for same project."""
        project_dir = Path("/home/dev/my-project")

        log1 = get_log_path(project_dir)
        log2 = get_log_path(project_dir)

        self.assertEqual(log1, log2)

    def test_get_log_path_accepts_string(self):
        """Test get_log_path accepts string paths."""
        project_str = "/home/dev/my-project"
        project_path = Path(project_str)

        log_from_str = get_log_path(project_str)
        log_from_path = get_log_path(project_path)

        self.assertEqual(log_from_str, log_from_path)


class TestPIDFileOperations(unittest.TestCase):
    """Test suite for PID file read/write/cleanup operations."""

    def test_write_pid_file_creates_file(self):
        """Test write_pid_file creates file with PID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "test.pid"
            test_pid = 12345

            write_pid_file(pid_path, test_pid)

            self.assertTrue(pid_path.exists())
            content = pid_path.read_text()
            self.assertEqual(content, "12345")

    def test_write_pid_file_accepts_string_path(self):
        """Test write_pid_file accepts string paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "test.pid"
            test_pid = 67890

            write_pid_file(str(pid_path), test_pid)

            self.assertTrue(pid_path.exists())

    def test_read_pid_file_returns_pid_for_alive_process(self):
        """Test read_pid_file returns PID when process is alive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "test.pid"
            current_pid = os.getpid()  # Current process is definitely alive

            write_pid_file(pid_path, current_pid)

            result = read_pid_file(pid_path)

            self.assertEqual(result, current_pid)

    def test_read_pid_file_returns_none_for_dead_process(self):
        """Test read_pid_file returns None for dead process and cleans up."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "test.pid"
            dead_pid = 999999  # Almost certainly not running

            write_pid_file(pid_path, dead_pid)

            result = read_pid_file(pid_path)

            self.assertIsNone(result)
            # Stale PID file should be cleaned up
            self.assertFalse(pid_path.exists())

    def test_read_pid_file_returns_none_for_missing_file(self):
        """Test read_pid_file returns None when file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "nonexistent.pid"

            result = read_pid_file(pid_path)

            self.assertIsNone(result)

    def test_read_pid_file_returns_none_for_invalid_content(self):
        """Test read_pid_file returns None for invalid PID content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "test.pid"
            pid_path.write_text("not-a-number")

            result = read_pid_file(pid_path)

            self.assertIsNone(result)

    def test_read_pid_file_accepts_string_path(self):
        """Test read_pid_file accepts string paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "test.pid"
            current_pid = os.getpid()

            write_pid_file(pid_path, current_pid)

            result = read_pid_file(str(pid_path))

            self.assertEqual(result, current_pid)

    def test_is_pid_alive_returns_true_for_current_process(self):
        """Test is_pid_alive returns True for current process."""
        current_pid = os.getpid()

        result = is_pid_alive(current_pid)

        self.assertTrue(result)

    def test_is_pid_alive_returns_false_for_nonexistent_process(self):
        """Test is_pid_alive returns False for nonexistent PID."""
        # PID 999999 is almost certainly not running
        result = is_pid_alive(999999)

        self.assertFalse(result)

    @patch("os.kill")
    def test_is_pid_alive_returns_true_on_permission_error(self, mock_kill):
        """Test is_pid_alive returns True when permission is denied."""
        mock_kill.side_effect = PermissionError("Access denied")

        result = is_pid_alive(12345)

        self.assertTrue(result)

    @patch("os.kill")
    def test_is_pid_alive_returns_false_on_general_exception(self, mock_kill):
        """Test is_pid_alive returns False on unexpected exceptions."""
        mock_kill.side_effect = RuntimeError("Unexpected error")

        result = is_pid_alive(12345)

        self.assertFalse(result)

    def test_cleanup_pid_file_removes_existing_file(self):
        """Test cleanup_pid_file removes existing PID file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "test.pid"
            pid_path.write_text("12345")

            cleanup_pid_file(pid_path)

            self.assertFalse(pid_path.exists())

    def test_cleanup_pid_file_handles_missing_file(self):
        """Test cleanup_pid_file handles missing file gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "nonexistent.pid"

            # Should not raise exception
            cleanup_pid_file(pid_path)

    def test_cleanup_pid_file_accepts_string_path(self):
        """Test cleanup_pid_file accepts string paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "test.pid"
            pid_path.write_text("12345")

            cleanup_pid_file(str(pid_path))

            self.assertFalse(pid_path.exists())

    @patch("pathlib.Path.unlink")
    def test_cleanup_pid_file_handles_exception(self, mock_unlink):
        """Test cleanup_pid_file handles exceptions during deletion."""
        mock_unlink.side_effect = PermissionError("Access denied")

        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "test.pid"
            pid_path.write_text("12345")

            # Should not raise exception
            cleanup_pid_file(pid_path)

    @patch("pathlib.Path.unlink")
    def test_cleanup_pid_file_handles_unexpected_exception(self, mock_unlink):
        """Test cleanup_pid_file logs unexpected exceptions."""
        mock_unlink.side_effect = RuntimeError("Unexpected error")

        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "test.pid"
            pid_path.write_text("12345")

            # Should not raise exception
            cleanup_pid_file(pid_path)


class TestSocketCleanup(unittest.TestCase):
    """Test suite for socket cleanup operations."""

    def test_cleanup_socket_removes_existing_file(self):
        """Test cleanup_socket removes existing socket file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "test.sock"
            socket_path.touch()  # Create empty file

            cleanup_socket(socket_path)

            self.assertFalse(socket_path.exists())

    def test_cleanup_socket_handles_missing_file(self):
        """Test cleanup_socket handles missing file gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "nonexistent.sock"

            # Should not raise exception
            cleanup_socket(socket_path)

    def test_cleanup_socket_accepts_string_path(self):
        """Test cleanup_socket accepts string paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "test.sock"
            socket_path.touch()

            cleanup_socket(str(socket_path))

            self.assertFalse(socket_path.exists())

    @patch("pathlib.Path.unlink")
    def test_cleanup_socket_handles_exception(self, mock_unlink):
        """Test cleanup_socket handles exceptions during deletion."""
        mock_unlink.side_effect = PermissionError("Access denied")

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "test.sock"
            socket_path.touch()

            # Should not raise exception
            cleanup_socket(socket_path)

    @patch("pathlib.Path.unlink")
    def test_cleanup_socket_handles_unexpected_exception(self, mock_unlink):
        """Test cleanup_socket logs unexpected exceptions."""
        mock_unlink.side_effect = RuntimeError("Unexpected error")

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "test.sock"
            socket_path.touch()

            # Should not raise exception
            cleanup_socket(socket_path)


class TestHostnameIsolation(unittest.TestCase):
    """Test hostname-based path isolation."""

    def test_socket_path_uses_raw_hostname(self):
        """Test socket path uses raw hostname as suffix."""
        with patch.dict(os.environ, {"HOSTNAME": "mycontainer"}):
            socket_path = get_socket_path("/workspace")
            self.assertTrue(str(socket_path).endswith("daemon-mycontainer.sock"))

    def test_socket_path_sanitizes_hostname(self):
        """Test hostname is sanitized (lowercase, no spaces)."""
        with patch.dict(os.environ, {"HOSTNAME": "My Server"}):
            socket_path = get_socket_path("/workspace")
            self.assertTrue(str(socket_path).endswith("daemon-my-server.sock"))

    def test_pid_path_uses_raw_hostname(self):
        """Test PID path uses raw hostname as suffix."""
        with patch.dict(os.environ, {"HOSTNAME": "container123"}):
            pid_path = get_pid_path("/workspace")
            self.assertTrue(str(pid_path).endswith("daemon-container123.pid"))

    def test_log_path_uses_raw_hostname(self):
        """Test log path uses raw hostname as suffix."""
        with patch.dict(os.environ, {"HOSTNAME": "webserver"}):
            log_path = get_log_path("/workspace")
            self.assertTrue(str(log_path).endswith("daemon-webserver.log"))

    def test_env_var_override_takes_precedence(self):
        """Test env var overrides hostname-based suffix."""
        with patch.dict(
            os.environ,
            {
                "HOSTNAME": "container-abc123",
                "CLAUDE_HOOKS_SOCKET_PATH": "/custom/path.sock",
            },
        ):
            socket_path = get_socket_path("/workspace")
            self.assertEqual(socket_path, Path("/custom/path.sock"))

    def test_different_hostnames_get_different_paths(self):
        """Test different hostnames get unique paths."""
        with patch.dict(os.environ, {"HOSTNAME": "machine-abc"}):
            socket_a = get_socket_path("/workspace")

        with patch.dict(os.environ, {"HOSTNAME": "machine-xyz"}):
            socket_b = get_socket_path("/workspace")

        self.assertNotEqual(socket_a, socket_b)
        self.assertTrue(str(socket_a).endswith("daemon-machine-abc.sock"))
        self.assertTrue(str(socket_b).endswith("daemon-machine-xyz.sock"))

    def test_numeric_hostname(self):
        """Test numeric hostname works correctly."""
        with patch.dict(os.environ, {"HOSTNAME": "506355bfbc76"}):
            socket_path = get_socket_path("/workspace")
            self.assertTrue(str(socket_path).endswith("daemon-506355bfbc76.sock"))

    def test_hostname_with_uppercase(self):
        """Test uppercase hostname is lowercased."""
        with patch.dict(os.environ, {"HOSTNAME": "PRODUCTION"}):
            socket_path = get_socket_path("/workspace")
            self.assertTrue(str(socket_path).endswith("daemon-production.sock"))

    def test_empty_hostname_gets_time_hash(self):
        """Test empty hostname gets time-based hash suffix."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove HOSTNAME if it exists
            os.environ.pop("HOSTNAME", None)
            socket_path = get_socket_path("/workspace")
            # Should get a time-based hash suffix (8 hex chars)
            self.assertRegex(str(socket_path), r"daemon-[a-f0-9]{8}\.sock")

    def test_suffix_consistency_same_hostname(self):
        """Test same hostname produces same suffix."""
        hostname = "test-machine"
        with patch.dict(os.environ, {"HOSTNAME": hostname}):
            socket1 = get_socket_path("/workspace")
            socket2 = get_socket_path("/workspace")
            self.assertEqual(socket1, socket2)
            self.assertTrue(str(socket1).endswith("daemon-test-machine.sock"))


if __name__ == "__main__":
    unittest.main()
