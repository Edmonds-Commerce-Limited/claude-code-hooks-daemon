"""Hello World handler for SubagentStop - confirms hook system is active."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class HelloWorldSubagentStopHandler(Handler):
    """Simple test handler that confirms SubagentStop hook is working.

    Always matches, non-terminal, provides confirmation message to Claude.
    Controlled by global config: daemon.enable_hello_world_handlers
    """

    def __init__(self, priority: int = Priority.HELLO_WORLD) -> None:
        """Initialise handler with low priority to run first."""
        super().__init__(
            handler_id=HandlerID.HELLO_WORLD_SUBAGENT_STOP,
            priority=priority,
            terminal=False,  # Allow other handlers to run
            tags=[HandlerTag.TEST, HandlerTag.NON_TERMINAL],
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Always match - this is a universal test handler."""
        return True

    def handle(self, _hook_input: dict[str, Any]) -> HookResult:
        """Return confirmation that SubagentStop hook is active."""
        return HookResult(
            decision=Decision.ALLOW,
            reason=None,
            context=["✅ SubagentStop hook system active"],
            guidance=None,
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for hello world handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Hello world test",
                command='echo "test"',
                description="Test handler that confirms SubagentStop hook is active",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"SubagentStop hook system active"],
                safety_notes="Test handler only - always allows with context message",
                test_type=TestType.CONTEXT,
                requires_event="SubagentStop event (cannot be triggered by subagent)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
