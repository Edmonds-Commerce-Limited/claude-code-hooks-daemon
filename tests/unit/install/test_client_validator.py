"""Tests for ClientInstallValidator."""

import yaml

from claude_code_hooks_daemon.install.client_validator import (
    ClientInstallValidator,
    ValidationResult,
)


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_validation_result_passed(self):
        """Test ValidationResult with no errors."""
        result = ValidationResult(passed=True, errors=[], warnings=[])
        assert result.passed is True
        assert result.errors == []
        assert result.warnings == []

    def test_validation_result_failed(self):
        """Test ValidationResult with errors."""
        result = ValidationResult(
            passed=False, errors=["Error 1", "Error 2"], warnings=["Warning 1"]
        )
        assert result.passed is False
        assert len(result.errors) == 2
        assert len(result.warnings) == 1


class TestCheckNotDaemonRepo:
    """Test _check_not_daemon_repo validation."""

    def test_not_daemon_repo_passes(self, tmp_path):
        """Test validation passes when not in daemon repo."""
        # Create a normal project structure (no daemon source)
        project_root = tmp_path / "client-project"
        project_root.mkdir()

        result = ClientInstallValidator._check_not_daemon_repo(project_root)
        assert result.passed is True
        assert len(result.errors) == 0

    def test_daemon_repo_detected(self, tmp_path):
        """Test validation fails when daemon source detected at root."""
        # Create daemon repository structure
        project_root = tmp_path / "daemon-repo"
        project_root.mkdir()
        daemon_src = project_root / "src" / "claude_code_hooks_daemon"
        daemon_src.mkdir(parents=True)

        result = ClientInstallValidator._check_not_daemon_repo(project_root)
        assert result.passed is False
        assert len(result.errors) == 1
        assert "--self-install" in result.errors[0]


class TestCheckExistingConfig:
    """Test _check_existing_config validation."""

    def test_no_existing_config_passes(self, tmp_path):
        """Test validation passes when no config exists."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = ClientInstallValidator._check_existing_config(project_root)
        assert result.passed is True
        assert len(result.errors) == 0

    def test_config_without_self_install_mode_passes(self, tmp_path):
        """Test validation passes when config has no self_install_mode."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {},
        }

        config_path = claude_dir / "hooks-daemon.yaml"
        with config_path.open("w") as f:
            yaml.dump(config, f)

        result = ClientInstallValidator._check_existing_config(project_root)
        assert result.passed is True
        assert len(result.errors) == 0

    def test_config_with_self_install_mode_false_passes(self, tmp_path):
        """Test validation passes when self_install_mode is explicitly false."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
                "self_install_mode": False,
            },
            "handlers": {},
        }

        config_path = claude_dir / "hooks-daemon.yaml"
        with config_path.open("w") as f:
            yaml.dump(config, f)

        result = ClientInstallValidator._check_existing_config(project_root)
        assert result.passed is True
        assert len(result.errors) == 0

    def test_config_with_self_install_mode_true_fails(self, tmp_path):
        """Test validation fails when config has self_install_mode: true."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
                "self_install_mode": True,
            },
            "handlers": {},
        }

        config_path = claude_dir / "hooks-daemon.yaml"
        with config_path.open("w") as f:
            yaml.dump(config, f)

        result = ClientInstallValidator._check_existing_config(project_root)
        assert result.passed is False
        assert len(result.errors) == 1
        assert "self_install_mode: true" in result.errors[0]
        assert "CLIENT PROJECT" in result.errors[0]

    def test_invalid_config_adds_warning(self, tmp_path):
        """Test validation adds warning for invalid config."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("not: valid: yaml: content:")

        result = ClientInstallValidator._check_existing_config(project_root)
        # Invalid config is a warning, not an error
        assert result.passed is True
        assert len(result.warnings) > 0


class TestCheckRunningDaemon:
    """Test _check_running_daemon validation."""

    def test_no_daemon_directory_passes(self, tmp_path):
        """Test validation passes when no daemon directory exists."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = ClientInstallValidator._check_running_daemon(project_root)
        assert result.passed is True

    def test_no_pid_files_passes(self, tmp_path):
        """Test validation passes when no PID files exist."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        untracked_dir = project_root / ".claude" / "hooks-daemon" / "untracked"
        untracked_dir.mkdir(parents=True)

        result = ClientInstallValidator._check_running_daemon(project_root)
        assert result.passed is True

    def test_stale_pid_file_cleaned(self, tmp_path):
        """Test stale PID file is cleaned up."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        untracked_dir = project_root / ".claude" / "hooks-daemon" / "untracked"
        untracked_dir.mkdir(parents=True)

        # Create PID file with non-existent PID
        pid_file = untracked_dir / "daemon.pid"
        pid_file.write_text("99999999")

        result = ClientInstallValidator._check_running_daemon(project_root)
        assert result.passed is True
        # PID file should be removed
        assert not pid_file.exists()


