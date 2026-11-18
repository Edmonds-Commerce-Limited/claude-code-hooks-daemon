"""Say how full the branch pools are on every prompt (Plan 00619 Task 1.3).

The warning ladder (:mod:`core.branch_ladder`) for the UserPromptSubmit event: the
twin of the PreToolUse advisor. Very strong pressure is said on EVERY prompt, with
no rate limit, until the pool drops below it; warn and strong once per session per
pool and level (the throttle is shared with the advisor, so one warning is not said
twice). Context only: it never denies and never holds a prompt.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.branch_ladder import (
    PRESSURE_CACHE,
    SESSION_THROTTLE,
    LadderThrottle,
    PressureCache,
    ladder_notice,
)
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext

logger = logging.getLogger(__name__)


class BranchPoolPressurePromptHandler(UserPromptSubmitHandlerBase):
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
        self._branches: BranchesConfig = BranchesConfig()
        self._project_root_override: Path | None = None
        self._throttle: LadderThrottle = SESSION_THROTTLE
        self._cache: PressureCache = PRESSURE_CACHE
        self._due: list[str] = []

    def _project_root(self) -> Path:
        if self._project_root_override is not None:
            return self._project_root_override
        try:
            return ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; reading branch pools from cwd")
            return Path.cwd()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a pool is at or above its warn level and the notice is due now."""
        session = hook_input.get(HookInputField.SESSION_ID)
        self._due = ladder_notice(
            self._project_root(),
            self._branches,
            session_id=session if isinstance(session, str) else None,
            throttle=self._throttle,
            cache=self._cache,
        )
        return bool(self._due)

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
