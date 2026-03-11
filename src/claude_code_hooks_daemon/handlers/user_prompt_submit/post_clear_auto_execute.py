"""PostClearAutoExecuteHandler - auto-execute instructions after /clear.

PROTOTYPE: Testing whether injecting guidance on the first prompt of a new
session can solve the "/clear <instruction>" idle agent problem.

When users run `/clear execute plan 85`, the session clears and the text
appears as a submitted message, but the agent often sits idle instead of
executing. This handler detects the first prompt of a new session and
injects strong guidance to execute it immediately.
"""

from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

# Handler identity
_HANDLER_ID: Final[str] = "post_clear_auto_execute"
_HANDLER_PRIORITY: Final[int] = (
    Priority.CRITICAL_THINKING_ADVISORY - 1
)  # Fire before critical thinking

# Guidance message injected on first prompt of a new session
_GUIDANCE_MESSAGE: Final[str] = (
    "POST-CLEAR INSTRUCTION DETECTED: The user has just started a fresh session"
    " (likely after /clear) and provided a direct instruction as their first message."
    " This is a common workflow pattern - the user expects you to execute the"
    " instruction immediately without asking for clarification or acknowledgement."
    " Proceed directly with the task described in their message."
)


class PostClearAutoExecuteHandler(Handler):
    """Inject execution guidance on the first prompt of a new session.

    Tracks session_id to detect when a new session starts. On the first
    UserPromptSubmit of each session, injects guidance telling the agent
    to execute the instruction immediately.

    Only fires once per session (first prompt only).
    """

    def __init__(self) -> None:
        """Initialise handler."""
        super().__init__(
            handler_id=_HANDLER_ID,
            priority=_HANDLER_PRIORITY,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        self._last_session_id: str | None = None
        self._fired_for_session: bool = False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match only the first prompt of a new session.

        Detects new sessions by tracking session_id changes.

        Args:
            hook_input: Hook input with 'session_id' and 'prompt' fields.

        Returns:
            True if this is the first prompt of a new/different session.
        """
        session_id = hook_input.get("session_id", "")
        if not session_id:
            return False

        # New session detected
        if session_id != self._last_session_id:
            return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Inject guidance to execute the instruction immediately.

        Args:
            hook_input: Hook input dictionary.

        Returns:
            HookResult with ALLOW and guidance context.
        """
        session_id = hook_input.get("session_id", "")
        self._last_session_id = session_id
        self._fired_for_session = True

        return HookResult(
            decision=Decision.ALLOW,
            context=[_GUIDANCE_MESSAGE],
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Post-clear auto-execute injects guidance on first prompt",
                command='echo "test"',
                description=(
                    "PROTOTYPE: Detects first prompt of new session and injects"
                    " guidance to execute it immediately. Test by running /clear"
                    " followed by an instruction and verifying the agent acts on it."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"POST-CLEAR INSTRUCTION DETECTED"],
                safety_notes="Advisory only - never blocks.",
                test_type=TestType.CONTEXT,
                requires_event="UserPromptSubmit event (first prompt of session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