class TestCheckDirectoryStructure:
    """Test _check_directory_structure validation."""

    def test_no_claude_dir_passes(self, tmp_path):
        """Test validation passes when .claude doesn't exist yet."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = ClientInstallValidator._check_directory_structure(project_root)
        assert result.passed is True

    def test_claude_as_directory_passes(self, tmp_path):
        """Test validation passes when .claude is a directory."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        result = ClientInstallValidator._check_directory_structure(project_root)
        assert result.passed is True

    def test_claude_as_file_fails(self, tmp_path):
        """Test validation fails when .claude is a file."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_file = project_root / ".claude"
        claude_file.write_text("not a directory")

        result = ClientInstallValidator._check_directory_structure(project_root)
        assert result.passed is False
        assert len(result.errors) == 1
        assert "not a directory" in result.errors[0]


class TestVerifyConfigValid:
    """Test _verify_config_valid validation."""

    def test_missing_config_fails(self, tmp_path):
        """Test validation fails when config doesn't exist."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = ClientInstallValidator._verify_config_valid(project_root)
        assert result.passed is False
        assert len(result.errors) == 1

    def test_valid_config_passes(self, tmp_path):
        """Test validation passes with valid config."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {},
        }

        config_path = claude_dir / "hooks-daemon.yaml"
        with config_path.open("w") as f:
            yaml.dump(config, f)

        result = ClientInstallValidator._verify_config_valid(project_root)
        assert result.passed is True

    def test_config_missing_daemon_section_fails(self, tmp_path):
        """Test validation fails when daemon section missing."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        config = {"version": "1.0", "handlers": {}}

        config_path = claude_dir / "hooks-daemon.yaml"
        with config_path.open("w") as f:
            yaml.dump(config, f)

        result = ClientInstallValidator._verify_config_valid(project_root)
        assert result.passed is False
        assert any("daemon" in err for err in result.errors)


class TestVerifyDaemonDirectory:
    """Test _verify_daemon_directory validation."""

    def test_missing_daemon_directory_fails(self, tmp_path):
        """Test validation fails when daemon directory missing."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = ClientInstallValidator._verify_daemon_directory(project_root)
        assert result.passed is False
        assert len(result.errors) == 1

    def test_daemon_directory_exists_passes(self, tmp_path):
        """Test validation passes when daemon directory exists."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        daemon_dir = project_root / ".claude" / "hooks-daemon"
        daemon_dir.mkdir(parents=True)
        src_dir = daemon_dir / "src"
        src_dir.mkdir()

        result = ClientInstallValidator._verify_daemon_directory(project_root)
        assert result.passed is True


