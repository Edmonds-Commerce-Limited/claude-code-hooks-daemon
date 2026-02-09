"""Client project installation safety validator.

CRITICAL: When install.py or upgrade.sh runs WITHOUT --self-install flag,
we are 100% CERTAIN it's a CLIENT PROJECT installation, NOT self-install mode.

This module provides comprehensive safety checks to prevent configuration
confusion that could cause handler_status.py and other tools to malfunction.
"""

import logging
import os
import signal
import subprocess  # nosec B404 - subprocess used for daemon verification only (trusted venv python)
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.constants import Timeout

logger = logging.getLogger(__name__)


class ClientValidationError(Exception):
    """Raised when client installation validation fails."""

    pass


@dataclass
class ValidationResult:
    """Result of validation check.

    Attributes:
        passed: True if validation passed
        errors: List of error messages (empty if passed)
        warnings: List of warning messages (non-fatal)
    """

    passed: bool
    errors: list[str]
    warnings: list[str]


class ClientInstallValidator:
    """Safety validator for client project installations.

    Ensures that client projects (non-self-install) have correct configuration
    and paths, preventing confusion with self-install mode.
    """

    @staticmethod
    def validate_pre_install(project_root: Path) -> ValidationResult:
        """Run all pre-installation safety checks.

        CERTAINTY: This runs during install.py WITHOUT --self-install,
        so we KNOW this is a client project, not the daemon repo itself.

        Args:
            project_root: Project root directory where daemon will be installed

        Returns:
            ValidationResult with any errors or warnings
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Check 1: Verify we're not accidentally in the daemon repo
        result = ClientInstallValidator._check_not_daemon_repo(project_root)
        errors.extend(result.errors)
        warnings.extend(result.warnings)

        # Check 2: Validate existing config doesn't have self_install_mode
        result = ClientInstallValidator._check_existing_config(project_root)
        errors.extend(result.errors)
        warnings.extend(result.warnings)

        # Check 3: Check for running daemon and offer to stop it
        result = ClientInstallValidator._check_running_daemon(project_root)
        errors.extend(result.errors)
        warnings.extend(result.warnings)

        # Check 4: Validate expected directory structure
        result = ClientInstallValidator._check_directory_structure(project_root)
        errors.extend(result.errors)
        warnings.extend(result.warnings)

        return ValidationResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def validate_post_install(project_root: Path) -> ValidationResult:
        """Run all post-installation verification checks.

        Ensures the installation completed correctly and config is sane.

        Args:
            project_root: Project root directory

        Returns:
            ValidationResult with any errors or warnings
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Check 1: Config exists and is valid
        result = ClientInstallValidator._verify_config_valid(project_root)
        errors.extend(result.errors)
        warnings.extend(result.warnings)

        # Check 2: Daemon directory exists with expected structure
        result = ClientInstallValidator._verify_daemon_directory(project_root)
        errors.extend(result.errors)
        warnings.extend(result.warnings)

        # Check 3: Config does NOT have self_install_mode: true
        result = ClientInstallValidator._verify_no_self_install_mode(project_root)
        errors.extend(result.errors)
        warnings.extend(result.warnings)

        return ValidationResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _check_not_daemon_repo(project_root: Path) -> ValidationResult:
        """Verify we're not installing into the daemon repository itself.

        Args:
            project_root: Project root to check

        Returns:
            ValidationResult
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Check for daemon source at project root (sign of daemon repo)
        daemon_src = project_root / "src" / "claude_code_hooks_daemon"
        if daemon_src.exists():
            # This looks like the daemon repo - should use --self-install
            errors.append(
                f"Installation target appears to be the daemon repository itself.\n"
                f"Found daemon source at: {daemon_src}\n"
                f"To install on the daemon repo for development, use: python3 install.py --self-install"
            )

        return ValidationResult(passed=len(errors) == 0, errors=errors, warnings=warnings)

    @staticmethod
    def _check_existing_config(project_root: Path) -> ValidationResult:
        """Check existing config for self_install_mode flag.

        Args:
            project_root: Project root to check

        Returns:
            ValidationResult
        """
        errors: list[str] = []
        warnings: list[str] = []

        config_path = project_root / ".claude" / "hooks-daemon.yaml"
        if not config_path.exists():
            # No existing config - this is fine for fresh install
            return ValidationResult(passed=True, errors=[], warnings=[])

        try:
            import yaml

            with config_path.open() as f:
                config = yaml.safe_load(f)

            if not isinstance(config, dict):
                warnings.append(f"Existing config at {config_path} is not a valid YAML dictionary")
                return ValidationResult(passed=True, errors=[], warnings=warnings)

            daemon_config = config.get("daemon", {})
            if not isinstance(daemon_config, dict):
                return ValidationResult(passed=True, errors=[], warnings=warnings)

            if daemon_config.get("self_install_mode", False):
                errors.append(
                    f"CRITICAL: Existing config has self_install_mode: true\n"
                    f"Config: {config_path}\n"
                    f"This is a CLIENT PROJECT installation (no --self-install flag).\n"
                    f"The config must NOT have self_install_mode: true.\n"
                    f"\n"
                    f"Action required:\n"
                    f"1. Remove 'self_install_mode: true' from config, OR\n"
                    f"2. If this IS the daemon repo, run: python3 install.py --self-install"
                )

        except Exception as e:
            warnings.append(f"Failed to read existing config at {config_path}: {e}")

        return ValidationResult(passed=len(errors) == 0, errors=errors, warnings=warnings)

    @staticmethod
    def _check_running_daemon(project_root: Path) -> ValidationResult:
        """Check for running daemon and stop it if found.

        Args:
            project_root: Project root to check

        Returns:
            ValidationResult
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Look for PID file in expected location
        daemon_dir = project_root / ".claude" / "hooks-daemon"
        if not daemon_dir.exists():
            # No daemon directory yet - nothing to check
            return ValidationResult(passed=True, errors=[], warnings=[])

        untracked_dir = daemon_dir / "untracked"
        if not untracked_dir.exists():
            return ValidationResult(passed=True, errors=[], warnings=[])

        # Check for any PID files (may have hostname suffix)
        pid_files = list(untracked_dir.glob("daemon*.pid"))
        if not pid_files:
            return ValidationResult(passed=True, errors=[], warnings=[])

        # Found PID file(s) - check if process is running
        for pid_file in pid_files:
            try:
                with pid_file.open() as f:
                    pid = int(f.read().strip())

                # Check if process is alive
                try:
                    os.kill(pid, 0)  # Signal 0 just checks existence
                    # Process is running - try to stop it
                    warnings.append(
                        f"Found running daemon (PID {pid}). Attempting to stop it before installation..."
                    )

                    try:
                        # Try graceful shutdown first
                        os.kill(pid, signal.SIGTERM)
                        import time

                        time.sleep(1)

                        # Check if still running
                        try:
                            os.kill(pid, 0)
                            # Still running - force kill
                            os.kill(pid, signal.SIGKILL)
                            warnings.append(f"Forcefully stopped daemon (PID {pid})")
                        except ProcessLookupError:
                            warnings.append(f"Gracefully stopped daemon (PID {pid})")

                    except (ProcessLookupError, PermissionError):
                        pass  # Process already gone or no permission

                except ProcessLookupError:
                    # Process not running - clean up stale PID file
                    pid_file.unlink()

            except (ValueError, FileNotFoundError, PermissionError):
                pass  # Invalid PID file or can't read it

        return ValidationResult(passed=True, errors=[], warnings=warnings)

    @staticmethod
    def _check_directory_structure(project_root: Path) -> ValidationResult:
        """Check that directory structure is correct for client install.

        Args:
            project_root: Project root to check

        Returns:
            ValidationResult
        """
        errors: list[str] = []
        warnings: list[str] = []

        claude_dir = project_root / ".claude"
        if not claude_dir.exists():
            # Will be created during install - this is fine
            return ValidationResult(passed=True, errors=[], warnings=[])

        # If .claude exists, verify it's not blocking installation
        if claude_dir.is_file():
            errors.append(f"{claude_dir} exists as a file, not a directory. Cannot install.")

        return ValidationResult(passed=len(errors) == 0, errors=errors, warnings=warnings)

    @staticmethod
    def _verify_config_valid(project_root: Path) -> ValidationResult:
        """Verify config file exists and is valid YAML.

        Args:
            project_root: Project root to check

        Returns:
            ValidationResult
        """
        errors: list[str] = []
        warnings: list[str] = []

        config_path = project_root / ".claude" / "hooks-daemon.yaml"
        if not config_path.exists():
            errors.append(f"Config file not created: {config_path}")
            return ValidationResult(passed=False, errors=errors, warnings=warnings)

        try:
            import yaml

            with config_path.open() as f:
                config = yaml.safe_load(f)

            if not isinstance(config, dict):
                errors.append(f"Config file is not a valid YAML dictionary: {config_path}")
                return ValidationResult(passed=False, errors=errors, warnings=warnings)

            # Basic structure checks
            if "version" not in config:
                warnings.append("Config missing 'version' field")

            if "daemon" not in config:
                errors.append("Config missing required 'daemon' section")

            if "handlers" not in config:
                warnings.append("Config missing 'handlers' section")

        except Exception as e:
            errors.append(f"Failed to parse config file {config_path}: {e}")

        return ValidationResult(passed=len(errors) == 0, errors=errors, warnings=warnings)

    @staticmethod
    def _verify_daemon_directory(project_root: Path) -> ValidationResult:
        """Verify daemon directory structure is correct.

        Args:
            project_root: Project root to check

        Returns:
            ValidationResult
        """
        errors: list[str] = []
        warnings: list[str] = []

        daemon_dir = project_root / ".claude" / "hooks-daemon"
        if not daemon_dir.exists():
            errors.append(
                f"Daemon directory not found: {daemon_dir}\n"
                f"Installation may have failed. Expected structure:\n"
                f"  {project_root}/.claude/hooks-daemon/src/\n"
                f"  {project_root}/.claude/hooks-daemon/untracked/"
            )
            return ValidationResult(passed=False, errors=errors, warnings=warnings)

        # Check for source directory
        src_dir = daemon_dir / "src"
        if not src_dir.exists():
            warnings.append(
                f"Daemon source directory not found: {src_dir}\n"
                f"This may indicate an incomplete installation."
            )

        return ValidationResult(passed=len(errors) == 0, errors=errors, warnings=warnings)

    @staticmethod
    def _verify_no_self_install_mode(project_root: Path) -> ValidationResult:
        """CRITICAL: Verify config does NOT have self_install_mode: true.

        This is the key check that prevents the handler_status.py confusion.

        Args:
            project_root: Project root to check

        Returns:
            ValidationResult
        """
        errors: list[str] = []
        warnings: list[str] = []

        config_path = project_root / ".claude" / "hooks-daemon.yaml"
        if not config_path.exists():
            # Already caught by _verify_config_valid
            return ValidationResult(passed=True, errors=[], warnings=[])

        try:
            import yaml

            with config_path.open() as f:
                config = yaml.safe_load(f)

            if not isinstance(config, dict):
                # Already caught by _verify_config_valid
                return ValidationResult(passed=True, errors=[], warnings=[])

            daemon_config = config.get("daemon", {})
            if not isinstance(daemon_config, dict):
                return ValidationResult(passed=True, errors=[], warnings=warnings)

            if daemon_config.get("self_install_mode", False):
                errors.append(
                    f"CRITICAL: Config has self_install_mode: true after installation!\n"
                    f"Config: {config_path}\n"
                    f"\n"
                    f"This is a CLIENT PROJECT installation. The config must NOT have\n"
                    f"self_install_mode: true, as this will cause path confusion.\n"
                    f"\n"
                    f"Expected daemon paths for client installation:\n"
                    f"  Daemon root: {project_root}/.claude/hooks-daemon/\n"
                    f"  Source:      {project_root}/.claude/hooks-daemon/src/\n"
                    f"  Venv:        {project_root}/.claude/hooks-daemon/untracked/venv/\n"
                    f"  Runtime:     {project_root}/.claude/hooks-daemon/untracked/*.sock\n"
                    f"\n"
                    f"Installation appears to have added self_install_mode incorrectly.\n"
                    f"Please file a bug report."
                )

        except Exception as e:
            warnings.append(f"Failed to verify config at {config_path}: {e}")

        return ValidationResult(passed=len(errors) == 0, errors=errors, warnings=warnings)

    @staticmethod
    def validate_daemon_can_start(project_root: Path) -> ValidationResult:
        """Verify daemon can start with the installed configuration.

        Args:
            project_root: Project root to check

        Returns:
            ValidationResult
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Find venv python
        daemon_dir = project_root / ".claude" / "hooks-daemon"
        venv_python = daemon_dir / "untracked" / "venv" / "bin" / "python"

        if not venv_python.exists():
            errors.append(
                f"Python interpreter not found at: {venv_python}\n"
                f"Virtual environment may not be installed correctly."
            )
            return ValidationResult(passed=False, errors=errors, warnings=warnings)

        # Try to import the daemon package
        try:
            # SECURITY: Using venv python (trusted) with hardcoded import check (no user input)
            result = subprocess.run(  # nosec B603 - venv python is trusted, no shell, no user input
                [str(venv_python), "-c", "import claude_code_hooks_daemon; print('OK')"],
                capture_output=True,
                text=True,
                timeout=Timeout.VALIDATION_CHECK,
                check=False,
            )

            if result.returncode != 0:
                errors.append(
                    f"Failed to import claude_code_hooks_daemon:\n"
                    f"stdout: {result.stdout}\n"
                    f"stderr: {result.stderr}\n"
                    f"\n"
                    f"The daemon package may not be installed correctly in the venv."
                )

        except subprocess.TimeoutExpired:
            errors.append("Import verification timed out after 5 seconds")
        except Exception as e:
            errors.append(f"Failed to verify daemon can import: {e}")

        return ValidationResult(passed=len(errors) == 0, errors=errors, warnings=warnings)

    @staticmethod
    def cleanup_stale_runtime_files(project_root: Path) -> ValidationResult:
        """Clean up stale socket and PID files before upgrade.

        Args:
            project_root: Project root to clean

        Returns:
            ValidationResult with warnings about cleaned files
        """
        errors: list[str] = []
        warnings: list[str] = []

        daemon_dir = project_root / ".claude" / "hooks-daemon"
        if not daemon_dir.exists():
            return ValidationResult(passed=True, errors=[], warnings=[])

        untracked_dir = daemon_dir / "untracked"
        if not untracked_dir.exists():
            return ValidationResult(passed=True, errors=[], warnings=[])

        # Clean up socket files
        for socket_file in untracked_dir.glob("daemon*.sock"):
            try:
                socket_file.unlink()
                warnings.append(f"Removed stale socket file: {socket_file.name}")
            except Exception as e:
                warnings.append(f"Failed to remove socket file {socket_file.name}: {e}")

        # Clean up PID files (only if process not running)
        for pid_file in untracked_dir.glob("daemon*.pid"):
            try:
                with pid_file.open() as f:
                    pid = int(f.read().strip())

                # Check if process is alive
                try:
                    os.kill(pid, 0)
                    warnings.append(
                        f"Skipped PID file {pid_file.name} (process {pid} still running)"
                    )
                except ProcessLookupError:
                    # Process not running - safe to remove
                    pid_file.unlink()
                    warnings.append(f"Removed stale PID file: {pid_file.name}")

            except (ValueError, FileNotFoundError, PermissionError):
                # Invalid or unreadable PID file - remove it
                try:
                    pid_file.unlink()
                    warnings.append(f"Removed invalid PID file: {pid_file.name}")
                except Exception as e:
                    warnings.append(f"Failed to remove PID file {pid_file.name}: {e}")

        return ValidationResult(passed=True, errors=[], warnings=warnings)
