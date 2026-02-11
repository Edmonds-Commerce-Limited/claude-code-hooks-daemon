"""Tests for daemon validation functions.

Tests the validation functions that prevent nested installations and detect
the hooks-daemon repository.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.daemon.validation import (
    InstallationError,
    check_for_nested_installation,
    is_hooks_daemon_repo,
    is_inside_daemon_directory,
    load_config_safe,
    validate_installation_target,
    validate_not_nested,
)


class TestIsHooksDaemonRepo:
    """Tests for is_hooks_daemon_repo function."""

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

    def test_returns_false_when_git_not_found(self, tmp_path: Path) -> None:
        """Test returns False when git is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            assert is_hooks_daemon_repo(tmp_path) is False

    def test_case_insensitive_matching(self, tmp_path: Path) -> None:
        """Test that URL matching is case insensitive."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/Example/Claude-Code-Hooks-Daemon.git\n",
            )
            assert is_hooks_daemon_repo(tmp_path) is True


class TestLoadConfigSafe:
    """Tests for load_config_safe function."""

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        """Test returns None when config file doesn't exist."""
        result = load_config_safe(tmp_path)
        assert result is None

    def test_loads_valid_yaml_config(self, tmp_path: Path) -> None:
        """Test loads valid YAML configuration."""
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "hooks-daemon.yaml"
        config_file.write_text("daemon:\n  self_install_mode: true\n")

        result = load_config_safe(tmp_path)
        assert result is not None
        assert result["daemon"]["self_install_mode"] is True

    def test_returns_none_for_invalid_yaml(self, tmp_path: Path) -> None:
        """Test returns None for invalid YAML."""
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "hooks-daemon.yaml"
        config_file.write_text("invalid: yaml: content: [")

        result = load_config_safe(tmp_path)
        assert result is None


class TestValidateNotNested:
    """Tests for validate_not_nested function."""

    def test_cleans_up_nested_hooks_daemon_install(self, tmp_path: Path) -> None:
        """Test actively removes nested hooks-daemon installation artifacts."""
        nested_install = tmp_path / ".claude" / "hooks-daemon" / ".claude" / "hooks-daemon"
        nested_install.mkdir(parents=True)

        # Should NOT raise - nested artifacts are cleaned up automatically
        validate_not_nested(tmp_path)

        # Nested install directory should be removed
        assert not nested_install.exists()
        # Parent .claude dir inside hooks-daemon should still exist
        assert (tmp_path / ".claude" / "hooks-daemon" / ".claude").exists()

    def test_allows_hooks_daemon_with_own_claude_dir(self, tmp_path: Path) -> None:
        """Test allows .claude/hooks-daemon/.claude without nested hooks-daemon."""
        nested_claude = tmp_path / ".claude" / "hooks-daemon" / ".claude"
        nested_claude.mkdir(parents=True)

        # Should not raise - .claude dir inside hooks-daemon repo is fine
        validate_not_nested(tmp_path)

    def test_raises_for_hooks_daemon_marker_without_config(self, tmp_path: Path) -> None:
        """Test raises for hooks-daemon marker without self_install_mode."""
        hooks_daemon_src = tmp_path / ".claude" / "hooks-daemon" / "src"
        hooks_daemon_src.mkdir(parents=True)

        with pytest.raises(InstallationError) as exc_info:
            validate_not_nested(tmp_path)

        assert "inside an existing hooks-daemon installation" in str(exc_info.value)

    def test_allows_hooks_daemon_marker_with_self_install(self, tmp_path: Path) -> None:
        """Test allows hooks-daemon marker when self_install_mode is enabled."""
        hooks_daemon_src = tmp_path / ".claude" / "hooks-daemon" / "src"
        hooks_daemon_src.mkdir(parents=True)

        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.write_text("daemon:\n  self_install_mode: true\n")

        # Should not raise
        validate_not_nested(tmp_path)

    def test_allows_clean_directory(self, tmp_path: Path) -> None:
        """Test allows clean directory without issues."""
        (tmp_path / ".claude").mkdir()

        # Should not raise
        validate_not_nested(tmp_path)


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

        with patch("claude_code_hooks_daemon.daemon.validation.is_hooks_daemon_repo") as mock_check:
            mock_check.return_value = True

            with pytest.raises(InstallationError) as exc_info:
                validate_installation_target(tmp_path, self_install_requested=False)

            assert "hooks-daemon repository" in str(exc_info.value)

    def test_allows_hooks_daemon_repo_with_flag(self, tmp_path: Path) -> None:
        """Test allows hooks-daemon repo with self-install flag."""
        (tmp_path / ".git").mkdir()

        with patch("claude_code_hooks_daemon.daemon.validation.is_hooks_daemon_repo") as mock_check:
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

        with patch("claude_code_hooks_daemon.daemon.validation.is_hooks_daemon_repo") as mock_check:
            mock_check.return_value = True

            # Should not raise
            validate_installation_target(tmp_path, self_install_requested=False)

    def test_allows_non_hooks_daemon_repo(self, tmp_path: Path) -> None:
        """Test allows non-hooks-daemon git repos."""
        (tmp_path / ".git").mkdir()

        with patch("claude_code_hooks_daemon.daemon.validation.is_hooks_daemon_repo") as mock_check:
            mock_check.return_value = False

            # Should not raise
            validate_installation_target(tmp_path)

    def test_allows_non_git_directory(self, tmp_path: Path) -> None:
        """Test allows non-git directories."""
        # No .git directory

        # Should not raise
        validate_installation_target(tmp_path)


