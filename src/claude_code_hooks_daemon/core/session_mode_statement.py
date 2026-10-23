"""The one line that states a session's pending mode news at its next prompt (Plan 00501 Task 4.2).

The registry queues one-time notices (an expiry; after a daemon restart, each
mode that survived it or was cleared by it; and, through
:meth:`SessionModeRegistry.queue_notice`, the goal-loop detector's entry with
whether its goal clear was signalled) and hands each out once
(:meth:`SessionModeRegistry.take_notices` is pop-once), plus one-time lines with
no mode entry behind them (:meth:`SessionModeRegistry.take_lines`, e.g. the
goal-clear attribution's "clear again" line, Task 8.2). This module is their
only reader: ``focus_mode_trigger`` calls it on every prompt that reaches it,
command or not, so the news is stated whatever the prompt is. A usage-paused
session's prompts are denied before they reach the trigger, so
``usage_pause_gate`` calls it on the one prompt it lets through while the pause
continues (the still-over resume tick), passing the record from before that
tick.

After a restart the line also restates what the registry does not own: a usage
pause recorded before the restart (checked once per session, at its first
prompt since the registry loaded), and the daemon-wide ``unattended`` mode
whenever the line reports a restart at all. Those sources are read lazily, so
an ordinary prompt reads neither.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final

from claude_code_hooks_daemon.core.session_mode_registry import NoticeKind, SessionModeRegistry
from claude_code_hooks_daemon.utils.session_modes import UsagePauseView

_RESTART_KINDS: Final[frozenset[NoticeKind]] = frozenset(
    {NoticeKind.SURVIVED_RESTART, NoticeKind.CLEARED_BY_RESTART}
)

_PREFIX: Final[str] = "SESSION MODE: "
_UNATTENDED: Final[str] = "the daemon is in unattended mode"


def _clock_text(epoch: float) -> str:
    return time.strftime("%H:%M UTC", time.gmtime(epoch))


def pending_mode_statement(
    registry: SessionModeRegistry,
    session_id: str,
    *,
    usage_pause: Callable[[], UsagePauseView | None],
    unattended: Callable[[], bool],
) -> str | None:
    """Take ``session_id``'s pending notices and state them, with the restart extras, in one line.

    Args:
        registry: The session-modes registry (its notices are consumed here).
        session_id: The prompting session.
        usage_pause: Reads the session's live usage pause; called at most once
            per session, at its first prompt since the registry loaded.
        unattended: Reads whether the daemon is in unattended mode; called only
            when the line reports a restart.

    Returns:
        The line, or None when there is nothing to state.

    Raises:
        RuntimeError: the registry has not loaded.
    """
    notices = registry.take_notices(session_id)
    parts = [notice.text() for notice in notices]
    restarted = any(notice.kind in _RESTART_KINDS for notice in notices)
    if registry.claim_first_prompt(session_id):
        pause = usage_pause()
        if pause is not None and pause.paused_at < registry.loaded_at:
            parts.append(
                f"usage-paused ({pause.reason}) survived a daemon restart and still applies "
                f"until {_clock_text(pause.until)}"
            )
            restarted = True
    if restarted and unattended():
        parts.append(_UNATTENDED)
    parts.extend(registry.take_lines(session_id))
    if not parts:
        return None
    return f"{_PREFIX}{'; '.join(parts)}."
