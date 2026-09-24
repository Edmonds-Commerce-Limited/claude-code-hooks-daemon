"""Tests for ProjectContext singleton."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core.project_context import (
    ProjectContext,
    _ensure_self_install_lsp_venv_symlink,
)


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

        # Mock git commands for normal mode (run_git runs in text mode, so
        # stdout is str, not bytes).
        with patch("subprocess.run") as mock_run:
            # git rev-parse --show-toplevel
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="/tmp/project\n"),
                # git remote get-url origin
                MagicMock(returncode=0, stdout="git@github.com:user/test-repo.git\n"),
                # git rev-parse --show-toplevel (again for git_toplevel)
                MagicMock(returncode=0, stdout="/tmp/project\n"),
            ]

            ProjectContext.initialize(config_path)

        # Verify state
        assert ProjectContext.project_root() == project_root
        assert ProjectContext.config_path() == config_path
        assert ProjectContext.config_dir() == claude_dir
        assert ProjectContext.self_install_mode() is False
        assert ProjectContext.git_repo_name() == "test-repo"
        assert ProjectContext.git_toplevel() == Path("/tmp/project")
        # Verify daemon_untracked_dir in normal mode: {project}/.claude/hooks-daemon/untracked
        expected_untracked = claude_dir / "hooks-daemon" / "untracked"
        assert ProjectContext.daemon_untracked_dir() == expected_untracked

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
                MagicMock(returncode=0, stdout="/tmp/daemon-project\n"),
                MagicMock(returncode=0, stdout="https://github.com/org/daemon.git\n"),
                MagicMock(returncode=0, stdout="/tmp/daemon-project\n"),
            ]

            ProjectContext.initialize(config_path)

        # Verify self-install mode detected
        assert ProjectContext.self_install_mode() is True
        assert ProjectContext.project_root() == project_root
        assert ProjectContext.git_repo_name() == "daemon"
        # Verify daemon_untracked_dir in self-install mode: {project}/untracked
        expected_untracked = project_root / "untracked"
        assert ProjectContext.daemon_untracked_dir() == expected_untracked

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
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="not a git repo")

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
                MagicMock(returncode=0, stdout="/tmp/project\n"),  # git rev-parse (in repo)
                MagicMock(returncode=128, stdout="", stderr="no remote"),  # git remote (no origin)
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
                MagicMock(returncode=0, stdout="/tmp/project\n"),
                MagicMock(returncode=0, stdout="git@github.com:user/repo.git\n"),
                MagicMock(returncode=0, stdout="/tmp/project\n"),
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
                MagicMock(returncode=0, stdout="/tmp/project\n"),
                MagicMock(returncode=0, stdout="https://github.com/org/my-repo.git\n"),
                MagicMock(returncode=0, stdout="/tmp/project\n"),
            ]
            ProjectContext.initialize(config_path)

        # All accessors should work
        assert ProjectContext.project_root() == project_root
        assert ProjectContext.config_path() == config_path
        assert ProjectContext.config_dir() == claude_dir
        assert isinstance(ProjectContext.self_install_mode(), bool)
        assert ProjectContext.git_repo_name() == "my-repo"
        assert ProjectContext.git_toplevel() == Path("/tmp/project")

    def test_is_initialized_false_before_init(self) -> None:
        assert ProjectContext.is_initialized() is False

    def test_is_initialized_true_after_init(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="/tmp/project\n"),
                MagicMock(returncode=0, stdout="https://github.com/org/my-repo.git\n"),
                MagicMock(returncode=0, stdout="/tmp/project\n"),
            ]
            ProjectContext.initialize(config_path)

        assert ProjectContext.is_initialized() is True


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
                MagicMock(returncode=0, stdout="/tmp/project\n"),
                MagicMock(returncode=0, stdout="git@github.com:user/ssh-repo.git\n"),
                MagicMock(returncode=0, stdout="/tmp/project\n"),
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
                MagicMock(returncode=0, stdout="/tmp/project\n"),
                MagicMock(returncode=0, stdout="https://github.com/org/https-repo.git\n"),
                MagicMock(returncode=0, stdout="/tmp/project\n"),
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
                MagicMock(returncode=0, stdout="/tmp/project\n"),
                MagicMock(returncode=0, stdout="https://github.com/org/no-extension\n"),
                MagicMock(returncode=0, stdout="/tmp/project\n"),
            ]
            ProjectContext.initialize(config_path)

        assert ProjectContext.git_repo_name() == "no-extension"

    def test_get_git_repo_name_handles_empty_url(self, tmp_path: Path) -> None:
        """_get_git_repo_name returns None for empty remote URL."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="/tmp/project\n"),  # git rev-parse
                MagicMock(returncode=0, stdout="\n"),  # git remote (empty URL)
            ]

            result = ProjectContext._get_git_repo_name(tmp_path)

        assert result is None

    def test_get_git_repo_name_handles_timeout(self, tmp_path: Path) -> None:
        """_get_git_repo_name returns None on timeout.

        The timeout is caught inside run_git (Plan 00246), which reports it as
        a non-zero returncode rather than raising — so this still exercises
        the same outward behaviour: a git failure never propagates.
        """
        import subprocess

        from claude_code_hooks_daemon.constants import Timeout

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=Timeout.GIT_CONTEXT)

            result = ProjectContext._get_git_repo_name(tmp_path)

        assert result is None

    def test_get_git_repo_name_handles_unparseable_url(self, tmp_path: Path) -> None:
        """_get_git_repo_name returns None for unparseable URL."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="/tmp/project\n"),  # git rev-parse
                MagicMock(returncode=0, stdout="/.git\n"),  # Malformed URL
            ]

            result = ProjectContext._get_git_repo_name(tmp_path)

        assert result is None

    def test_get_git_toplevel_handles_timeout(self, tmp_path: Path) -> None:
        """_get_git_toplevel returns None on timeout (caught inside run_git)."""
        import subprocess

        from claude_code_hooks_daemon.constants import Timeout

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=Timeout.GIT_CONTEXT)

            result = ProjectContext._get_git_toplevel(tmp_path)

        assert result is None

    def test_get_git_toplevel_handles_unexpected_error(self, tmp_path: Path) -> None:
        """_get_git_toplevel returns None on unexpected errors (caught inside run_git)."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Unexpected filesystem error")

            result = ProjectContext._get_git_toplevel(tmp_path)

        assert result is None


