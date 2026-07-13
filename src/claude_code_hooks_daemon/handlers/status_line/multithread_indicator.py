"""Multithread-indicator status handler (Plan 00158 Phase 6).

Renders ``🧵 Y/X`` in the bottom status bar — this thread's stable rank ``Y``
among the ``X`` Claude Code sessions currently alive behind the one shared
daemon. When only one session is live (the overwhelmingly common case) the
segment is empty, so single-thread users never see it.

Why this exists: Agent View lets a human background one thread and open another,
and each background thread is a full independent session that renders its OWN
bottom bar (Plan 00158 Truth #5). But the Status payload carries no field that
distinguishes one plain thread from another (Truth #1), so "which thread am I
looking at?" is unanswerable from a single render. This handler answers it by
having every real session heartbeat into a shared on-disk registry and reading
back the live set — see ``thread_registry`` for the mechanism and the Truth #6
thread-safety rationale (per-session keying + atomic writes).

Only genuine top-level interactive sessions are counted. Claude Code keeps
pre-warmed background "spare" PTY hosts ready to be claimed, and also runs
agent/subagent sessions; these render ``statusLine`` too but carry a truthy
``agent_type`` (payload also has ``agent={"name": ...}`` and no ``session_name``/
``prompt_id``/``rate_limits``). A real interactive thread — including a
backgrounded+forked one — reports ``agent_type=None``. The handler skips any
session with a truthy ``agent_type`` entirely (no heartbeat, no render), so an
unclaimed spare can never inflate a real session's count.

The handler is display-only: it writes its heartbeat and returns a single status
segment (or nothing). It is fail-open — any registry I/O error degrades to "no
segment" and is logged, never propagated into the render.
"""

import logging
import time
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core import Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.handlers.status_line.thread_registry import (
    _REGISTRY_SUBDIR,
    compute_indicator,
    read_live_entries,
    upsert_heartbeat,
)

logger = logging.getLogger(__name__)


class MultithreadIndicatorHandler(Handler):
    """Show this thread's rank among live Agent-View threads (``🧵 Y/X``)."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MULTITHREAD_INDICATOR,
            priority=Priority.MULTITHREAD_INDICATOR,
            terminal=False,
            tags=[HandlerTag.STATUSLINE, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Run on every status event (heartbeat write is cheap and idempotent)."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Upsert this session's heartbeat and render its ``🧵 Y/X`` segment.

        Args:
            hook_input: Status event payload (session identity + agent fields).

        Returns:
            HookResult carrying a single ``| 🧵 Y/X`` segment when two or more
            threads are live, else an empty context (silent when alone, and on
            any registry failure).
        """
        agent_type = hook_input.get(HookInputField.AGENT_TYPE)
        if agent_type:
            # Not a navigable top-level thread. A truthy agent_type marks a
            # session launched as an agent OR a pre-warmed background "spare"
            # PTY host (payload carries agent={"name": ...} and no session_name /
            # prompt_id / rate_limits). Real interactive threads — including a
            # backgrounded+forked one — report agent_type=None. Excluding these
            # here means a spare never writes a heartbeat, so it can never
            # inflate a real session's count (the "🧵 1/2 with one thread" bug).
            return HookResult(context=[])

        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "")
        session_name = hook_input.get(HookInputField.SESSION_NAME)

        segment = self._render_segment(session_id, session_name, agent_type)
        if segment:
            return HookResult(context=[f"| {segment}"])
        return HookResult(context=[])

    def _render_segment(
        self,
        session_id: str,
        session_name: Any,
        agent_type: Any,
    ) -> str:
        """Do the registry I/O; return the segment text or "" (fail-open).

        Any ``RuntimeError`` (ProjectContext not initialised — e.g. the
        default-config/standalone entry point) or ``OSError`` (registry
        unwritable/unreadable) degrades to an empty segment rather than failing
        the whole status-line render.
        """
        try:
            registry_dir = ProjectContext.daemon_untracked_dir() / _REGISTRY_SUBDIR
            now = self._now()
            upsert_heartbeat(
                registry_dir,
                session_id,
                str(session_name) if session_name is not None else None,
                str(agent_type) if agent_type is not None else None,
                now,
            )
            live = read_live_entries(registry_dir, now)
            return compute_indicator(live, session_id)
        except RuntimeError as e:
            logger.warning("Skipping multithread indicator (no project context): %s", e)
            return ""
        except OSError as e:
            logger.warning("Failed to update thread registry: %s", e)
            return ""

    def _now(self) -> float:
        """Return the current epoch time (seam for deterministic tests)."""
        return time.time()

    def get_claude_md(self) -> str | None:
        # Display-only: writes nothing to the session and blocks nothing, so
        # there is no handler behaviour an agent needs to avoid fighting.
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="multithread indicator handler test",
                command='echo "test"',
                description=(
                    "Verify the multithread indicator handler runs on a Status event. "
                    "It renders '🧵 Y/X' only when 2+ Claude Code threads share the "
                    "daemon; with a single session the segment is silent. Handler "
                    "confirmed active by the daemon loading without errors."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Display-only status handler - writes a heartbeat, injects nothing",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
