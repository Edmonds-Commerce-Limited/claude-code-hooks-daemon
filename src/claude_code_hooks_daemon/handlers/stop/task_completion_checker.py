"""TaskCompletionCheckerHandler - reminds agent to verify task completion."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class TaskCompletionCheckerHandler(Handler):
    """Remind agent to verify task completion before stopping.

    Provides context reminder when agent stops to ensure tasks are properly
    completed. Non-terminal to allow stop to proceed.
    """

    def __init__(self) -> None:
        """Initialise handler as non-terminal reminder."""
        super().__init__(
            handler_id=HandlerID.TASK_COMPLETION_CHECKER,
            priority=Priority.TASK_COMPLETION_CHECKER,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.VALIDATION,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Match all stop events.

        Args:
            _hook_input: Hook input dictionary from Claude Code (unused)

        Returns:
            Always True (remind on all stops)
        """
        return True

    def handle(self, _hook_input: dict[str, Any]) -> HookResult:
        """Provide task completion reminder.

        Args:
            _hook_input: Hook input dictionary from Claude Code (unused)

        Returns:
            HookResult with completion reminder context
        """
        context = """Task Completion Checklist:

Before stopping, ensure:
  ✓ All requested tasks are complete
  ✓ Tests are passing (if code changes were made)
  ✓ Files are saved and committed (if applicable)
  ✓ User has been informed of results
  ✓ Any follow-up items are documented

If any items are incomplete, continue working or inform the user."""

        return HookResult(decision=Decision.ALLOW, context=[context])

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
                title="task completion checker handler test",
                command='echo "test"',
                description="Tests task completion checker handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="Stop event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
