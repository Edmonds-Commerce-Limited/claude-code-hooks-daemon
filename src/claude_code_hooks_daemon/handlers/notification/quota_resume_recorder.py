"""QuotaResumeRecorderHandler - write down how a usage-limit wait ended (Plan 00470 Task 3.2).

Claude Code sends a ``Notification`` with ``notification_type`` ``quota_auto_resume_fired``
when it continues the task a usage limit paused, ``quota_auto_resume_stale`` when the
limit reset while the machine slept and it waits for Enter, and
``quota_auto_resume_disabled`` when it ends the wait without continuing
(``remote-docs/code.claude.com/docs/en/hooks.md``, "Notification"). A Notification
hook cannot block or inject context: ``systemMessage`` and ``continue`` are
discarded. So this handler only records the event in ``utils.limit_events``;
``limit_rebrief`` (UserPromptSubmit) delivers the re-brief at the session's next
prompt, which is the first point the daemon can speak to the model again.

Silent bookkeeping that fails open. The notification's own text is not stored:
the type says what happened.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.handler_bases import NotificationHandlerBase
from claude_code_hooks_daemon.utils.limit_events import (
    RESUME_KINDS,
    LimitEvent,
    default_events_path,
    record_event,
)

logger = logging.getLogger(__name__)


class QuotaResumeRecorderHandler(NotificationHandlerBase):
    """Record each ``quota_auto_resume_*`` notification, silently."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.QUOTA_RESUME_RECORDER,
            priority=Priority.QUOTA_RESUME_RECORDER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )

    def _events_path(self) -> Path | None:
        """Where the events live; None without a project context."""
        return default_events_path()

    def _now(self) -> float:
        return time.time()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for the three documented ``quota_auto_resume_*`` notification types."""
        return hook_input.get(HookInputField.NOTIFICATION_TYPE) in RESUME_KINDS

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Record the event against its session; always an empty answer."""
        path = self._events_path()
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        if path is None or not session_id:
            logger.debug("quota_resume_recorder: no project context or session id, not recording")
            return AdvisoryResult()
        record_event(
            path,
            LimitEvent(
                session_id=session_id,
                kind=str(hook_input[HookInputField.NOTIFICATION_TYPE]),
                recorded_at=self._now(),
            ),
        )
        return AdvisoryResult()

    def get_claude_md(self) -> str | None:
        """No resident guidance: silent, and the re-brief it feeds is delivered at fire time."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One case: a recorded event is a file, which the harness cannot assert on."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="quota_resume_recorder records a usage-limit resume notification",
                command=(
                    "Trigger a Notification (quota_auto_resume_fired) and verify the hook answers {}."
                ),
                harness_cannot_produce=(
                    "The quota_auto_resume_* notifications fire only when a usage limit "
                    "pauses and releases a real session, and the assertion is a file under "
                    "the daemon's untracked directory, not the hook's answer; the harness "
                    "compares decisions and message patterns only. Covered by "
                    "tests/unit/handlers/notification/test_quota_resume_recorder.py."
                ),
                description=(
                    "A Notification of type quota_auto_resume_fired, quota_auto_resume_stale "
                    "or quota_auto_resume_disabled is written to the daemon's untracked "
                    "limit-events.json; every other type is ignored. Always a clean {}."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Observe-only: writes one record to the daemon's untracked dir.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
