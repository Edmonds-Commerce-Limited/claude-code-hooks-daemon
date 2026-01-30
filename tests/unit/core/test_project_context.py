"""Tests for ProjectContext singleton."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext


class TestProjectContextInitialization:
    """Test ProjectContext initialization and validation."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    def test_initialize_with_valid_config_normal_mode(self, tmp_path: Path) -> None:
        """Initialize with valid config in normal install mode."""
        # Setup: Create normal install structure
        # /tmp/project/.claude/hooks-daemon.yaml (config)
        # /tmp/project/.claude/hooks-daemon/src/... (daemon installed here)
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        # Mock git commands for normal mode
        with patch("subprocess.run") as mock_run:
            # git rev-parse --show-toplevel
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),
                # git remote get-url origin
                MagicMock(returncode=0, stdout=b"git@github.com:user/test-repo.git\n"),
                # git rev-parse --show-toplevel (again for git_toplevel)
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),
            ]

            ProjectContext.initialize(config_path)

        # Verify state
        assert ProjectContext.project_root() == project_root
        assert ProjectContext.config_path() == config_path
        assert ProjectContext.config_dir() == claude_dir
        assert ProjectContext.self_install_mode() is False
        assert ProjectContext.git_repo_name() == "test-repo"
        assert ProjectContext.git_toplevel() == Path("/tmp/project")

    def test_initialize_with_valid_config_self_install_mode(self, tmp_path: Path) -> None:
        """Initialize with valid config in self-install mode (dogfooding)."""
        # Setup: Create self-install structure (daemon source at project root)
        # /tmp/daemon-project/.claude/hooks-daemon.yaml (config)
        # /tmp/daemon-project/src/claude_code_hooks_daemon/... (daemon source here)
        project_root = tmp_path / "daemon-project"
        claude_dir = project_root / ".claude"
        daemon_src = project_root / "src" / "claude_code_hooks_daemon"
        daemon_src.mkdir(parents=True)
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        # Mock git commands for self-install mode
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=b"/tmp/daemon-project\n"),
                MagicMock(returncode=0, stdout=b"https://github.com/org/daemon.git\n"),
                MagicMock(returncode=0, stdout=b"/tmp/daemon-project\n"),
            ]

            ProjectContext.initialize(config_path)

        # Verify self-install mode detected
        assert ProjectContext.self_install_mode() is True
        assert ProjectContext.project_root() == project_root
        assert ProjectContext.git_repo_name() == "daemon"

    def test_initialize_fails_if_config_does_not_exist(self, tmp_path: Path) -> None:
        """FAIL FAST: Initialize fails if config file doesn't exist."""
        nonexistent = tmp_path / "nonexistent.yaml"

        with pytest.raises(ValueError, match="Config file does not exist"):
            ProjectContext.initialize(nonexistent)

    def test_initialize_fails_if_config_is_directory(self, tmp_path: Path) -> None:
        """FAIL FAST: Initialize fails if config path is a directory."""
        dir_path = tmp_path / "config-dir"
        dir_path.mkdir()

        with pytest.raises(ValueError, match="Config path is not a file"):
            ProjectContext.initialize(dir_path)

    def test_initialize_fails_if_config_name_wrong(self, tmp_path: Path) -> None:
        """FAIL FAST: Initialize fails if config file has wrong name."""
        wrong_name = tmp_path / ".claude" / "wrong-name.yaml"
        wrong_name.parent.mkdir(parents=True)
        wrong_name.write_text("version: 1.0\n")

        with pytest.raises(ValueError, match="must be named 'hooks-daemon.yaml'"):
            ProjectContext.initialize(wrong_name)

    def test_initialize_fails_if_not_in_claude_directory(self, tmp_path: Path) -> None:
        """FAIL FAST: Initialize fails if config not in .claude directory."""
        wrong_dir = tmp_path / "wrong-dir" / "hooks-daemon.yaml"
        wrong_dir.parent.mkdir(parents=True)
        wrong_dir.write_text("version: 1.0\n")

        with pytest.raises(ValueError, match="must be in .claude directory"):
            ProjectContext.initialize(wrong_dir)

    def test_initialize_fails_if_not_in_git_repo(self, tmp_path: Path) -> None:
        """FAIL FAST: Initialize fails if project is not a git repository."""
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        # Mock git command failure (not a git repo)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout=b"", stderr=b"not a git repo")

            with pytest.raises(ValueError, match="FAIL FAST.*not a git repository"):
                ProjectContext.initialize(config_path)

    def test_initialize_fails_if_no_git_remote(self, tmp_path: Path) -> None:
        """FAIL FAST: Initialize fails if git repo has no remote origin."""
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        # Mock: git repo exists but no remote
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),  # git rev-parse (in repo)
                MagicMock(
                    returncode=128, stdout=b"", stderr=b"no remote"
                ),  # git remote (no origin)
            ]

            with pytest.raises(ValueError, match="FAIL FAST.*not a git repository"):
                ProjectContext.initialize(config_path)

    def test_initialize_fails_if_called_twice(self, tmp_path: Path) -> None:
        """FAIL FAST: Cannot initialize twice."""
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),
                MagicMock(returncode=0, stdout=b"git@github.com:user/repo.git\n"),
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),
            ]
            ProjectContext.initialize(config_path)

        # Second initialization should fail
        with pytest.raises(RuntimeError, match="already initialized"):
            ProjectContext.initialize(config_path)


