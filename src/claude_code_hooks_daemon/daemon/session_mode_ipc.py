"""The per-session mode IPC actions (Plan 00501 Task 3.3).

``get_session_modes`` lists one session's modes; ``enter_focus`` and
``exit_focus`` change its focus through the same operations the prompt command
uses (``core.focus_mode``), so entering focus clears an existing goal once on
every route. ``get_mode_history`` (Task 4.3) lists every session's live modes
and the newest transitions with their evidence. The daemon-wide
``get_mode``/``set_mode`` actions are separate and unchanged.
``exit_blocked`` (Task 6.3) ends a goal-loop block; when only the declared
awaiting-human block is live it is refused with a named error.
``enter_manual_goals``/``exit_manual_goals`` (Task 8.3) turn automated goals
off and back on through ``core.manual_goals``, as the prompt command does.

A request naming no session is refused; a registry failure is logged at
WARNING and returned as an error, never read as "no modes".
"""

from __future__ import annotations

import logging
from typing import Any

from claude_code_hooks_daemon.constants.modes import SessionModeIPC
from claude_code_hooks_daemon.core.data_layer import get_data_layer
from claude_code_hooks_daemon.core.focus_mode import FocusChange, enter_focus, exit_focus
from claude_code_hooks_daemon.core.goal_loop_block import (
    DeclaredBlockRefusedError,
    unblock_goal_loop,
)
from claude_code_hooks_daemon.core.manual_goals import (
    GoalsChange,
    enter_manual_goals,
    exit_manual_goals,
)
from claude_code_hooks_daemon.core.session_mode_log import TransitionLogError
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.session_modes import ModeSource, SessionModeEntry

logger = logging.getLogger(__name__)

#: The transition log's evidence for a focus change made through IPC.
_IPC_EVIDENCE = "the session-mode CLI or /mode skill"
#: The transition log's evidence for an unblock made through IPC (exit 6.4: explicit clear).
_UNBLOCK_EVIDENCE = f"cause=explicit-clear ({_IPC_EVIDENCE})"


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
    if action == SessionModeIPC.ACTION_GET_MODE_HISTORY:
        return _mode_history(hook_input)
    session_id = hook_input.get(SessionModeIPC.KEY_SESSION_ID)
    if not isinstance(session_id, str) or not session_id.strip():
        return {"error": f"'{SessionModeIPC.KEY_SESSION_ID}' must name the session"}
    task = hook_input.get(SessionModeIPC.KEY_TASK)
    if action == SessionModeIPC.ACTION_ENTER_FOCUS and not isinstance(task, str):
        return {"error": f"'{SessionModeIPC.KEY_TASK}' must give the focus task"}
    try:
        registry = get_data_layer().session_modes
        return {"result": _answer(registry, action, session_id, task)}
    except DeclaredBlockRefusedError as error:
        # unblock_goal_loop has already logged the refusal at WARNING.
        return {"error": str(error)}
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
        return _change(
            enter_focus(
                registry,
                session_id,
                str(task),
                clear_goal=clear_goal_signal,
                evidence=_IPC_EVIDENCE,
            )
        )
    if action == SessionModeIPC.ACTION_EXIT_BLOCKED:
        change = unblock_goal_loop(registry, session_id, evidence=_UNBLOCK_EVIDENCE)
        return {
            SessionModeIPC.KEY_OUTCOME: str(change.outcome),
            SessionModeIPC.KEY_LINE: change.line(),
        }
    if action == SessionModeIPC.ACTION_ENTER_MANUAL_GOALS:
        return _goals_change(
            enter_manual_goals(
                registry, session_id, source=ModeSource.HUMAN, evidence=_IPC_EVIDENCE
            )
        )
    if action == SessionModeIPC.ACTION_EXIT_MANUAL_GOALS:
        return _goals_change(exit_manual_goals(registry, session_id, evidence=_IPC_EVIDENCE))
    return _change(exit_focus(registry, session_id, evidence=_IPC_EVIDENCE))


def _mode_history(hook_input: dict[str, Any]) -> dict[str, Any]:
    """Every session's live modes (or one session's) and the newest transitions.

    An absent or unreadable transition log is an error, never an empty history.
    """
    session_id = hook_input.get(SessionModeIPC.KEY_SESSION_ID)
    if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
        return {"error": f"'{SessionModeIPC.KEY_SESSION_ID}' must name a session when given"}
    limit = hook_input.get(SessionModeIPC.KEY_LIMIT, SessionModeIPC.DEFAULT_HISTORY_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return {"error": f"'{SessionModeIPC.KEY_LIMIT}' must be a positive whole number"}
    try:
        registry = get_data_layer().session_modes
        log = registry.transition_log
        if log is None:
            return {"error": "the session-modes registry has no transition log"}
        snapshot = registry.snapshot()
        transitions = log.recent(limit, session_id=session_id)
    except (RuntimeError, OSError, TransitionLogError) as error:
        log_and_continue(
            logger,
            error,
            reason="mode-history could not be answered; the caller gets the error",
        )
        kind = (
            "transition log unreadable"
            if isinstance(error, TransitionLogError)
            else "session modes unavailable"
        )
        return {"error": f"{kind}: {error}"}
    sessions = {
        sid: [_entry(entry) for entry in entries]
        for sid, entries in snapshot.items()
        if session_id is None or sid == session_id
    }
    return {
        "result": {
            SessionModeIPC.KEY_SESSIONS: sessions,
            SessionModeIPC.KEY_TRANSITIONS: [t.to_record() for t in transitions],
        }
    }


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


def _goals_change(change: GoalsChange) -> dict[str, Any]:
    return {
        SessionModeIPC.KEY_OUTCOME: str(change.outcome),
        SessionModeIPC.KEY_LINE: change.line(),
    }


def _change(change: FocusChange) -> dict[str, Any]:
    return {
        SessionModeIPC.KEY_OUTCOME: str(change.outcome),
        SessionModeIPC.KEY_TASK: change.task,
        SessionModeIPC.KEY_LINE: change.line(),
    }
