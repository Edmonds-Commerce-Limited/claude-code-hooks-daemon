"""Core components of the hooks daemon.

This module exports the primary classes and utilities for
building and running hook handlers.
"""

from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest, TestType
from claude_code_hooks_daemon.core.chain import ChainExecutionResult, HandlerChain
from claude_code_hooks_daemon.core.data_layer import (
    DaemonDataLayer,
    get_data_layer,
    reset_data_layer,
)
from claude_code_hooks_daemon.core.error_response import generate_daemon_error_response
from claude_code_hooks_daemon.core.event import EventType, HookEvent, HookInput, ToolInput
from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.handler_history import HandlerDecisionRecord, HandlerHistory
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.language_config import (
    GO_CONFIG,
    PHP_CONFIG,
    PYTHON_CONFIG,
    LanguageConfig,
    get_language_config,
)
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.core.session_state import SessionState
from claude_code_hooks_daemon.core.transcript_reader import (
    ToolUse,
    TranscriptMessage,
    TranscriptReader,
)

__all__ = [
    "GO_CONFIG",
    "PHP_CONFIG",
    "PYTHON_CONFIG",
    "AcceptanceTest",
    "ChainExecutionResult",
    "DaemonDataLayer",
    "Decision",
    "EventRouter",
    "EventType",
    "FrontController",
    "Handler",
    "HandlerChain",
    "HandlerDecisionRecord",
    "HandlerHistory",
    "HookEvent",
    "HookInput",
    "HookResult",
    "LanguageConfig",
    "ProjectContext",
    "SessionState",
    "TestType",
    "ToolInput",
    "ToolUse",
    "TranscriptMessage",
    "TranscriptReader",
    "generate_daemon_error_response",
    "get_data_layer",
    "get_language_config",
    "reset_data_layer",
]
