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
