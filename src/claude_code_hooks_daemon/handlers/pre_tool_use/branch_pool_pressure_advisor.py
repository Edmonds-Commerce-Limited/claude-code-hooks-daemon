"""Say how full the branch pools are on tool calls (Plan 00619 Task 1.3).

The warning ladder (:mod:`core.branch_ladder`) for the PreToolUse event. Warn
and strong pressure is said once per session per pool and level; very strong
pressure (90 percent of the block point by default) is said on EVERY tool call,
with no rate limit, until the pool drops below it. Context only: this handler
never denies, never terminates the chain and changes nothing any guard decides.

It reads the project root's pools (it does not follow ``cd``), through a short
cache so that an every-call advisory costs one reading per few seconds. A
repository that cannot be read gets no line.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.utils.branch_ladder_surface import BranchLadderSurface


class BranchPoolPressureAdvisorHandler(BranchLadderSurface, PreToolUseHandlerBase):
    """Warn on tool calls as a branch pool fills toward the point where creation is refused."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BRANCH_POOL_PRESSURE_ADVISOR,
            priority=Priority.BRANCH_POOL_PRESSURE_ADVISOR,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.GIT,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a pool is at or above its warn level and the notice is due now."""
        return self.ladder_matches(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Allow, with the due ladder lines as context."""
        return GatingResult(decision=Decision.ALLOW, context=list(self._due))

    def get_claude_md(self) -> str | None:
        """No resident guidance: the warning is delivered in full, with its command, at fire time."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """A quiet repository gets no ladder line; the ladder itself is covered by unit tests."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="branch pool pressure advisor never blocks a tool call",
                command="bash -n -c 'echo ok'",
                dispatch_as_bash=True,
                description="The advisor only adds context and always allows",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="bash -n -c only parses the command, never executes it",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
