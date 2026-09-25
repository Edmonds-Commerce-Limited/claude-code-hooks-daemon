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
    # A process that ignores SIGTERM for the whole `SOCKET_CONNECT` grace
    # period (Plan 00466 N40 review 2 MA2) is escalated to SIGKILL, which a
    # process cannot catch, block or ignore -- this second, shorter budget is
    # only for the OS to actually reap it afterward.
    DAEMON_SIGKILL_GRACE = 2  # 2 seconds (wait after SIGKILL for the OS to reap)
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
    # Daemon-side chain deadline (seconds; Plan 00466 N25). Well under
    # HOOK_TOTAL's 30s client budget: a client-side timeout fails the WHOLE
    # chain OPEN (`.claude/init.sh` reads it as an empty context, an ALLOW
    # for every non-Stop event), so a slow handler bypassed every guard
    # behind it. Enforced inside `HandlerChain.execute` instead, where a
    # SAFETY+BLOCKING handler can still be told from an advisory and denied
    # rather than silently skipped.
    CHAIN_DEADLINE_DEFAULT = 20

    # Minimum gap required (Plan 00466 N40 m6) between ChainConfig's
    # deadline_seconds and the client's own socket timeout
    # (SOCKET_DISPATCH_ROUNDTRIP, defined below). A deadline flush against —
    # or merely close to — the client timeout reproduces the exact fail-open
    # bypass deadline_seconds exists to close: the client gives up and fails
    # the whole chain open before the daemon's deadline-triggered deny can be
    # built and sent back over the socket. 5s covers the time to serialise
    # and flush a response after the deadline fires.
    CHAIN_DEADLINE_SOCKET_MARGIN_SECONDS = 5

    # SAFETY handler input-size cap in bytes (Plan 00466 N34 remedy 3),
    # defence in depth alongside CHAIN_DEADLINE_DEFAULT. Ordinary source
    # files are typically well under a few hundred KB; 2 MiB stays
    # comfortably above even a large generated asset while still catching a
    # payload far outside normal use BEFORE dispatch overhead is spent on it.
    SAFETY_INPUT_SIZE_CAP_BYTES = 2 * 1024 * 1024  # 2 MiB

    # Straggler health thresholds (Plan 00466 N40 M2): an abandoned handler
    # dispatch ("straggler") is one whose own BoundedDispatcher.run() call
    # already gave up waiting on it -- it is still running in the
    # background, consuming a thread (and, if CPU-bound, real CPU) with no
    # verdict ever coming. A handful is unremarkable; enough of them at once,
    # or one stuck long enough, means the daemon can no longer promise a
    # timely verdict at all.
    STRAGGLER_UNHEALTHY_COUNT = 4  # concurrent stragglers before DEGRADED health
    STRAGGLER_RESTART_AFTER_SECONDS = 120  # oldest straggler's age before self-restart

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
    # 120 seconds (branch-safety proof engine: `cherry`, `rev-list --objects`,
    # `ls-tree -r`). These are OBJECT WALKS, not context reads — a patch-id per
    # commit, or every tree and blob reachable from a ref — so their cost scales
    # with repository size, not with anything a hook budget models. Before Plan
    # 00246 centralised git spawning they ran UNBOUNDED; inheriting GIT_CONTEXT's
    # five seconds broke `delete-branch` on any large repo (Plan 00248 F1).
    # Bounded rather than unbounded, so a wedged git still cannot hang the CLI
    # forever, but generous enough that repository size alone never trips it.
    GIT_BRANCH_SAFETY = 120
    # 300 seconds (`git bundle create` for the recovery bundle). The heaviest
    # call in the proof engine — it PACKS the objects — and the one that must
    # never be killed part-way: it is written before any ref is removed, so a
    # truncated bundle is a lost recovery rather than a slow one.
    GIT_BUNDLE_CREATE = 300
    VALIDATION_CHECK = 5  # 5 seconds (installation validation subprocess)
    VERSION_CHECK = 5  # 5 seconds (git ls-remote for version check)
    # 10 seconds (`ps -eo ...` for the background harvester). A local process
    # table read returns in milliseconds; the ceiling exists so a wedged `ps` on
    # a loaded box cannot hang the hourly harvest tick rather than to model any
    # expected duration.
    PROCESS_SAMPLE = 10
    # 30 seconds (`gh run list` for CI state). This one reaches the NETWORK,
    # where slow is the normal weather rather than a fault, so it is the most
    # generous of the short bounds — but bounded, because an unbounded network
    # call in a CLI command is a hang with no error to read.
    GH_API_QUERY = 30

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

    # Test-only wait budgets for BoundedDispatcher/chain dispatch tests (Plan
    # 00466 N40 review 2 MA1): an unnamed timeout literal is exactly as opaque
    # in test code as in production, and check_magic_values.py's
    # magic-timeout rule applies to both. Named by MAGNITUDE/role, not by
    # individual call site, since many call sites share the same budget for
    # the same reason (force a DispatchTimeout, or wait for a background
    # straggler thread to settle before the next test starts).
    DISPATCH_TEST_INSTANT = 0.01  # sub-tick: forces an already-expired wait
    DISPATCH_TEST_VERY_SHORT = 0.02  # forces DispatchTimeout against a slow callable
    DISPATCH_TEST_SHORT = 0.05  # forces DispatchTimeout with a slightly larger margin
    DISPATCH_TEST_NORMAL = 1.0  # generous wait for a background thread to settle
    DISPATCH_TEST_GENEROUS = 5.0  # generous wait under CI/host load
    DISPATCH_TEST_OUTER_BOUND = 10  # outer ceiling for a probe socket's own settimeout()
