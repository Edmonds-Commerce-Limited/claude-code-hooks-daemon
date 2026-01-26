"""Tests for daemon path generation.

Tests project-aware socket and PID file path generation using MD5 hashing.
"""

import unittest
from pathlib import Path

from claude_code_hooks_daemon.daemon.paths import get_pid_path, get_socket_path


class TestPathGeneration(unittest.TestCase):
    """Test suite for daemon path generation functions."""

    def test_get_socket_path_format(self):
        """Test socket path follows expected format."""
        project_dir = Path("/home/dev/my-project")
        socket_path = get_socket_path(project_dir)

        # Should be in /tmp/
        self.assertTrue(str(socket_path).startswith("/tmp/"))

        # Should have .sock extension
        self.assertTrue(str(socket_path).endswith(".sock"))

        # Should contain 'claude-hooks' prefix
        self.assertIn("claude-hooks", str(socket_path))

        # Should contain project name (truncated to 20 chars)
        self.assertIn("my-project", str(socket_path))

    def test_get_pid_path_format(self):
        """Test PID path follows expected format."""
        project_dir = Path("/home/dev/my-project")
        pid_path = get_pid_path(project_dir)

        # Should be in /tmp/
        self.assertTrue(str(pid_path).startswith("/tmp/"))

        # Should have .pid extension
        self.assertTrue(str(pid_path).endswith(".pid"))

        # Should contain 'claude-hooks' prefix
        self.assertIn("claude-hooks", str(pid_path))

        # Should contain project name
        self.assertIn("my-project", str(pid_path))

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
        """Test hash portion is unique for different paths."""
        project1 = Path("/home/dev/project-alpha")
        project2 = Path("/home/dev/project-beta")

        socket1 = get_socket_path(project1)
        socket2 = get_socket_path(project2)

        # Extract hash portions (should be different)
        # Format: /tmp/claude-hooks-{name}-{hash}.sock
        parts1 = str(socket1).split("-")
        parts2 = str(socket2).split("-")

        # Get hash portion (last part before .sock)
        hash1 = parts1[-1].replace(".sock", "")
        hash2 = parts2[-1].replace(".sock", "")

        self.assertNotEqual(hash1, hash2)
        # Hash should be 8 characters (first 8 of MD5)
        self.assertEqual(len(hash1), 8)
        self.assertEqual(len(hash2), 8)

    def test_hash_consistency(self):
        """Test hash is consistent for same absolute path."""
        project = Path("/home/dev/my-project")

        socket1 = get_socket_path(project)
        socket2 = get_socket_path(project)

        # Extract hash portions
        hash1 = str(socket1).split("-")[-1].replace(".sock", "")
        hash2 = str(socket2).split("-")[-1].replace(".sock", "")

        self.assertEqual(hash1, hash2)

    def test_project_name_truncation(self):
        """Test long project names are truncated to 20 characters."""
        long_name = "this-is-a-very-long-project-name-that-exceeds-twenty-characters"
        project_dir = Path(f"/home/dev/{long_name}")

        socket_path = get_socket_path(project_dir)
        filename = Path(socket_path).name

        # Extract project name portion (between claude-hooks- and hash)
        # Format: claude-hooks-{name}-{hash}.sock
        parts = filename.replace("claude-hooks-", "").split("-")
        # Everything except last part (which is hash.sock) is the name
        project_name = "-".join(parts[:-1])

        # Should be truncated to 20 chars
        self.assertLessEqual(len(project_name), 20)

    def test_relative_vs_absolute_paths(self):
        """Test relative and absolute paths produce different hashes."""
        relative_path = Path("my-project")
        absolute_path = Path("/home/dev/my-project")

        socket_rel = get_socket_path(relative_path)
        socket_abs = get_socket_path(absolute_path)

        # Should be different because absolute path is different
        self.assertNotEqual(socket_rel, socket_abs)

    def test_socket_and_pid_have_same_hash(self):
        """Test socket and PID paths use the same hash for same project."""
        project_dir = Path("/home/dev/my-project")

        socket_path = get_socket_path(project_dir)
        pid_path = get_pid_path(project_dir)

        # Extract hash from socket path
        socket_hash = str(socket_path).split("-")[-1].replace(".sock", "")
        # Extract hash from PID path
        pid_hash = str(pid_path).split("-")[-1].replace(".pid", "")

        # Hashes should be identical
        self.assertEqual(socket_hash, pid_hash)

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

        # Should still generate valid paths
        self.assertTrue(str(socket_path).startswith("/tmp/"))
        self.assertTrue(str(pid_path).startswith("/tmp/"))

        # Hash should be consistent
        socket_hash = str(socket_path).split("-")[-1].replace(".sock", "")
        self.assertEqual(len(socket_hash), 8)

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


if __name__ == "__main__":
    unittest.main()
