"""
Claude Code Hooks Daemon.

A reusable, configurable daemon for Claude Code hooks using the front controller architecture.
"""

from claude_code_hooks_daemon.python_floor import require_min_python

# First, so `python -m claude_code_hooks_daemon...` under a too-old interpreter
# gets one clear line instead of the first import's traceback.
require_min_python("claude_code_hooks_daemon")

from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.version import __version__

__all__ = ["FrontController", "Handler", "HookResult", "__version__"]