class TestSelfInstallCliSymlink:
    """The self-install checkout exposes bin/hooks-daemon at the conventional
    client path (Plan 00455): ``.claude/hooks-daemon/bin/hooks-daemon`` ->
    a relative symlink to the project root's own ``bin/hooks-daemon``.
    """

    def teardown_method(self) -> None:
        ProjectContext.reset()

    def _init_self_install(self, tmp_path: Path) -> Path:
        project_root = tmp_path / "daemon-project"
        claude_dir = project_root / ".claude"
        daemon_src = project_root / "src" / "claude_code_hooks_daemon"
        daemon_src.mkdir(parents=True)
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=f"{project_root}\n"),
                MagicMock(returncode=0, stdout="https://github.com/org/daemon.git\n"),
                MagicMock(returncode=0, stdout=f"{project_root}\n"),
            ]
            ProjectContext.initialize(config_path)

        return project_root

    def _init_normal(self, tmp_path: Path) -> Path:
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=f"{project_root}\n"),
                MagicMock(returncode=0, stdout="git@github.com:user/test-repo.git\n"),
                MagicMock(returncode=0, stdout=f"{project_root}\n"),
            ]
            ProjectContext.initialize(config_path)

        return project_root

    def test_creates_the_conventional_symlink_in_self_install_mode(self, tmp_path: Path) -> None:
        project_root = self._init_self_install(tmp_path)
        link = project_root / ".claude" / "hooks-daemon" / "bin" / "hooks-daemon"
        assert link.is_symlink()
        assert link.resolve() == (project_root / "bin" / "hooks-daemon").resolve()

    def test_symlink_target_is_relative_not_absolute(self, tmp_path: Path) -> None:
        """A relative target survives the checkout being moved or cloned again."""
        project_root = self._init_self_install(tmp_path)
        link = project_root / ".claude" / "hooks-daemon" / "bin" / "hooks-daemon"
        assert not link.readlink().is_absolute()

    def test_normal_mode_never_creates_the_symlink(self, tmp_path: Path) -> None:
        """Normal mode has no bin/hooks-daemon at the project root to link to."""
        project_root = self._init_normal(tmp_path)
        link = project_root / ".claude" / "hooks-daemon" / "bin" / "hooks-daemon"
        assert not link.exists()
        assert not link.is_symlink()

    def test_is_idempotent_when_the_symlink_already_exists(self, tmp_path: Path) -> None:
        """A second daemon start (e.g. restart) must not error or recreate it."""
        project_root = tmp_path / "daemon-project"
        claude_dir = project_root / ".claude"
        daemon_src = project_root / "src" / "claude_code_hooks_daemon"
        daemon_src.mkdir(parents=True)
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        link = claude_dir / "hooks-daemon" / "bin" / "hooks-daemon"
        link.parent.mkdir(parents=True)
        link.symlink_to(Path("../../../bin/hooks-daemon"))

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=f"{project_root}\n"),
                MagicMock(returncode=0, stdout="https://github.com/org/daemon.git\n"),
                MagicMock(returncode=0, stdout=f"{project_root}\n"),
            ]
            ProjectContext.initialize(config_path)

        assert link.is_symlink()
        assert link.resolve() == (project_root / "bin" / "hooks-daemon").resolve()

    def test_never_replaces_a_real_file_at_the_link_path(self, tmp_path: Path) -> None:
        """A genuine client-style wrapper file must never be clobbered."""
        project_root = tmp_path / "daemon-project"
        claude_dir = project_root / ".claude"
        daemon_src = project_root / "src" / "claude_code_hooks_daemon"
        daemon_src.mkdir(parents=True)
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        real_wrapper = claude_dir / "hooks-daemon" / "bin" / "hooks-daemon"
        real_wrapper.parent.mkdir(parents=True)
        real_wrapper.write_text("#!/bin/sh\necho not-a-symlink\n", encoding="utf-8")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=f"{project_root}\n"),
                MagicMock(returncode=0, stdout="https://github.com/org/daemon.git\n"),
                MagicMock(returncode=0, stdout=f"{project_root}\n"),
            ]
            ProjectContext.initialize(config_path)

        assert not real_wrapper.is_symlink()
        assert real_wrapper.read_text(encoding="utf-8") == "#!/bin/sh\necho not-a-symlink\n"


