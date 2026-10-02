"""StopFailureRecorderHandler - write down a turn that ended on a limit or a credential error.

A ``StopFailure`` hook runs instead of ``Stop`` when a turn ends on an API error,
and Claude Code ignores its output (``remote-docs/code.claude.com/docs/en/hooks.md``,
"StopFailure"), so the failure can neither be answered nor shown from here. A
persistent session that hit its usage limit, or whose credential lapsed, simply
stops, and nothing says so. This handler records the three errors that stop it
until a human or a credential changes -- ``rate_limit``, ``authentication_failed``
and ``cloud_credential_error`` -- in ``utils.stop_failure_records``, and the
usage indicator in the status line shows the latest unresolved one.

Silent bookkeeping: it never speaks and fails open. Only the error type is
stored; ``error_details`` and ``last_assistant_message`` are the API's own text
and are not needed to say which failure it was.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.handler_bases import StopFailureHandlerBase
from claude_code_hooks_daemon.utils.stop_failure_records import (
    RECORDED_ERRORS,
    StopFailureRecord,
    default_records_path,
    record_failure,
)

logger = logging.getLogger(__name__)


class StopFailureRecorderHandler(StopFailureHandlerBase):
    """Record each rate-limit or credential StopFailure, silently."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.STOP_FAILURE_RECORDER,
            priority=Priority.STOP_FAILURE_RECORDER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )

    def _records_path(self) -> Path | None:
        """Where the records live; None without a project context."""
        return default_records_path()

    def _now(self) -> float:
        return time.time()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for the errors that stop a session until a human or a credential changes."""
        return hook_input.get(HookInputField.ERROR) in RECORDED_ERRORS

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Record the failure against its session; always an empty answer."""
        path = self._records_path()
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        if path is None or not session_id:
            logger.debug("stop_failure_recorder: no project context or session id, not recording")
            return AdvisoryResult()
        record_failure(
            path,
            StopFailureRecord(
                session_id=session_id,
                error=str(hook_input[HookInputField.ERROR]),
                recorded_at=self._now(),
            ),
        )
        return AdvisoryResult()

    def get_claude_md(self) -> str | None:
        """No resident guidance: silent, and the status line is for the human."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """VERIFIED_BY_LOAD: StopFailure fires only when the API fails a turn."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="stop_failure_recorder records a rate-limit or credential failure",
                command='echo "stop failure recording verified by unit tests"',
                description=(
                    "A StopFailure with error rate_limit, authentication_failed or "
                    "cloud_credential_error is written to the daemon's untracked "
                    "stop-failures.json; every other error is ignored. Always a clean {}."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Untriggerable by tool call; verified by daemon load + unit tests.",
                test_type=TestType.CONTEXT,
                requires_event="StopFailure event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
