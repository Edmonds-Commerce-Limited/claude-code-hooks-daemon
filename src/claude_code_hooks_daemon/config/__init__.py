"""Configuration loading and validation.

This module provides both legacy (jsonschema-based) and modern
(Pydantic-based) configuration handling.
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
from claude_code_hooks_daemon.config.schema import ConfigSchema
from claude_code_hooks_daemon.config.validation_ux import format_validation_error
from claude_code_hooks_daemon.config.validator import ConfigValidator, ValidationError

__all__ = [
    # Pydantic models (preferred)
    "Config",
    # Legacy support
    "ConfigLoader",
    "ConfigSchema",
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