class TestIsInsideDaemonDirectory:
    """Tests for is_inside_daemon_directory function.

    Detects when a candidate project root is inside another project's
    .claude/hooks-daemon/ directory tree. This prevents the walk-up path
    detection from being confused by the daemon repo's own .claude/ directory
    (which exists because the repo dogfoods itself in self-install mode).
    """

    def test_returns_true_for_hooks_daemon_directory(self, tmp_path: Path) -> None:
        """Path ending in .claude/hooks-daemon IS inside a daemon directory."""
        daemon_dir = tmp_path / "project" / ".claude" / "hooks-daemon"
        daemon_dir.mkdir(parents=True)
        assert is_inside_daemon_directory(daemon_dir) is True

    def test_returns_true_for_subdirectory_of_hooks_daemon(self, tmp_path: Path) -> None:
        """Path inside .claude/hooks-daemon/src/ IS inside a daemon directory."""
        src_dir = tmp_path / "project" / ".claude" / "hooks-daemon" / "src"
        src_dir.mkdir(parents=True)
        assert is_inside_daemon_directory(src_dir) is True

    def test_returns_true_for_deeply_nested_path(self, tmp_path: Path) -> None:
        """Deep path under .claude/hooks-daemon/ IS inside a daemon directory."""
        deep = tmp_path / "project" / ".claude" / "hooks-daemon" / "src" / "daemon" / "cli"
        deep.mkdir(parents=True)
        assert is_inside_daemon_directory(deep) is True

    def test_returns_false_for_project_root(self, tmp_path: Path) -> None:
        """Normal project root is NOT inside a daemon directory."""
        project = tmp_path / "project"
        project.mkdir()
        assert is_inside_daemon_directory(project) is False

    def test_returns_false_for_project_with_claude_dir(self, tmp_path: Path) -> None:
        """Project with .claude/ is NOT inside a daemon directory."""
        project = tmp_path / "project"
        (project / ".claude").mkdir(parents=True)
        assert is_inside_daemon_directory(project) is False

    def test_returns_false_for_claude_dir_itself(self, tmp_path: Path) -> None:
        """The .claude/ directory itself is NOT inside a daemon directory."""
        claude_dir = tmp_path / "project" / ".claude"
        claude_dir.mkdir(parents=True)
        assert is_inside_daemon_directory(claude_dir) is False

    def test_returns_false_for_self_install_project_root(self, tmp_path: Path) -> None:
        """Self-install project root (/workspace) is NOT inside a daemon directory."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        assert is_inside_daemon_directory(workspace) is False

    def test_returns_true_for_real_world_nested_scenario(self, tmp_path: Path) -> None:
        """Real-world scenario: CWD is .claude/hooks-daemon with its own .claude/.

        This is the exact scenario from prod feedback: daemon repo checked out
        at .claude/hooks-daemon/ has its own .claude/ from git (self-install
        dogfooding files). Walk-up finds .claude/hooks-daemon/.claude/ and
        tries to use .claude/hooks-daemon/ as project root.
        """
        # Simulate: /workspace/.claude/hooks-daemon/ (the daemon installation)
        project = tmp_path / "workspace"
        daemon_dir = project / ".claude" / "hooks-daemon"
        daemon_dir.mkdir(parents=True)
        # Daemon repo has its own .claude/ from git checkout (dogfooding)
        (daemon_dir / ".claude").mkdir()
        (daemon_dir / ".claude" / "hooks-daemon.yaml").write_text(
            "daemon:\n  self_install_mode: true\n"
        )

        # The candidate is .claude/hooks-daemon/ - this IS inside a daemon dir
        assert is_inside_daemon_directory(daemon_dir) is True


class TestCheckForNestedInstallation:
    """Tests for check_for_nested_installation function."""

    def test_cleans_up_nested_installation_and_returns_none(self, tmp_path: Path) -> None:
        """Nested install artifacts are actively removed, startup continues."""
        nested_install = tmp_path / ".claude" / "hooks-daemon" / ".claude" / "hooks-daemon"
        nested_untracked = nested_install / "untracked"
        nested_untracked.mkdir(parents=True)
        # Simulate runtime artifacts
        (nested_untracked / "daemon-abc123.sock").touch()
        (nested_untracked / "daemon-abc123.pid").write_text("12345")

        result = check_for_nested_installation(tmp_path)
        # Should return None (cleaned up, not blocking)
        assert result is None
        # Nested install directory should be gone
        assert not nested_install.exists()
        # Parent .claude dir inside hooks-daemon should still exist (git-tracked)
        assert (tmp_path / ".claude" / "hooks-daemon" / ".claude").exists()

    def test_returns_none_for_hooks_daemon_with_own_claude_dir(self, tmp_path: Path) -> None:
        """Test returns None when hooks-daemon has its own .claude dir (not nested install)."""
        nested_claude = tmp_path / ".claude" / "hooks-daemon" / ".claude"
        nested_claude.mkdir(parents=True)

        result = check_for_nested_installation(tmp_path)
        assert result is None

    def test_returns_none_for_clean_installation(self, tmp_path: Path) -> None:
        """Test returns None for clean installation."""
        (tmp_path / ".claude").mkdir()

        result = check_for_nested_installation(tmp_path)
        assert result is None

    def test_returns_none_for_normal_hooks_daemon_dir(self, tmp_path: Path) -> None:
        """Test returns None when hooks-daemon exists without nested .claude."""
        hooks_daemon = tmp_path / ".claude" / "hooks-daemon"
        hooks_daemon.mkdir(parents=True)
        # Add some normal content, not a .claude directory
        (hooks_daemon / "src").mkdir()

        result = check_for_nested_installation(tmp_path)
        assert result is None

    def test_returns_none_when_outer_hooks_daemon_is_the_repo(self, tmp_path: Path) -> None:
        """Test returns None when .claude/hooks-daemon IS the hooks-daemon repo.

        When the hooks-daemon repo is installed at .claude/hooks-daemon/ and it
        has its own .claude/hooks-daemon/ subdirectory (for self-dogfooding),
        this should NOT be flagged as a nested installation.

        The repo is identified by having a pyproject.toml file.
        """
        hooks_daemon_repo = tmp_path / ".claude" / "hooks-daemon"
        hooks_daemon_repo.mkdir(parents=True)
        # The outer .claude/hooks-daemon IS the hooks-daemon repo (has pyproject.toml)
        (hooks_daemon_repo / "pyproject.toml").write_text(
            "[project]\nname = 'claude-code-hooks-daemon'\n"
        )
        (hooks_daemon_repo / "src").mkdir()
        # The repo has its own .claude/hooks-daemon subdirectory (dogfooding)
        inner_hooks_daemon = hooks_daemon_repo / ".claude" / "hooks-daemon"
        inner_hooks_daemon.mkdir(parents=True)

        result = check_for_nested_installation(tmp_path)
        assert result is None

    def test_cleans_up_genuine_nested_installation(self, tmp_path: Path) -> None:
        """Genuine nested install (outer is NOT the repo) is actively removed.

        When .claude/hooks-daemon/ does NOT have pyproject.toml (i.e., it's just
        a normal installation directory), the inner .claude/hooks-daemon IS a
        genuinely nested installation and should be cleaned up.
        """
        hooks_daemon_dir = tmp_path / ".claude" / "hooks-daemon"
        hooks_daemon_dir.mkdir(parents=True)
        # No pyproject.toml - this is NOT the repo, just an install directory
        nested_install = hooks_daemon_dir / ".claude" / "hooks-daemon"
        nested_install.mkdir(parents=True)

        result = check_for_nested_installation(tmp_path)
        # Cleaned up, not blocking
        assert result is None
        assert not nested_install.exists()
