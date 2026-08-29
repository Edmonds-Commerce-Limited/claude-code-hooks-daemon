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
    """Client-project path constants that are genuinely daemon-wide.

    This class used to also carry a much larger set of "client project
    layout" members (doc dirs, plan dirs, test dirs, source dirs — a
    project's OWN structure, as opposed to the daemon's). Per-project
    layout truths now have a proper home: the ``layout:`` config block and
    the ``ProjectLayout`` runtime facade (``core/project_layout.py``,
    Plan 00288). A repo-wide measurement
    (``CLAUDE/Plan/00288-project-layout-config-ssot/MEASUREMENT-vendored-dirs.md``)
    found every one of those removed members had ZERO live callers — dead
    code, not a migration in progress — so they were deleted rather than
    re-scoped. The three members that remain are genuinely daemon-wide
    (worktree root conventions and the vendored install path), not
    per-project client layout, so they stay here.
    """

    # Worktree directories
    WORKTREES_DIR = "untracked/worktrees"  # manually managed worktrees
    CLAUDE_WORKTREES_DIR = ".claude/worktrees"  # Claude Code managed worktrees (not configurable)

    # Vendored daemon install root in a CLIENT project (Task 3.6). Empty/absent
    # in self-install mode -- this repo runs the daemon from its own project
    # root rather than from a vendored copy under here (CLAUDE.md "Self-Install
    # Mode"), so exclusions keyed on this constant are inert in this repo.
    HOOKS_DAEMON_INSTALL_DIR = f"{DaemonPath.CLAUDE_DIR}/{DaemonPath.HOOKS_DAEMON_DIR}"
