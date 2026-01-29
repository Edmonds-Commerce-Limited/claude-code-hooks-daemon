"""Hello World handler for Stop - confirms hook system is active."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class HelloWorldStopHandler(Handler):
    """Simple test handler that confirms Stop hook is working.

    Always matches, non-terminal, provides confirmation message to Claude.
    Controlled by global config: daemon.enable_hello_world_handlers
    """

    def __init__(self, priority: int = Priority.HELLO_WORLD) -> None:
        """Initialise handler with low priority to run first."""
        super().__init__(
            handler_id=HandlerID.HELLO_WORLD_STOP,
            priority=priority,
            terminal=False,  # Allow other handlers to run
            tags=[HandlerTag.TEST, HandlerTag.NON_TERMINAL],
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Always match - this is a universal test handler."""
        return True

    def handle(self, _hook_input: dict[str, Any]) -> HookResult:
        """Return confirmation that Stop hook is active."""
        return HookResult(
            decision=Decision.ALLOW,
            reason=None,
            context=["✅ Stop hook system active"],
            guidance=None,
        )
