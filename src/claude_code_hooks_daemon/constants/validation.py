"""Validation limit constants - single source of truth.

This module defines all validation limits, thresholds, and constraints
used throughout the daemon for config validation, buffer sizes, timeouts, etc.

Usage:
    from claude_code_hooks_daemon.constants import ValidationLimit

    # In Pydantic model:
    log_buffer_size: int = Field(
        default=ValidationLimit.LOG_BUFFER_DEFAULT,
        ge=ValidationLimit.LOG_BUFFER_MIN,
        le=ValidationLimit.LOG_BUFFER_MAX,
    )
"""

from __future__ import annotations


class ValidationLimit:
    """Validation limits and thresholds - single source of truth.

    These constants define validation boundaries for configuration values,
    buffer sizes, and other numeric constraints throughout the daemon.

    Categories:
        - Log buffer: Size limits for daemon log buffer
        - Timeouts: Min/max values for timeout configurations
        - Paths: Length and validation constraints
        - Handlers: Limits on handler configuration
    """

    # Log buffer size limits (entries)
    LOG_BUFFER_MIN = 100
    LOG_BUFFER_MAX = 100_000
    LOG_BUFFER_DEFAULT = 1_000

    # Request timeout limits (seconds)
    REQUEST_TIMEOUT_MIN = 1
    REQUEST_TIMEOUT_MAX = 300
    REQUEST_TIMEOUT_DEFAULT = 30

    # Idle timeout limits (seconds)
    IDLE_TIMEOUT_MIN = 1
    IDLE_TIMEOUT_MAX = 86_400  # 24 hours
    IDLE_TIMEOUT_DEFAULT = 600  # 10 minutes

    # Priority limits
    PRIORITY_MIN = 0
    PRIORITY_MAX = 100
    PRIORITY_DEFAULT = 50

    # Handler name length limits
    HANDLER_NAME_MIN_LENGTH = 3
    HANDLER_NAME_MAX_LENGTH = 100

    # Config version limits
    CONFIG_VERSION_MIN_MAJOR = 1
    CONFIG_VERSION_MAX_MAJOR = 10

    # Plugin limits
    MAX_PLUGINS = 100
    MAX_PLUGIN_DIRS = 10

    # Path length limits
    MAX_PATH_LENGTH = 4096  # Maximum path length on most systems
    MAX_SOCKET_PATH_LENGTH = 108  # Unix socket path limit

    # Handler tag limits
    MAX_TAGS_PER_HANDLER = 20
    MAX_TAG_LENGTH = 50


__all__ = ["ValidationLimit"]
