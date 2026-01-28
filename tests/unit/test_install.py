"""Tests for install.py validation functions.

Tests the installation validation functions that prevent nested installations.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path to import install.py
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from install import (
    InstallationError,
    _load_config_safe,
    _validate_not_nested,
    find_project_root,
    is_hooks_daemon_repo,
    validate_installation_target,
)


class TestIsHooksDaemonRepo:
    """Tests for is_hooks_daemon_repo function in install.py."""

    def test_returns_true_for_hooks_daemon_remote_https(self, tmp_path: Path) -> None:
        """Test detection of hooks-daemon repo via HTTPS URL."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/example/claude-code-hooks-daemon.git\n",
            )
            assert is_hooks_daemon_repo(tmp_path) is True

    def test_returns_true_for_hooks_daemon_remote_ssh(self, tmp_path: Path) -> None:
        """Test detection of hooks-daemon repo via SSH URL."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="git@github.com:example/claude-code-hooks-daemon.git\n",
            )
            assert is_hooks_daemon_repo(tmp_path) is True

    def test_returns_true_for_underscore_variant(self, tmp_path: Path) -> None:
        """Test detection of hooks-daemon repo with underscore in name."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/example/claude_code_hooks_daemon.git\n",
            )
            assert is_hooks_daemon_repo(tmp_path) is True

    def test_returns_false_for_other_repo(self, tmp_path: Path) -> None:
        """Test returns False for non-hooks-daemon repos."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/example/some-other-project.git\n",
            )
            assert is_hooks_daemon_repo(tmp_path) is False

    def test_returns_false_when_git_fails(self, tmp_path: Path) -> None:
        """Test returns False when git command fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert is_hooks_daemon_repo(tmp_path) is False

    def test_returns_false_on_timeout(self, tmp_path: Path) -> None:
        """Test returns False when git command times out."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("git", 5)
            assert is_hooks_daemon_repo(tmp_path) is False


class TestLoadConfigSafe:
    """Tests for _load_config_safe function."""

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        """Test returns None when config file doesn't exist."""
        result = _load_config_safe(tmp_path)
        assert result is None

    def test_loads_valid_yaml_config(self, tmp_path: Path) -> None:
        """Test loads valid YAML configuration."""
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "hooks-daemon.yaml"
        config_file.write_text("daemon:\n  self_install_mode: true\n")

        result = _load_config_safe(tmp_path)
        assert result is not None
        assert result["daemon"]["self_install_mode"] is True


class TestValidateNotNested:
    """Tests for _validate_not_nested function."""

    def test_raises_for_nested_claude_directory(self, tmp_path: Path) -> None:
        """Test raises InstallationError for nested .claude directory."""
        nested_claude = tmp_path / ".claude" / "hooks-daemon" / ".claude"
        nested_claude.mkdir(parents=True)

        with pytest.raises(InstallationError) as exc_info:
            _validate_not_nested(tmp_path)

        assert "NESTED INSTALLATION DETECTED" in str(exc_info.value)

    def test_raises_for_hooks_daemon_marker_without_config(self, tmp_path: Path) -> None:
        """Test raises for hooks-daemon marker without self_install_mode."""
        hooks_daemon_src = tmp_path / ".claude" / "hooks-daemon" / "src"
        hooks_daemon_src.mkdir(parents=True)

        with pytest.raises(InstallationError) as exc_info:
            _validate_not_nested(tmp_path)

        assert "inside an existing hooks-daemon installation" in str(exc_info.value)

    def test_allows_hooks_daemon_marker_with_self_install(self, tmp_path: Path) -> None:
        """Test allows hooks-daemon marker when self_install_mode is enabled."""
        hooks_daemon_src = tmp_path / ".claude" / "hooks-daemon" / "src"
        hooks_daemon_src.mkdir(parents=True)

        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.write_text("daemon:\n  self_install_mode: true\n")

        # Should not raise
        _validate_not_nested(tmp_path)

    def test_allows_clean_directory(self, tmp_path: Path) -> None:
        """Test allows clean directory without issues."""
        (tmp_path / ".claude").mkdir()

        # Should not raise
        _validate_not_nested(tmp_path)


class TestValidateInstallationTarget:
    """Tests for validate_installation_target function."""

    def test_raises_for_inside_existing_installation(self, tmp_path: Path) -> None:
        """Test raises when project is inside existing hooks-daemon installation."""
        # Create parent with hooks-daemon installation
        parent_install = tmp_path / "parent" / ".claude" / "hooks-daemon"
        parent_install.mkdir(parents=True)

        # Try to install in subdirectory
        project_root = tmp_path / "parent" / "subproject"
        project_root.mkdir(parents=True)

        with pytest.raises(InstallationError) as exc_info:
            validate_installation_target(project_root)

        assert "inside an existing installation" in str(exc_info.value)

    def test_raises_for_hooks_daemon_repo_without_flag(self, tmp_path: Path) -> None:
        """Test raises for hooks-daemon repo without self-install flag."""
        (tmp_path / ".git").mkdir()

        with patch("install.is_hooks_daemon_repo") as mock_check:
            mock_check.return_value = True

            with pytest.raises(InstallationError) as exc_info:
                validate_installation_target(tmp_path, self_install_requested=False)

            assert "hooks-daemon repository" in str(exc_info.value)

    def test_allows_hooks_daemon_repo_with_flag(self, tmp_path: Path) -> None:
        """Test allows hooks-daemon repo with self-install flag."""
        (tmp_path / ".git").mkdir()

        with patch("install.is_hooks_daemon_repo") as mock_check:
            mock_check.return_value = True

            # Should not raise
            validate_installation_target(tmp_path, self_install_requested=True)

    def test_allows_hooks_daemon_repo_with_config(self, tmp_path: Path) -> None:
        """Test allows hooks-daemon repo with self_install_mode in config."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(
            "daemon:\n  self_install_mode: true\n"
        )

        with patch("install.is_hooks_daemon_repo") as mock_check:
            mock_check.return_value = True

            # Should not raise
            validate_installation_target(tmp_path, self_install_requested=False)

    def test_allows_non_hooks_daemon_repo(self, tmp_path: Path) -> None:
        """Test allows non-hooks-daemon git repos."""
        (tmp_path / ".git").mkdir()

        with patch("install.is_hooks_daemon_repo") as mock_check:
            mock_check.return_value = False

            # Should not raise
            validate_installation_target(tmp_path)


class TestFindProjectRoot:
    """Tests for find_project_root function."""

    def test_returns_explicit_root_when_provided(self, tmp_path: Path) -> None:
        """Test returns explicit root when provided."""
        result = find_project_root(explicit_root=tmp_path)
        assert result == tmp_path.resolve()

    def test_finds_claude_directory_in_current(self, tmp_path: Path) -> None:
        """Test finds .claude directory in current directory."""
        (tmp_path / ".claude").mkdir()

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = find_project_root()
            assert result == tmp_path

    def test_finds_claude_directory_in_parent(self, tmp_path: Path) -> None:
        """Test finds .claude directory in parent directory."""
        (tmp_path / ".claude").mkdir()
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        with patch("pathlib.Path.cwd", return_value=subdir):
            result = find_project_root()
            assert result == tmp_path

    def test_returns_current_when_no_claude_found(self, tmp_path: Path) -> None:
        """Test returns current directory when no .claude found."""
        # tmp_path has no .claude directory

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = find_project_root()
            assert result == tmp_path
