"""Hello World handler for PostToolUse - confirms hook system is active."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class HelloWorldPostToolUseHandler(Handler):
    """Simple test handler that confirms PostToolUse hook is working.

    Always matches, non-terminal, provides confirmation message to Claude.
    Controlled by global config: daemon.enable_hello_world_handlers
    """

    def __init__(self, priority: int = Priority.HELLO_WORLD) -> None:
        """Initialise handler with low priority to run first."""
        super().__init__(
            handler_id=HandlerID.HELLO_WORLD_POST_TOOL_USE,
            priority=priority,
            terminal=False,  # Allow other handlers to run
            tags=[HandlerTag.TEST, HandlerTag.NON_TERMINAL],
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Always match - this is a universal test handler."""
        return True

    def handle(self, _hook_input: dict[str, Any]) -> HookResult:
        """Return confirmation that PostToolUse hook is active."""
        return HookResult(
            decision=Decision.ALLOW,
            reason=None,
            context=["✅ PostToolUse hook system active"],
            guidance=None,
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for hello world handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="PostToolUse hello world confirmation",
                command='echo "PostToolUse test"',
                description="Handler fires on every tool use to confirm PostToolUse hook is active (advisory context)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"PostToolUse hook system active"],
                safety_notes="Test handler - fires on any tool use, provides confirmation message",
                test_type=TestType.CONTEXT,
            ),
        ]
