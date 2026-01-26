"""TaskCompletionCheckerHandler - reminds agent to verify task completion."""

from typing import Any

from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class TaskCompletionCheckerHandler(Handler):
    """Remind agent to verify task completion before stopping.

    Provides context reminder when agent stops to ensure tasks are properly
    completed. Non-terminal to allow stop to proceed.
    """

    def __init__(self) -> None:
        """Initialise handler as non-terminal reminder."""
        super().__init__(name="task-completion-checker", priority=50, terminal=False)

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
