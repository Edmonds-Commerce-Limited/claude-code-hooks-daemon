"""SessionModeIndicatorHandler - this session's active session mode(s) (Plan 00501 Task 4.1).

``| ⚑ focus: write the release note`` or ``| ⚑ awaiting-human +1``

The top mode by precedence (usage-paused > goal-blocked > awaiting-human >
focus > unattended) plus a ``+N`` count of the others; when focus is the top
mode its task is shown, shortened. Nothing is shown when no mode is active.

Sources, all cheap on the render path:

- focus, awaiting-human and goal-blocked from the daemon's in-memory
  session-modes registry (no file read);
- usage-paused from the session's own pause record, through ``MtimeCachedFile``
  (one ``stat()`` per render);
- unattended from the daemon's current mode, held in memory.

A registry or pause record that cannot be read is shown as a named error and
logged at WARNING: an unreadable source is never displayed as "no mode".
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.data_layer import get_data_layer
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation
from claude_code_hooks_daemon.daemon.controller import get_controller
from claude_code_hooks_daemon.handlers.status_line.mtime_cache import MtimeCachedFile
from claude_code_hooks_daemon.utils.session_modes import (
    ModeLabel,
    SessionPolicy,
    UsagePauseView,
    displayed_policy,
)
from claude_code_hooks_daemon.utils.usage_pause import UsagePause, parse_usage_pause, pause_path

logger = logging.getLogger(__name__)

_ICON: Final[str] = "⚑"
_RED: Final[str] = "\033[31m"
_YELLOW: Final[str] = "\033[33m"
_CYAN: Final[str] = "\033[36m"
_GREY: Final[str] = "\033[37m"
_RESET: Final[str] = "\033[0m"

#: The badge colour of each top label.
_COLOURS: Final[dict[ModeLabel, str]] = {
    ModeLabel.USAGE_PAUSED: _RED,
    ModeLabel.GOAL_BLOCKED: _YELLOW,
    ModeLabel.AWAITING_HUMAN: _YELLOW,
    ModeLabel.FOCUS: _CYAN,
    ModeLabel.UNATTENDED: _GREY,
}

#: The longest focus task shown before it is shortened with an ellipsis.
_TASK_SHOWN: Final[int] = 32
_ELLIPSIS: Final[str] = "…"

_REGISTRY_ERROR: Final[str] = "modes unreadable"
_PAUSE_ERROR: Final[str] = "usage-pause record unreadable"


@dataclass(frozen=True, slots=True)
class _Malformed:
    """A pause record that exists but could not be parsed."""

    error: str


def _parse_pause(text: str) -> UsagePause | _Malformed:
    """Total, so ``MtimeCachedFile`` caches the malformed verdict instead of hiding it."""
    try:
        return parse_usage_pause(text)
    except ValueError as error:
        return _Malformed(str(error))


def _shorten(task: str) -> str:
    return task if len(task) <= _TASK_SHOWN else task[: _TASK_SHOWN - 1] + _ELLIPSIS


def _badge(policy: SessionPolicy) -> str:
    """The top label (with the focus task when focus leads) plus ``+N``."""
    top = policy.labels[0]
    text = str(top)
    if top is ModeLabel.FOCUS and policy.focus_task is not None:
        text = f"{text}: {_shorten(policy.focus_task)}"
    extra = len(policy.labels) - 1
    if extra:
        text = f"{text} +{extra}"
    return f"{_COLOURS[top]}{_ICON} {text}{_RESET}"


def _error(text: str) -> str:
    return f"{_RED}{_ICON} {text}{_RESET}"


class SessionModeIndicatorHandler(StatusLineHandlerBase):
    """Render this session's top session mode and how many more are active."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SESSION_MODE_INDICATOR,
            priority=Priority.SESSION_MODE_INDICATOR,
            terminal=False,
            tags=[HandlerTag.STATUSLINE, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )
        self._pauses: MtimeCachedFile[UsagePause | _Malformed | None] = MtimeCachedFile(
            _parse_pause, None
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run; `handle` decides whether there is anything to show."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Render the segment, a named error, or nothing when no mode is active."""
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "").strip()
        if not session_id:
            return AdvisoryResult(context=[])
        try:
            entries = get_data_layer().session_modes.active(session_id)
        except (RuntimeError, OSError) as error:
            logger.warning("session mode segment: the registry could not be read: %s", error)
            return AdvisoryResult(context=[f"| {_error(_REGISTRY_ERROR)}"])
        now = time.time()
        pause = self._read_pause(session_id, now)
        if isinstance(pause, _Malformed):
            logger.warning("session mode segment: usage-pause record unreadable: %s", pause.error)
            return AdvisoryResult(context=[f"| {_error(_PAUSE_ERROR)}"])
        mode = get_controller().get_mode().get(ModeConstant.KEY_MODE)
        policy = displayed_policy(
            session_id,
            entries,
            usage_pause=pause,
            unattended=mode == DaemonMode.UNATTENDED.value,
            now=now,
        )
        if not policy.entries:
            return AdvisoryResult(context=[])
        return AdvisoryResult(context=[f"| {_badge(policy)}"])

    def _read_pause(self, session_id: str, now: float) -> UsagePauseView | _Malformed | None:
        """The session's live usage pause, a malformed record, or None."""
        record = self._pauses.read(pause_path(ProjectContext.daemon_untracked_dir(), session_id))
        if record is None or isinstance(record, _Malformed):
            return record
        if not record.is_live(session_id=session_id, now=now):
            return None
        return UsagePauseView(
            paused_at=record.paused_at, until=record.expires_at, reason=record.reason
        )

    def explain_segment(self) -> SegmentExplanation:
        """Describe this segment (read-only, no I/O)."""
        return SegmentExplanation(
            glyphs=(_ICON,),
            name="Session Mode",
            what_it_is=(
                "This session's active session modes (Plan 00501): conditions that turn "
                "the daemon's work-driving machinery off for one session. Absent when "
                "no mode is active."
            ),
            how_to_read=(
                f"`{_ICON} <mode> +N` shows the top mode by precedence and how many more "
                "are active. Precedence: usage-paused (red: paused on the usage ceiling "
                "until the window resets) > goal-blocked (yellow: a /goal loop was caught) "
                "> awaiting-human (yellow: the agent declared it needs the human) > focus "
                "(cyan, with its task: `hooks-daemon focus off` ends it) > unattended "
                "(grey: the daemon-wide unattended mode). A red "
                f"`{_ICON} {_REGISTRY_ERROR}` or `{_ICON} {_PAUSE_ERROR}` means the mode "
                "state could not be read; see the daemon log. `hooks-daemon session-mode` "
                "lists this session's modes and `hooks-daemon mode-history` every "
                "session's modes and transitions."
            ),
            current_value=(
                "Rendered per session from the session-modes registry, the usage-pause "
                "record and the daemon mode; there is no value outside a status-line render."
            ),
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import Decision, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="session mode segment shows the focus task",
                command='echo "test"',
                description=(
                    "After `hooks-daemon session-mode focus <task>`, the status line "
                    "carries a '⚑ focus: <task>' segment; after `focus off` it is gone."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Display-only status-line segment; reads in-memory state",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            )
        ]
