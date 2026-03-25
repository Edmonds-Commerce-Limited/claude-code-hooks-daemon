"""Path constants - Single source of truth for all path components.

This module defines path components and patterns used throughout the daemon.
Eliminates magic strings for directory/file names.

Usage:
    from claude_code_hooks_daemon.constants import DaemonPath, ProjectPath
    from pathlib import Path

    # Don't use: path / ".claude" / "hooks-daemon"
    # Do use:
    daemon_dir = path / DaemonPath.CLAUDE_DIR / DaemonPath.HOOKS_DAEMON_DIR
"""


class DaemonPath:
    """Daemon-related path components.

    These are path components (not full paths) used to construct
    daemon file locations.
    """

    # Directory names
    CLAUDE_DIR = ".claude"
    HOOKS_DAEMON_DIR = "hooks-daemon"
    LOG_DIR = "logs"
    UNTRACKED_DIR = "untracked"
    VENV_DIR = "venv"
    SRC_DIR = "src"

    # File names
    CONFIG_FILE = "hooks-daemon.yaml"
    SOCKET_FILE = "daemon.sock"
    PID_FILE = "daemon.pid"
    ENV_FILE = "hooks-daemon.env"
    INSTALL_MARKER = ".installed"

    # Log file patterns
    LOG_FILE_PATTERN = "daemon-{date}.log"
    ERROR_LOG_FILE = "errors.log"


class ProjectPath:
    """Project-relative path constants.

    These define standard project structure paths.
    """

    # Documentation directories
    CLAUDE_DOC_DIR = "CLAUDE"
    PLAN_DIR = "CLAUDE/Plan"
    PLAN_COMPLETED_DIR = "CLAUDE/Plan/Completed"
    RELEASES_DIR = "RELEASES"
    UPGRADES_DIR = "UPGRADES"

    # Documentation files
    PLAN_WORKFLOW_DOC = "CLAUDE/PlanWorkflow.md"
    ARCHITECTURE_DOC = "CLAUDE/ARCHITECTURE.md"
    HANDLER_DEVELOPMENT_DOC = "CLAUDE/HANDLER_DEVELOPMENT.md"
    DEBUGGING_HOOKS_DOC = "CLAUDE/DEBUGGING_HOOKS.md"
    SELF_INSTALL_DOC = "CLAUDE/SELF_INSTALL.md"
    CLAUDE_MD = "CLAUDE.md"
    README_MD = "README.md"
    CONTRIBUTING_MD = "CONTRIBUTING.md"

    # Plan files
    PLAN_FILE = "PLAN.md"
    PLAN_README = "CLAUDE/Plan/README.md"

    # Script directories
    SCRIPTS_DIR = "scripts"
    QA_SCRIPTS_DIR = "scripts/qa"

    # Test directories
    TESTS_DIR = "tests"
    UNIT_TESTS_DIR = "tests/unit"
    INTEGRATION_TESTS_DIR = "tests/integration"

    # Source directories
    SRC_DIR = "src"
    HANDLERS_DIR = "src/claude_code_hooks_daemon/handlers"
    CONFIG_DIR = "src/claude_code_hooks_daemon/config"
    CORE_DIR = "src/claude_code_hooks_daemon/core"
    DAEMON_DIR = "src/claude_code_hooks_daemon/daemon"

    # Config files
    PYPROJECT_TOML = "pyproject.toml"
    SETUP_PY = "setup.py"
    REQUIREMENTS_TXT = "requirements.txt"
