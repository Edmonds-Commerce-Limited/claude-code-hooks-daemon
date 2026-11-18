"""Say how full the branch pools are on every prompt (Plan 00619 Task 1.3).

The warning ladder (:mod:`core.branch_ladder`) for the UserPromptSubmit event: the
twin of the PreToolUse advisor. Very strong pressure is said on EVERY prompt, with
no rate limit, until the pool drops below it; warn and strong once per session per
pool and level (the throttle is shared with the advisor, so one warning is not said
twice). Context only: it never denies and never holds a prompt.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.handlers.utils.branch_ladder_surface import BranchLadderSurface


class BranchPoolPressurePromptHandler(BranchLadderSurface, UserPromptSubmitHandlerBase):
    """Warn on prompts as a branch pool fills toward the point where creation is refused."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BRANCH_POOL_PRESSURE_PROMPT,
            priority=Priority.BRANCH_POOL_PRESSURE_PROMPT,
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

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Allow the prompt, with the due ladder lines as context."""
        return BlockingResult(decision=Decision.ALLOW, context=list(self._due))

    def get_claude_md(self) -> str | None:
        """Covered by the guidance of ``branch_pool_pressure_advisor``, its PreToolUse twin."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """The trigger is pool fullness, which the harness cannot arrange safely."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="branch pool pressure prompt never holds a prompt",
                command="Send any prompt while a branch pool is at 90 percent of its block point.",
                harness_cannot_produce=(
                    "Filling a branch pool to 90 percent needs real branches in the repository "
                    "under test. Covered by "
                    "tests/unit/handlers/user_prompt_submit/test_branch_pool_pressure_prompt.py."
                ),
                description="At 90 percent of a pool's block point every prompt carries the "
                "very strong ladder warning; the prompt is never held.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"BRANCH POOL"],
                safety_notes="Advisory only; reads branch refs, changes nothing",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
