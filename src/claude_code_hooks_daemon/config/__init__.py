"""Configuration loading and validation.

``ConfigLoader`` discovers and reads the YAML; ``ConfigValidator`` (backed by
the Pydantic ``Config`` model) is the single validation path the daemon runs
at startup. Its event-type coverage is derived from ``wired_event_metas()``,
so there is deliberately no second, hand-enumerated schema beside it.
"""

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import (
    Config,
    DaemonConfig,
    HandlerConfig,
    HandlersConfig,
    LogLevel,
    PluginConfig,
    PluginsConfig,
)
from claude_code_hooks_daemon.config.validation_ux import format_validation_error
from claude_code_hooks_daemon.config.validator import ConfigValidator, ValidationError

__all__ = [
    "Config",
    "ConfigLoader",
    "ConfigValidator",
    "DaemonConfig",
    "HandlerConfig",
    "HandlersConfig",
    "LogLevel",
    "PluginConfig",
    "PluginsConfig",
    "ValidationError",
    "format_validation_error",
]
