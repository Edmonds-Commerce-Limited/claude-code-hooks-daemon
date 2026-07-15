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
    _project_root_is_daemon_repo,
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

    def test_raises_for_nested_hooks_daemon_install(self, tmp_path: Path) -> None:
        """Test raises InstallationError for nested hooks-daemon installation."""
        nested_install = tmp_path / ".claude" / "hooks-daemon" / ".claude" / "hooks-daemon"
        nested_install.mkdir(parents=True)

        with pytest.raises(InstallationError) as exc_info:
            _validate_not_nested(tmp_path)

        assert "NESTED INSTALLATION DETECTED" in str(exc_info.value)

    def test_allows_hooks_daemon_with_own_claude_dir(self, tmp_path: Path) -> None:
        """Test allows .claude/hooks-daemon/.claude without nested hooks-daemon."""
        nested_claude = tmp_path / ".claude" / "hooks-daemon" / ".claude"
        nested_claude.mkdir(parents=True)

        # Should not raise - .claude dir inside hooks-daemon repo is fine
        _validate_not_nested(tmp_path)

    def test_allows_consumer_clone_of_daemon_marker(self, tmp_path: Path) -> None:
        """Regression (Issue #3): a consumer project that cloned the daemon into
        .claude/hooks-daemon/ (creating .claude/hooks-daemon/src) is a NORMAL
        install, not a nested one. It must NOT raise even without
        self_install_mode - this is the documented manual-install layout.
        """
        (tmp_path / ".claude" / "hooks-daemon" / "src").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "some-consumer-app"\n')

        # Should NOT raise - the daemon clone under .claude/ is a dependency
        _validate_not_nested(tmp_path)

    def test_allows_consumer_clone_without_project_pyproject(self, tmp_path: Path) -> None:
        """Regression (Issue #3): consumer with the daemon clone marker but no
        pyproject.toml at project root must also be allowed."""
        (tmp_path / ".claude" / "hooks-daemon" / "src").mkdir(parents=True)

        # Should NOT raise
        _validate_not_nested(tmp_path)

    def test_raises_when_project_root_is_daemon_repo_without_config(self, tmp_path: Path) -> None:
        """Installing with project_root == the daemon repo itself (pyproject names
        the daemon package) and no self_install_mode must fail fast."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "claude-code-hooks-daemon"\n')
        (tmp_path / "src").mkdir()

        with pytest.raises(InstallationError) as exc_info:
            _validate_not_nested(tmp_path)

        assert "hooks-daemon repository itself" in str(exc_info.value)

    def test_allows_daemon_repo_with_self_install_mode(self, tmp_path: Path) -> None:
        """The daemon repo itself is allowed when self_install_mode is enabled."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "claude-code-hooks-daemon"\n')
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(
            "daemon:\n  self_install_mode: true\n"
        )

        # Should not raise
        _validate_not_nested(tmp_path)


class TestProjectRootIsDaemonRepo:
    """Tests for _project_root_is_daemon_repo (offline daemon-repo detection)."""

    def test_true_when_pyproject_names_the_package(self, tmp_path: Path) -> None:
        """True when pyproject.toml declares this daemon package as its name."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "claude-code-hooks-daemon"\nversion = "1.0.0"\n'
        )
        assert _project_root_is_daemon_repo(tmp_path) is True

    def test_false_for_other_package(self, tmp_path: Path) -> None:
        """False for a consumer project whose pyproject names a different package."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "other-app"\n')
        assert _project_root_is_daemon_repo(tmp_path) is False

    def test_false_when_no_pyproject(self, tmp_path: Path) -> None:
        """False when there is no pyproject.toml at project root."""
        assert _project_root_is_daemon_repo(tmp_path) is False

    def test_false_for_malformed_toml(self, tmp_path: Path) -> None:
        """False (not a crash) when pyproject.toml is malformed."""
        (tmp_path / "pyproject.toml").write_text("this is [ not valid toml")
        assert _project_root_is_daemon_repo(tmp_path) is False

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
