"""Tests for ClientInstallValidator."""

import json

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


def _build_valid_settings() -> dict:
    """Build a settings.json dict with all hooks properly registered."""
    from claude_code_hooks_daemon.utils.hook_registration import HOOK_EVENTS_IN_SETTINGS

    hooks: dict = {}
    for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items():
        hooks[json_key] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f'"$CLAUDE_PROJECT_DIR"/.claude/hooks/{bash_key}',
                        "timeout": 60,
                    }
                ]
            }
        ]
    return {"hooks": hooks}


class TestVerifyHookRegistrations:
    """Test _verify_hook_registrations validation."""

    def test_no_settings_file_passes(self, tmp_path):
        """No settings.json yet — nothing to validate."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = ClientInstallValidator._verify_hook_registrations(project_root)
        assert result.passed is True
        assert result.warnings == []

    def test_all_hooks_present_no_duplicates(self, tmp_path):
        """All hooks registered, no duplicates — clean result."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps(_build_valid_settings()))

        result = ClientInstallValidator._verify_hook_registrations(project_root)
        assert result.passed is True
        assert result.warnings == []

    def test_missing_hooks_reported_as_warnings(self, tmp_path):
        """Missing hooks should appear as warnings."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        settings = _build_valid_settings()
        del settings["hooks"]["Stop"]
        del settings["hooks"]["PreToolUse"]

        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps(settings))

        result = ClientInstallValidator._verify_hook_registrations(project_root)
        assert result.passed is True  # warnings, not errors
        warnings_text = "\n".join(result.warnings)
        assert "Stop" in warnings_text
        assert "PreToolUse" in warnings_text

    def test_duplicate_hooks_reported_as_warnings(self, tmp_path):
        """Hooks in both settings files should be warned about."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps(_build_valid_settings()))

        local_settings = {
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": ".claude/hooks/stop"}]}],
            }
        }
        local_path = claude_dir / "settings.local.json"
        local_path.write_text(json.dumps(local_settings))

        result = ClientInstallValidator._verify_hook_registrations(project_root)
        assert result.passed is True  # warnings, not errors
        warnings_text = "\n".join(result.warnings)
        assert "Duplicate" in warnings_text or "duplicate" in warnings_text
        assert "Stop" in warnings_text

    def test_wrong_command_reported_as_warning(self, tmp_path):
        """Wrong hook command paths should appear as warnings."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        settings = _build_valid_settings()
        settings["hooks"]["Stop"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/wrong-script',
                    }
                ]
            }
        ]

        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps(settings))

        result = ClientInstallValidator._verify_hook_registrations(project_root)
        assert result.passed is True  # warnings, not errors
        warnings_text = "\n".join(result.warnings)
        assert "Stop" in warnings_text
        assert "wrong-script" in warnings_text

    def test_invalid_json_adds_warning(self, tmp_path):
        """Malformed settings.json should produce a warning, not crash."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        settings_path = claude_dir / "settings.json"
        settings_path.write_text("{invalid json")

        result = ClientInstallValidator._verify_hook_registrations(project_root)
        assert result.passed is True
        assert len(result.warnings) == 1
        assert "Failed to read" in result.warnings[0]

    def test_no_local_settings_no_duplicate_warnings(self, tmp_path):
        """Missing settings.local.json should not produce duplicate warnings."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps(_build_valid_settings()))
        # No settings.local.json

        result = ClientInstallValidator._verify_hook_registrations(project_root)
        assert result.passed is True
        warnings_text = "\n".join(result.warnings)
        assert "duplicate" not in warnings_text.lower()

    def test_local_hooks_without_duplicate_still_warned(self, tmp_path):
        """Any hooks entry in settings.local.json must be flagged."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        settings = _build_valid_settings()
        # Remove Notification from main so the local entry is NOT a duplicate
        settings["hooks"].pop("Notification", None)

        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps(settings))

        local_settings = {
            "hooks": {
                "Notification": [
                    {"hooks": [{"type": "command", "command": ".claude/hooks/notification"}]}
                ]
            }
        }
        local_path = claude_dir / "settings.local.json"
        local_path.write_text(json.dumps(local_settings))

        result = ClientInstallValidator._verify_hook_registrations(project_root)
        assert result.passed is True
        warnings_text = "\n".join(result.warnings)
        assert "settings.local.json" in warnings_text
        assert "Notification" in warnings_text

    def test_legacy_hook_command_warned(self, tmp_path):
        """Inline/custom hook commands that bypass the daemon must be flagged."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        settings = _build_valid_settings()
        settings["hooks"]["Stop"] = [
            {"hooks": [{"type": "command", "command": "python /opt/hooks/my_stop.py"}]}
        ]
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps(settings))

        result = ClientInstallValidator._verify_hook_registrations(project_root)
        assert result.passed is True
        warnings_text = "\n".join(result.warnings)
        assert "legacy" in warnings_text.lower()
        assert "Stop" in warnings_text


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
        from unittest.mock import patch

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

        # Mock daemon start check since we don't have a real venv in test
        with patch.object(
            ClientInstallValidator,
            "validate_daemon_can_start",
            return_value=ValidationResult(passed=True, errors=[], warnings=[]),
        ):
            result = ClientInstallValidator.validate_post_install(project_root)
            assert result.passed is True

    def test_post_install_calls_daemon_start_check(self, tmp_path):
        """Test that validate_post_install checks daemon can start.

        Bug regression: validate_post_install did not call
        validate_daemon_can_start(), so a broken venv (e.g. missing
        mdformat dependency) was never caught during post-install
        verification.
        """
        from unittest.mock import patch

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

        # Mock daemon start check to return failure
        daemon_error = ValidationResult(
            passed=False,
            errors=["Failed to import claude_code_hooks_daemon: No module named 'mdformat'"],
            warnings=[],
        )
        with patch.object(
            ClientInstallValidator,
            "validate_daemon_can_start",
            return_value=daemon_error,
        ) as mock_check:
            result = ClientInstallValidator.validate_post_install(project_root)
            # validate_daemon_can_start must be called
            mock_check.assert_called_once_with(project_root)
            # Post-install must FAIL when daemon can't start
            assert result.passed is False
            assert any("mdformat" in err for err in result.errors)

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