class TestProjectContextAccess:
    """Test accessing ProjectContext properties."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    def test_access_before_initialization_fails(self) -> None:
        """FAIL FAST: Accessing ProjectContext before initialization fails."""
        with pytest.raises(RuntimeError, match="not initialized"):
            ProjectContext.project_root()

        with pytest.raises(RuntimeError, match="not initialized"):
            ProjectContext.git_repo_name()

        with pytest.raises(RuntimeError, match="not initialized"):
            ProjectContext.git_toplevel()

    def test_all_accessors_after_initialization(self, tmp_path: Path) -> None:
        """All accessor methods work after initialization."""
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),
                MagicMock(returncode=0, stdout=b"https://github.com/org/my-repo.git\n"),
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),
            ]
            ProjectContext.initialize(config_path)

        # All accessors should work
        assert ProjectContext.project_root() == project_root
        assert ProjectContext.config_path() == config_path
        assert ProjectContext.config_dir() == claude_dir
        assert isinstance(ProjectContext.self_install_mode(), bool)
        assert ProjectContext.git_repo_name() == "my-repo"
        assert ProjectContext.git_toplevel() == Path("/tmp/project")


class TestGitRepoNameParsing:
    """Test git remote URL parsing logic."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    def test_parse_ssh_url(self, tmp_path: Path) -> None:
        """Parse SSH format git URL correctly."""
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),
                MagicMock(returncode=0, stdout=b"git@github.com:user/ssh-repo.git\n"),
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),
            ]
            ProjectContext.initialize(config_path)

        assert ProjectContext.git_repo_name() == "ssh-repo"

    def test_parse_https_url(self, tmp_path: Path) -> None:
        """Parse HTTPS format git URL correctly."""
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),
                MagicMock(returncode=0, stdout=b"https://github.com/org/https-repo.git\n"),
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),
            ]
            ProjectContext.initialize(config_path)

        assert ProjectContext.git_repo_name() == "https-repo"

    def test_parse_url_without_git_extension(self, tmp_path: Path) -> None:
        """Parse git URL without .git extension."""
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),
                MagicMock(returncode=0, stdout=b"https://github.com/org/no-extension\n"),
                MagicMock(returncode=0, stdout=b"/tmp/project\n"),
            ]
            ProjectContext.initialize(config_path)

        assert ProjectContext.git_repo_name() == "no-extension"
