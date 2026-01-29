"""Hello World handler for SessionStart - confirms hook system is active."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class HelloWorldSessionStartHandler(Handler):
    """Simple test handler that confirms SessionStart hook is working.

    Always matches, non-terminal, provides confirmation message to Claude.
    Controlled by global config: daemon.enable_hello_world_handlers
    """

    def __init__(self, priority: int = Priority.HELLO_WORLD) -> None:
        """Initialise handler with low priority to run first."""
        super().__init__(
            name="hello_world",
            priority=priority,
            terminal=False,  # Allow other handlers to run
            tags=[HandlerTag.TEST, HandlerTag.NON_TERMINAL],
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Always match - this is a universal test handler."""
        return True

    def handle(self, _hook_input: dict[str, Any]) -> HookResult:
        """Return confirmation that SessionStart hook is active."""
        return HookResult(
            decision=Decision.ALLOW,
            reason=None,
            context=["✅ SessionStart hook system active"],
            guidance=None,
        )