class TestSelfInstallLspVenvSymlink:
    """``untracked/lsp-venv`` gives pyrightconfig.json a stable path to the
    venv the self-install daemon is currently running from (Ledger 00422
    N18), derived from ``sys.prefix`` -- unlike the CLI symlink, this one is
    repointed when it goes stale (the fingerprint-keyed target changes on
    every upgrade).
    """

    def _make_venv(self, untracked_dir: Path, name: str) -> Path:
        venv_dir = untracked_dir / name
        (venv_dir / "bin").mkdir(parents=True)
        return venv_dir

    def test_creates_the_link_when_sys_prefix_is_under_untracked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_root = tmp_path / "daemon-project"
        untracked_dir = project_root / "untracked"
        venv_dir = self._make_venv(untracked_dir, "venv-abc123")
        monkeypatch.setattr(sys, "prefix", str(venv_dir))

        _ensure_self_install_lsp_venv_symlink(project_root)

        link = untracked_dir / "lsp-venv"
        assert link.is_symlink()
        assert link.resolve() == venv_dir.resolve()
        assert not link.readlink().is_absolute()

    def test_is_idempotent_when_already_correct(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_root = tmp_path / "daemon-project"
        untracked_dir = project_root / "untracked"
        venv_dir = self._make_venv(untracked_dir, "venv-abc123")
        monkeypatch.setattr(sys, "prefix", str(venv_dir))

        _ensure_self_install_lsp_venv_symlink(project_root)
        link = untracked_dir / "lsp-venv"
        first_target = link.readlink()

        _ensure_self_install_lsp_venv_symlink(project_root)

        assert link.is_symlink()
        assert link.readlink() == first_target

    def test_repoints_when_the_target_is_stale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An upgrade changes the fingerprint-keyed venv name; the link must
        follow it rather than keep pointing at the deleted old venv."""
        project_root = tmp_path / "daemon-project"
        untracked_dir = project_root / "untracked"
        old_venv = self._make_venv(untracked_dir, "venv-old111")
        new_venv = self._make_venv(untracked_dir, "venv-new222")

        monkeypatch.setattr(sys, "prefix", str(old_venv))
        _ensure_self_install_lsp_venv_symlink(project_root)
        link = untracked_dir / "lsp-venv"
        assert link.resolve() == old_venv.resolve()

        monkeypatch.setattr(sys, "prefix", str(new_venv))
        _ensure_self_install_lsp_venv_symlink(project_root)

        assert link.is_symlink()
        assert link.resolve() == new_venv.resolve()

    def test_leaves_a_non_symlink_at_the_link_path_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_root = tmp_path / "daemon-project"
        untracked_dir = project_root / "untracked"
        venv_dir = self._make_venv(untracked_dir, "venv-abc123")
        monkeypatch.setattr(sys, "prefix", str(venv_dir))

        link = untracked_dir / "lsp-venv"
        link.mkdir(parents=True)
        (link / "marker.txt").write_text("real directory, not a symlink")

        _ensure_self_install_lsp_venv_symlink(project_root)

        assert not link.is_symlink()
        assert (link / "marker.txt").read_text() == "real directory, not a symlink"

    def test_sys_prefix_outside_untracked_does_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_root = tmp_path / "daemon-project"
        (project_root / "untracked").mkdir(parents=True)
        elsewhere_venv = tmp_path / "some-other-venv"
        elsewhere_venv.mkdir()
        monkeypatch.setattr(sys, "prefix", str(elsewhere_venv))

        _ensure_self_install_lsp_venv_symlink(project_root)

        link = project_root / "untracked" / "lsp-venv"
        assert not link.exists()
        assert not link.is_symlink()

    def test_client_mode_never_creates_the_lsp_venv_symlink(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the self-install branch of ProjectContext.initialize calls
        this; a normal client install must never grow the link."""
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        venv_dir = project_root / "untracked" / "venv-abc123"
        (venv_dir / "bin").mkdir(parents=True)
        monkeypatch.setattr(sys, "prefix", str(venv_dir))

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=f"{project_root}\n"),
                MagicMock(returncode=0, stdout="git@github.com:user/test-repo.git\n"),
                MagicMock(returncode=0, stdout=f"{project_root}\n"),
            ]
            ProjectContext.initialize(config_path)

        ProjectContext.reset()
        link = project_root / "untracked" / "lsp-venv"
        assert not link.exists()
        assert not link.is_symlink()

    def test_self_install_mode_creates_the_link_via_initialize(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The end-to-end path: ProjectContext.initialize() in self-install
        mode wires up the lsp-venv link, not just the standalone function."""
        project_root = tmp_path / "daemon-project"
        claude_dir = project_root / ".claude"
        daemon_src = project_root / "src" / "claude_code_hooks_daemon"
        daemon_src.mkdir(parents=True)
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        venv_dir = project_root / "untracked" / "venv-abc123"
        (venv_dir / "bin").mkdir(parents=True)
        monkeypatch.setattr(sys, "prefix", str(venv_dir))

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=f"{project_root}\n"),
                MagicMock(returncode=0, stdout="https://github.com/org/daemon.git\n"),
                MagicMock(returncode=0, stdout=f"{project_root}\n"),
            ]
            ProjectContext.initialize(config_path)

        link = project_root / "untracked" / "lsp-venv"
        assert link.is_symlink()
        assert link.resolve() == venv_dir.resolve()


class TestProjectContextContainerRuntime:
    """The container runtime is detected ONCE at startup and cached (Plan 00126)."""

    def teardown_method(self) -> None:
        ProjectContext.reset()

    def _init(self, tmp_path: Path, env: dict[str, str]) -> None:
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")
        with patch.dict("os.environ", env, clear=True):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0, stdout="/tmp/project\n"),
                    MagicMock(returncode=0, stdout="git@github.com:user/test-repo.git\n"),
                    MagicMock(returncode=0, stdout="/tmp/project\n"),
                ]
                ProjectContext.initialize(config_path)

    def test_container_runtime_cached_from_env(self, tmp_path: Path) -> None:
        """A `container=podman` env at startup is cached as the runtime."""
        self._init(tmp_path, {"container": "podman"})
        assert ProjectContext.container_runtime() == "podman"
        assert ProjectContext.in_container() is True

    def test_host_has_no_runtime(self, tmp_path: Path) -> None:
        """With every container marker neutralised, runtime is None (host)."""
        self._init(
            tmp_path,
            {
                "HOOKS_DAEMON_DOCKERENV_PATH": "/tmp/_absent_docker_pc",
                "HOOKS_DAEMON_CONTAINERENV_PATH": "/tmp/_absent_containerenv_pc",
                "HOOKS_DAEMON_CGROUP_PATH": "/tmp/_absent_cgroup_pc",
            },
        )
        assert ProjectContext.container_runtime() is None
        assert ProjectContext.in_container() is False
