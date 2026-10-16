"""BackgroundTaskRecorderHandler - keep the live-agent count honest (Plan 00471 L4).

``background_tasks[]`` is the one list Claude Code gives of the agents it is
still running, and it reaches only Stop and SubagentStop. This sensor records
which subagent and teammate tasks a Stop reports as no longer running, so the
live count (``utils.session_load``) stops counting them however recently their
transcripts moved. ``subagent_cache_aggregator`` does the same at SubagentStop.

A sensor on a blocking event: it never blocks, and a record that cannot be
written costs only accuracy of an advisory.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import StopHandlerBase
from claude_code_hooks_daemon.daemon.synthetic_traffic import is_synthetic_event
from claude_code_hooks_daemon.utils.session_load import (
    record_background_tasks,
    refresh_live_snapshot,
)

logger = logging.getLogger(__name__)


class BackgroundTaskRecorderHandler(StopHandlerBase):
    """Record a Stop's finished agent tasks for the live count; always allow."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BACKGROUND_TASK_RECORDER,
            priority=Priority.BACKGROUND_TASK_RECORDER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )
        self._untracked_override: Path | None = None

    def _untracked_dir(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A real Stop that carries the list (absent means unknown, not empty)."""
        if is_synthetic_event(hook_input):
            return False
        return isinstance(hook_input.get(HookInputField.BACKGROUND_TASKS), list)

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Record the finished tasks and refresh the live snapshot, then ALLOW unconditionally.

        The coordinator stops at the end of every turn, so this is what keeps the
        status segment's live count current between spawns.
        """
        untracked = self._untracked_dir()
        session = str(hook_input.get(HookInputField.SESSION_ID) or "")
        record_background_tasks(untracked, session, hook_input.get(HookInputField.BACKGROUND_TASKS))
        refresh_live_snapshot(
            untracked, session, str(hook_input.get(HookInputField.TRANSCRIPT_PATH) or "")
        )
        return BlockingResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        """Silent sensor: nothing an agent acts on."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One probe: a Stop with background tasks is allowed and says nothing."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="background task recorder - a Stop is recorded silently",
                command='echo "stop with background_tasks"',
                description=(
                    "Sensor only: records finished agent tasks for the live count and "
                    "always allows. The record is asserted by "
                    "tests/unit/handlers/stop/test_background_task_recorder.py."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Writes one small file under the daemon untracked dir.",
                test_type=TestType.CONTEXT,
                requires_event="Stop event",
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=True,
            )
        ]
