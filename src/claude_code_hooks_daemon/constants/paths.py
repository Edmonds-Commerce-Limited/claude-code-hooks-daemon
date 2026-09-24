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

    # The sanctioned home for scratch: commit-message files, command captures,
    # probes, prototypes (Plan 00333). Inside the working tree so it survives a
    # container restart, and gitignored so it never reaches review. Named here
    # rather than in the handler because two surfaces must agree on it --
    # `project_containment` DENIES writes outside the repo and points here, and
    # `pipe_blocker` RECOMMENDS a capture target. If those two drifted, the
    # daemon would advise what it then blocks.
    SCRATCH_DIR = f"{DaemonPath.UNTRACKED_DIR}/scratch"

    #: Absolute roots that are wiped between container runs (Plan 00333). The
    #: `project_containment` handler does not read this -- it is deny-by-default
    #: and needs no list of bad places. This exists for the Claude Code
    #: `permissions.deny` BACKSTOP, which cannot express a whitelist: its rules
    #: evaluate deny before allow with the first match winning, so a broad deny
    #: cannot carry an allow exception for the project, there is no negation
    #: syntax, and there is no writes counterpart to
    #: `blockReadsOutsideWorkingDirectories`. Enumeration is therefore the only
    #: shape available at that layer, and this constant is what keeps the
    #: enumeration honest instead of hand-maintained.
    #: nosec B108 - these paths are the SUBJECT of a deny rule, never a
    #: destination. Bandit's check cannot tell "writes here" from "forbids
    #: writing here", and this is the second: the enumeration is emitted into
    #: `permissions.deny`. Suppressed for the same reason `daemon/paths.py`
    #: suppresses it, with the opposite polarity.
    EPHEMERAL_ROOTS: tuple[str, ...] = ("/tmp", "/var/tmp", "/dev/shm")  # nosec B108

    @staticmethod
    def claude_code_deny_rule(root: str) -> str:
        """The `permissions.deny` rule denying writes under an absolute root.

        Args:
            root: Absolute path, e.g. ``/tmp``.

        Returns:
            A rule such as ``Edit(//tmp/**)``. Three details are load-bearing
            and none is guessable: the tool is ``Edit`` (``Write`` is not a
            permission-rule tool name and would match nothing), the leading
            ``//`` marks an ABSOLUTE path where a single slash would anchor to
            the settings file's own location, and ``/**`` makes it recursive.
        """
        return f"Edit(/{root}/**)"

    # Worktree directories
    WORKTREES_DIR = "untracked/worktrees"  # manually managed worktrees
    CLAUDE_WORKTREES_DIR = ".claude/worktrees"  # Claude Code managed worktrees (not configurable)

    # Vendored daemon install root in a CLIENT project (Task 3.6). Empty/absent
    # in self-install mode -- this repo runs the daemon from its own project
    # root rather than from a vendored copy under here (CLAUDE.md "Self-Install
    # Mode"), so exclusions keyed on this constant are inert in this repo.
    HOOKS_DAEMON_INSTALL_DIR = f"{DaemonPath.CLAUDE_DIR}/{DaemonPath.HOOKS_DAEMON_DIR}"
