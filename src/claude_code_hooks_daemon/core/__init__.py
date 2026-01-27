"""Core components of the hooks daemon.

This module exports the primary classes and utilities for
building and running hook handlers.
"""

from claude_code_hooks_daemon.core.chain import ChainExecutionResult, HandlerChain
from claude_code_hooks_daemon.core.error_response import generate_daemon_error_response
from claude_code_hooks_daemon.core.event import EventType, HookEvent, HookInput, ToolInput
from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.router import EventRouter

__all__ = [
    "ChainExecutionResult",
    "Decision",
    "EventRouter",
    "EventType",
    "FrontController",
    "Handler",
    "HandlerChain",
    "HookEvent",
    "HookInput",
    "HookResult",
    "ToolInput",
    "generate_daemon_error_response",
]
