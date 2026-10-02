"""StopFailureResolverHandler - a later prompt resolves the session's StopFailure (Plan 00470 Task 3.1).

``stop_failure_recorder`` writes down a turn that ended on a rate limit or a
credential error, and the status line shows it until the session moves on. A
session has moved on when it submits another prompt: a human typing, a cron tick
and a resume all arrive as one, and a turn that succeeds always began with one.
If that prompt fails too, the recorder writes a newer failure, which is
unresolved again. See ``utils.stop_failure_records`` for why no successful-Stop
signal is needed as well.

Silent and fails open. It writes only when this session has an unresolved
failure, so an ordinary prompt costs one small file read.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.utils.stop_failure_records import (
    default_records_path,
    resolve_session,
)

logger = logging.getLogger(__name__)


class StopFailureResolverHandler(UserPromptSubmitHandlerBase):
    """Resolve this session's recorded StopFailure when it submits a prompt."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.STOP_FAILURE_RESOLVER,
            priority=Priority.STOP_FAILURE_RESOLVER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )

    def _records_path(self) -> Path | None:
        """Where the records live; None without a project context."""
        return default_records_path()

    def _now(self) -> float:
        return time.time()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every prompt: resolving is a cheap no-op when the session has no failure."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Resolve the session's failures; always ALLOW and silent."""
        path = self._records_path()
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        if path is not None and session_id:
            resolve_session(path, session_id, now=self._now())
        return BlockingResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        """No resident guidance: silent bookkeeping."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One case: an ordinary prompt is untouched (the effect is a file)."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="stop failure resolver - an ordinary prompt is left alone",
                command="Submit any prompt and verify it is allowed without context.",
                harness_cannot_produce=(
                    "The assertion is a file under the daemon's untracked directory, not "
                    "the hook's answer, and the harness compares decisions and message "
                    "patterns only. Covered by "
                    "tests/unit/handlers/user_prompt_submit/test_stop_failure_resolver.py."
                ),
                description=(
                    "The resolver marks the session's recorded StopFailure resolved and "
                    "produces no context, so the prompt reaches the model unchanged."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Observe-only: writes nothing when the session has no failure.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
