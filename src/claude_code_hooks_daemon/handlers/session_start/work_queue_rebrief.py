"""WorkQueueRebriefHandler - re-brief the durable work queue on resume or compact (Plan 00470 Task 3.3).

A resumed or compacted session has lost, from its context, which agents it
dispatched; a usage-limit restart or a user interrupt may also have killed them.
The work queue (``utils/work_queue.py``) is the durable record, written by the
coordinator through ``hooks-daemon work-queue``. This handler lists what it still
records as ``running``, with the worktree, branch, brief and last sha a respawn
needs, and says plainly that it respawns nothing: whether to re-dispatch an agent
is the coordinator's call.

``limit_rebrief`` (UserPromptSubmit) lists the same queue after a usage-limit
resume, from the same ``queue_briefing``, so the two can never disagree about what
the queue holds.

Silent on a new session (``startup``/``clear``), and when the queue is missing or
has no running record. An UNREADABLE queue speaks, because silence would hide the
lost agents. Never denies.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.utils.work_queue import default_queue_path, queue_briefing

_SOURCE_FIELD: Final[str] = "source"

#: The SessionStart sources that continue an earlier conversation.
_CONTINUING_SOURCES: Final[frozenset[str]] = frozenset({"resume", "compact"})


class WorkQueueRebriefHandler(SessionStartHandlerBase):
    """List the agents the durable work queue records as still running."""

    def __init__(self) -> None:
        """Initialise as a non-terminal advisory."""
        super().__init__(
            handler_id=HandlerID.WORK_QUEUE_REBRIEF,
            priority=Priority.WORK_QUEUE_REBRIEF,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )

    def get_default_enabled(self) -> bool:
        """On by default: silent unless a queue exists and something is running."""
        return True

    def _queue_path(self) -> Path | None:
        """Where the durable work queue lives; None without a project context."""
        return default_queue_path()

    def _now(self) -> float:
        return time.time()

    def _briefing(self) -> list[str]:
        return queue_briefing(self._queue_path(), now=self._now())

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A resumed or compacted session, with something in the queue to say."""
        if hook_input.get(_SOURCE_FIELD) not in _CONTINUING_SOURCES:
            return False
        return bool(self._briefing())

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """List the running agents with their respawn facts; always ALLOW."""
        return AdvisoryResult(decision=Decision.ALLOW, context=self._briefing())

    def get_claude_md(self) -> str | None:
        """No resident guidance: never denies, and the message is delivered in full at fire time."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One case: the trigger is a resumed or compacted session, which the harness cannot start."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="work queue rebrief lists the agents a resumed session had dispatched",
                command=(
                    "Record an agent with `bin/hooks-daemon work-queue add`, then resume or "
                    "compact the session and verify a WORK QUEUE advisory naming it is injected."
                ),
                harness_cannot_produce=(
                    "The trigger is a SessionStart whose source is resume or compact; an agent "
                    "under test cannot start one for its own session. Covered by "
                    "tests/unit/handlers/session_start/test_work_queue_rebrief.py."
                ),
                description=(
                    "A resumed or compacted session whose work queue records a running agent "
                    "is told its worktree, branch, brief and last sha, and that nothing is "
                    "respawned for it."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"WORK QUEUE", r"not respawned"],
                safety_notes="Advisory only; reads one file in the daemon's untracked dir.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
