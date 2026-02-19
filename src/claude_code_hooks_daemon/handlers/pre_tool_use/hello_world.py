"""Hello World handler for PreToolUse - confirms hook system is active."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class HelloWorldPreToolUseHandler(Handler):
    """Simple test handler that confirms PreToolUse hook is working.

    Always matches, non-terminal, provides confirmation message to Claude.
    Controlled by global config: daemon.enable_hello_world_handlers
    """

    def __init__(self, priority: int = 5) -> None:
        """Initialise handler with low priority to run first."""
        super().__init__(
            handler_id=HandlerID.HELLO_WORLD_PRE_TOOL_USE,
            priority=priority,
            terminal=False,  # Allow other handlers to run
            tags=[HandlerTag.TEST, HandlerTag.NON_TERMINAL],
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Always match - this is a universal test handler."""
        return True

    def handle(self, _hook_input: dict[str, Any]) -> HookResult:
        """Return confirmation that PreToolUse hook is active."""
        return HookResult(
            decision=Decision.ALLOW,
            reason=None,
            context=["✅ PreToolUse hook system active"],
            guidance=None,
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for hello world handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="PreToolUse hello world confirmation",
                command='echo "PreToolUse test"',
                description="Handler fires on every tool use to confirm PreToolUse hook is active (advisory context)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"PreToolUse hook system active"],
                safety_notes="Test handler - fires on any tool use, provides confirmation message",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
