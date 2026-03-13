"""
Claude Code Hooks Daemon.

A reusable, configurable daemon for Claude Code hooks using the front controller architecture.
"""

from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.version import __version__

__all__ = ["FrontController", "Handler", "HookResult", "__version__"]
