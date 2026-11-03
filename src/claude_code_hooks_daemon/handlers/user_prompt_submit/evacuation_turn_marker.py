"""Advance the main thread's turn so evacuation records expire (Plan 00558 Task 4.5).

``evacuation_recorder`` keeps each evacuation for the current turn only; the main
thread's turn is a counter this handler advances at every UserPromptSubmit. Silent
bookkeeping: it never speaks to the model and never denies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.evacuation_turns import advance_turn
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext


class EvacuationTurnMarkerHandler(UserPromptSubmitHandlerBase):
    """Start a new main-thread turn at each prompt."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.EVACUATION_TURN_MARKER,
            priority=Priority.EVACUATION_TURN_MARKER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        self._untracked_override: Path | None = None

    def _untracked(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every prompt of a session that has an id."""
        return bool(hook_input.get(HookInputField.SESSION_ID))

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Advance the turn; always a silent allow."""
        advance_turn(self._untracked(), str(hook_input.get(HookInputField.SESSION_ID)))
        return BlockingResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        """No resident guidance: silent bookkeeping."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One case: an ordinary prompt is untouched (the effect is a file)."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="evacuation turn marker - an ordinary prompt is left alone",
                command="Submit any prompt and verify it is allowed without context.",
                harness_cannot_produce=(
                    "The effect is a counter file under the daemon's untracked directory, "
                    "not the hook's answer, and the harness compares decisions and message "
                    "patterns only. Covered by "
                    "tests/unit/handlers/user_prompt_submit/test_evacuation_turn_marker.py."
                ),
                description=(
                    "The marker advances the session's turn counter and produces no "
                    "context, so the prompt reaches the model unchanged."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Observe-only: writes one small counter file.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