class TestVerifyNoSelfInstallMode:
    """Test _verify_no_self_install_mode validation."""

    def test_config_without_self_install_mode_passes(self, tmp_path):
        """Test validation passes when config has no self_install_mode."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {},
        }

        config_path = claude_dir / "hooks-daemon.yaml"
        with config_path.open("w") as f:
            yaml.dump(config, f)

        result = ClientInstallValidator._verify_no_self_install_mode(project_root)
        assert result.passed is True

    def test_config_with_self_install_mode_true_fails(self, tmp_path):
        """Test validation fails when config has self_install_mode: true."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
                "self_install_mode": True,
            },
            "handlers": {},
        }

        config_path = claude_dir / "hooks-daemon.yaml"
        with config_path.open("w") as f:
            yaml.dump(config, f)

        result = ClientInstallValidator._verify_no_self_install_mode(project_root)
        assert result.passed is False
        assert len(result.errors) == 1
        assert "self_install_mode: true" in result.errors[0]
        assert "CLIENT PROJECT" in result.errors[0]


class TestCleanupStaleRuntimeFiles:
    """Test cleanup_stale_runtime_files."""

    def test_no_daemon_directory_passes(self, tmp_path):
        """Test cleanup passes when no daemon directory exists."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = ClientInstallValidator.cleanup_stale_runtime_files(project_root)
        assert result.passed is True

    def test_removes_stale_socket_files(self, tmp_path):
        """Test cleanup removes stale socket files."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        untracked_dir = project_root / ".claude" / "hooks-daemon" / "untracked"
        untracked_dir.mkdir(parents=True)

        # Create stale socket file
        socket_file = untracked_dir / "daemon.sock"
        socket_file.write_text("")

        result = ClientInstallValidator.cleanup_stale_runtime_files(project_root)
        assert result.passed is True
        assert not socket_file.exists()
        assert len(result.warnings) > 0

    def test_removes_stale_pid_files(self, tmp_path):
        """Test cleanup removes stale PID files."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        untracked_dir = project_root / ".claude" / "hooks-daemon" / "untracked"
        untracked_dir.mkdir(parents=True)

        # Create PID file with non-existent PID
        pid_file = untracked_dir / "daemon.pid"
        pid_file.write_text("99999999")

        result = ClientInstallValidator.cleanup_stale_runtime_files(project_root)
        assert result.passed is True
        assert not pid_file.exists()


class TestValidatePreInstall:
    """Test validate_pre_install main entry point."""

    def test_clean_project_passes(self, tmp_path):
        """Test validation passes for clean project."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = ClientInstallValidator.validate_pre_install(project_root)
        assert result.passed is True

    def test_daemon_repo_fails(self, tmp_path):
        """Test validation fails for daemon repo without --self-install."""
        project_root = tmp_path / "daemon-repo"
        project_root.mkdir()
        daemon_src = project_root / "src" / "claude_code_hooks_daemon"
        daemon_src.mkdir(parents=True)

        result = ClientInstallValidator.validate_pre_install(project_root)
        assert result.passed is False
        assert len(result.errors) > 0


class TestValidatePostInstall:
    """Test validate_post_install main entry point."""

    def test_successful_install_passes(self, tmp_path):
        """Test validation passes for successful installation."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()
        daemon_dir = claude_dir / "hooks-daemon"
        daemon_dir.mkdir()
        src_dir = daemon_dir / "src"
        src_dir.mkdir()

        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {},
        }

        config_path = claude_dir / "hooks-daemon.yaml"
        with config_path.open("w") as f:
            yaml.dump(config, f)

        result = ClientInstallValidator.validate_post_install(project_root)
        assert result.passed is True

    def test_missing_config_fails(self, tmp_path):
        """Test validation fails when config missing after install."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = ClientInstallValidator.validate_post_install(project_root)
        assert result.passed is False

    def test_self_install_mode_in_config_fails(self, tmp_path):
        """Test validation fails when self_install_mode leaked into config."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()
        daemon_dir = claude_dir / "hooks-daemon"
        daemon_dir.mkdir()
        src_dir = daemon_dir / "src"
        src_dir.mkdir()

        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
                "self_install_mode": True,  # This should never be in client config!
            },
            "handlers": {},
        }

        config_path = claude_dir / "hooks-daemon.yaml"
        with config_path.open("w") as f:
            yaml.dump(config, f)

        result = ClientInstallValidator.validate_post_install(project_root)
        assert result.passed is False
        assert any("self_install_mode: true" in err for err in result.errors)
