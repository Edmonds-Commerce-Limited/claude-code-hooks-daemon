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

    # Unit conversion. Named so that a constant declared in one unit can be
    # re-expressed in another without a bare 1000 tripping the magic-value gate.
    MILLISECONDS_PER_SECOND = 1_000

    # Daemon timeouts (seconds, for daemon configuration)
    DAEMON_IDLE = 600  # 10 minutes (daemon idle before shutdown)
    DAEMON_STARTUP = 30  # 30 seconds (wait for daemon to start)
    DAEMON_SHUTDOWN = 10  # 10 seconds (wait for daemon to shutdown)
    # A restart is a shutdown FOLLOWED BY a startup, so its budget is the sum.
    # Giving it DAEMON_SHUTDOWN alone asserts that stop-and-start fits inside
    # the stop budget -- structurally impossible whenever startup is the slower
    # half, which it is here by 3x.
    DAEMON_RESTART = DAEMON_SHUTDOWN + DAEMON_STARTUP

    # Request timeouts (seconds)
    REQUEST_DEFAULT = 30  # 30 seconds (client request timeout)
    REQUEST_LONG = 60  # 1 minute (for long-running requests)

    # Hook dispatch timeouts (milliseconds)
    HOOK_DISPATCH = 5_000  # 5 seconds (max time for single handler)
    HOOK_TOTAL = 30_000  # 30 seconds (max time for all handlers in chain)

    # Network/IO timeouts (seconds)
    SOCKET_CONNECT = 5  # 5 seconds (Unix socket connection)
    FILE_LOCK = 10  # 10 seconds (file lock acquisition)
    # A full send-hook-and-await-response round-trip over the socket. This is
    # NOT the same budget as SOCKET_CONNECT and must never borrow it: connecting
    # to a local AF_UNIX socket is sub-millisecond, whereas the response is only
    # written after the whole handler chain has run -- an operation the daemon
    # itself bounds at HOOK_TOTAL. A test that puts a connect-sized budget on a
    # dispatch recv is silently asserting a latency budget it never meant to
    # assert, and fails under CPU contention rather than on any defect.
    SOCKET_DISPATCH_ROUNDTRIP = HOOK_TOTAL / MILLISECONDS_PER_SECOND

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
    # 30 seconds (CLAUDE.md auto-commit). Deliberately generous rather than
    # tight: a commit runs the repo's pre-commit hooks, and subprocess kills the
    # child when a timeout expires — killing git mid-commit is itself how
    # .git/index.lock gets orphaned. Long enough for a hook-running commit to
    # finish, short enough that a wedged git cannot hang daemon startup forever.
    GIT_COMMIT = 30
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
