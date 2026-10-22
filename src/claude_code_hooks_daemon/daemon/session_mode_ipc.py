"""The per-session mode IPC actions (Plan 00501 Task 3.3).

``get_session_modes`` lists one session's modes; ``enter_focus`` and
``exit_focus`` change its focus through the same operations the prompt command
uses (``core.focus_mode``), so entering focus clears an existing goal once on
every route. The daemon-wide ``get_mode``/``set_mode`` actions are separate and
unchanged.

A request naming no session is refused; a registry failure is logged at
WARNING and returned as an error, never read as "no modes".
"""

from __future__ import annotations

import logging
from typing import Any

from claude_code_hooks_daemon.constants.modes import SessionModeIPC
from claude_code_hooks_daemon.core.data_layer import get_data_layer
from claude_code_hooks_daemon.core.focus_mode import FocusChange, enter_focus, exit_focus
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.session_modes import SessionModeEntry

logger = logging.getLogger(__name__)


def clear_goal_signal(session_id: str) -> bool:
    """Signal the goal clear for ``session_id``; False when it could not be written.

    The import is deferred: this module is imported by ``daemon.server``, and the
    ``handlers.post_tool_use`` package imports ``install``, which imports
    ``daemon.server`` back. ``cmd_clear_goal`` in ``daemon.cli`` defers the same
    import for the same reason.
    """
    from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import (
        clear_goal_signal as clear,
    )

    return clear(session_id)


def handle_session_mode_action(action: str, hook_input: dict[str, Any]) -> dict[str, Any]:
    """Answer one session-mode IPC request.

    Args:
        action: One of :attr:`SessionModeIPC.ACTIONS`.
        hook_input: The request's fields (``session_id``, and ``task`` to enter focus).

    Returns:
        ``{"result": ...}``, or ``{"error": ...}`` for a bad request or a registry failure.

    Raises:
        ValueError: ``action`` is not a session-mode action (a dispatch defect).
    """
    if action not in SessionModeIPC.ACTIONS:
        raise ValueError(f"{action!r} is not a session-mode action")
    session_id = hook_input.get(SessionModeIPC.KEY_SESSION_ID)
    if not isinstance(session_id, str) or not session_id.strip():
        return {"error": f"'{SessionModeIPC.KEY_SESSION_ID}' must name the session"}
    task = hook_input.get(SessionModeIPC.KEY_TASK)
    if action == SessionModeIPC.ACTION_ENTER_FOCUS and not isinstance(task, str):
        return {"error": f"'{SessionModeIPC.KEY_TASK}' must give the focus task"}
    try:
        registry = get_data_layer().session_modes
        return {"result": _answer(registry, action, session_id, task)}
    except (RuntimeError, OSError) as error:
        log_and_continue(
            logger,
            error,
            reason=f"the session-modes registry could not answer {action}; the caller gets the error",
        )
        return {"error": f"session modes unavailable: {error}"}


def _answer(
    registry: SessionModeRegistry, action: str, session_id: str, task: object
) -> dict[str, Any]:
    """The result of a validated request."""
    if action == SessionModeIPC.ACTION_GET_SESSION_MODES:
        policy = registry.policy(session_id)
        return {
            SessionModeIPC.KEY_SESSION_ID: session_id,
            SessionModeIPC.KEY_BADGE: policy.badge(),
            SessionModeIPC.KEY_MODES: [_entry(entry) for entry in policy.entries],
        }
    if action == SessionModeIPC.ACTION_ENTER_FOCUS:
        return _change(enter_focus(registry, session_id, str(task), clear_goal=clear_goal_signal))
    return _change(exit_focus(registry, session_id))


def _entry(entry: SessionModeEntry) -> dict[str, Any]:
    return {
        SessionModeIPC.KEY_LABEL: str(entry.label),
        SessionModeIPC.KEY_MODE: str(entry.mode),
        SessionModeIPC.KEY_REASON: None if entry.reason is None else str(entry.reason),
        SessionModeIPC.KEY_SOURCE: str(entry.source),
        SessionModeIPC.KEY_DETAIL: entry.detail,
        SessionModeIPC.KEY_ENTERED_AT: entry.entered_at,
        SessionModeIPC.KEY_EXPIRES_AT: entry.expires_at,
    }


def _change(change: FocusChange) -> dict[str, Any]:
    return {
        SessionModeIPC.KEY_OUTCOME: str(change.outcome),
        SessionModeIPC.KEY_TASK: change.task,
        SessionModeIPC.KEY_LINE: change.line(),
    }
