"""Daemon configuration management.

DEPRECATED: This module re-exports DaemonConfig from config.models for backward compatibility.
New code should import directly from claude_code_hooks_daemon.config.models.
"""

# Re-export DaemonConfig from config.models (Pydantic version with input_validation)
from claude_code_hooks_daemon.config.models import DaemonConfig

__all__ = ["DaemonConfig"]
