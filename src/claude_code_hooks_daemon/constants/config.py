"""Configuration key constants - single source of truth.

This module defines all configuration key names used in the daemon's
YAML configuration files and runtime config access.

Usage:
    from claude_code_hooks_daemon.constants import ConfigKey

    # In config access:
    handler_config = config[ConfigKey.HANDLERS]
    enabled = handler_config[handler_name][ConfigKey.ENABLED]

    # In config validation:
    if ConfigKey.PRIORITY in handler_config:
        priority = handler_config[ConfigKey.PRIORITY]
"""

from __future__ import annotations


class ConfigKey:
    """Configuration key names - single source of truth.

    These are the exact key names used in YAML configuration files
    and runtime configuration access. All keys use snake_case format.

    Config Structure:
        version: str
        daemon: DaemonConfig
        handlers: dict[HandlerName, HandlerConfig]
        plugins: PluginConfig
    """

    # Top-level config keys
    VERSION = "version"
    DAEMON = "daemon"
    HANDLERS = "handlers"
    PLUGINS = "plugins"

    # Handler-specific config keys
    ENABLED = "enabled"
    PRIORITY = "priority"
    OPTIONS = "options"
    ENABLE_TAGS = "enable_tags"
    DISABLE_TAGS = "disable_tags"
    SHARES_OPTIONS_WITH = "shares_options_with"
    DEPENDS_ON = "depends_on"

    # Daemon config keys
    IDLE_TIMEOUT_SECONDS = "idle_timeout_seconds"
    LOG_LEVEL = "log_level"
    SOCKET_PATH = "socket_path"
    PID_FILE_PATH = "pid_file_path"
    LOG_BUFFER_SIZE = "log_buffer_size"
    REQUEST_TIMEOUT_SECONDS = "request_timeout_seconds"
    SELF_INSTALL_MODE = "self_install_mode"
    ENABLE_HELLO_WORLD_HANDLERS = "enable_hello_world_handlers"
    INPUT_VALIDATION = "input_validation"

    # Plugin config keys
    PLUGIN_DIRS = "plugin_dirs"
    AUTO_LOAD = "auto_load"

    # Common option keys (used in handler options)
    STRICT_MODE = "strict_mode"
    DRY_RUN = "dry_run"
    VERBOSE = "verbose"
    THRESHOLD = "threshold"
    PATTERN = "pattern"
    EXCLUDE = "exclude"
    INCLUDE = "include"


__all__ = ["ConfigKey"]
