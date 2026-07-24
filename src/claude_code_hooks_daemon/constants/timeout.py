"""Timeout constants - Single source of truth for all timeout values.

This module defines all timeout values used throughout the daemon.
Eliminates magic numbers for timeouts and makes them easy to adjust.

Usage:
    from claude_code_hooks_daemon.constants import Timeout

    # Don't use: timeout=120000
    # Do use:
    result = execute_command(timeout=Timeout.BASH_DEFAULT)
"""


class Timeout:
    """Timeout constants in various units.

    All timeout values are defined here to avoid magic numbers.
    Units are indicated in constant names or comments.
    """

    # Bash command timeouts (milliseconds)
    BASH_DEFAULT = 120_000  # 2 minutes (default for most commands)
    BASH_MAX = 600_000  # 10 minutes (maximum allowed)
    BASH_SHORT = 30_000  # 30 seconds (for quick operations)
    BASH_LONG = 300_000  # 5 minutes (for slower operations)

    # Daemon timeouts (seconds, for daemon configuration)
    DAEMON_IDLE = 600  # 10 minutes (daemon idle before shutdown)
    DAEMON_STARTUP = 30  # 30 seconds (wait for daemon to start)
    DAEMON_SHUTDOWN = 10  # 10 seconds (wait for daemon to shutdown)

    # Request timeouts (seconds)
    REQUEST_DEFAULT = 30  # 30 seconds (client request timeout)
    REQUEST_LONG = 60  # 1 minute (for long-running requests)

    # Hook dispatch timeouts (milliseconds)
    HOOK_DISPATCH = 5_000  # 5 seconds (max time for single handler)
    HOOK_TOTAL = 30_000  # 30 seconds (max time for all handlers in chain)

    # Network/IO timeouts (seconds)
    SOCKET_CONNECT = 5  # 5 seconds (Unix socket connection)
    FILE_LOCK = 10  # 10 seconds (file lock acquisition)

    # Retry timeouts (milliseconds)
    RETRY_DELAY_SHORT = 100  # 100ms (initial retry delay)
    RETRY_DELAY_MEDIUM = 500  # 500ms (medium retry delay)
    RETRY_DELAY_LONG = 2_000  # 2 seconds (long retry delay)

    # Handler-specific timeouts (seconds, used in subprocess calls)
    ESLINT_CHECK = 30  # 30 seconds (ESLint validation)
    LINT_CHECK = 15  # 15 seconds (generic lint validation)
    GIT_STATUS_SHORT = 0.5  # 0.5 seconds (quick git status check)
    GIT_CONTEXT = 5  # 5 seconds (git context gathering)
    GIT_FETCH_BACKGROUND = 30  # 30 seconds (background git fetch in status line)
    GIT_FETCH_SESSION = 30  # 30 seconds (full fetch --all --prune on session start)
    GIT_PULL_SESSION = 30  # 30 seconds (git pull --ff-only in auto-pull mode)
    GIT_WORKTREE = 30  # 30 seconds (git worktree add/remove for WorktreeCreate/Remove)
    VALIDATION_CHECK = 5  # 5 seconds (installation validation subprocess)
    VERSION_CHECK = 5  # 5 seconds (git ls-remote for version check)

    # QA runner timeouts (seconds)
    QA_TEST_TIMEOUT = 120  # 2 minutes (mypy, individual tool checks)
    QA_LONG_TIMEOUT = 300  # 5 minutes (pytest, full test suite)

    # Process management timeouts (seconds)
    PROCESS_KILL_WAIT = 2  # 2 seconds (wait for SIGTERM before SIGKILL)

    # Daemon startup polling (Plan 00100 Task 0.2)
    DAEMON_PID_POLL_INTERVAL_SEC = 0.1  # 100ms between PID-file checks
    DAEMON_PID_POLL_MAX_ITERATIONS = 50  # 50 x 100ms = 5s ceiling
    DAEMON_RESTART_VERIFY_TIMEOUT_SEC = 15  # Overall restart verification ceiling

    # Live-daemon socket-liveness probe (Plan 00127). Connect-timeout for
    # probing whether an existing Unix socket is owned by a live daemon before
    # unlinking it. Fast: a local AF_UNIX connect is sub-millisecond when a
    # listener is present; 0.5s tolerates a momentarily-busy accept queue
    # without stalling start. A live-but-slower-than-this daemon is treated as
    # unhealthy and replaced (Decision 1 fail-fast trade-off).
    SOCKET_LIVENESS_PROBE_SEC = 0.5
