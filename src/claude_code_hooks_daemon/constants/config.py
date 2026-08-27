"""Configuration key constants - single source of truth.

This module defines all configuration key names used in the daemon's
YAML configuration files and runtime config access.

Usage:
    from claude_code_hooks_daemon.constants import ConfigKey

    # In config access:
    handler_config = config[ConfigKey.HANDLERS]
    enabled = handler_config[handler_name][ConfigKey.ENABLED]

    # Resolving a handler priority (absent OR None both fall back):
    priority = resolve_priority(handler_config, instance.priority)

Note: do NOT test ``if ConfigKey.PRIORITY in handler_config`` against a
``model_dump()`` result — ``model_dump()`` materialises an UNSET field as an
explicit ``None``, so the key is present while its value is ``None``. Use
``resolve_priority`` (below), which treats absent and ``None`` identically.
The membership form is only correct against a RAW parsed-YAML dict, where an
omitted key is genuinely absent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


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


def resolve_priority(handler_config: Mapping[str, Any], fallback: int) -> int:
    """Return the config's ``priority``, or ``fallback`` when absent OR ``None``.

    Single source of truth for the three consumers (runtime dispatch in
    ``registry.py`` and both documentation generators). Two shapes both mean
    "no priority given, use the handler's own default":

    - ``config.handlers.model_dump()`` materialises an UNSET ``priority`` field
      as an explicit ``None`` (not an absent key), so a plain
      ``.get(PRIORITY, fallback)`` returns that ``None`` — the default never
      applies, and ``None`` reaches a sort key and raises (Plan 00282).
    - PyYAML parses a bare ``priority:`` line as ``None`` (Plan 00070).

    Only an explicit integer overrides the fallback (``0`` included); anything
    non-integer — ``None`` or an absent key — falls back.
    """
    value = handler_config.get(ConfigKey.PRIORITY)
    if isinstance(value, int):
        return value
    return fallback


__all__ = ["ConfigKey", "resolve_priority"]
