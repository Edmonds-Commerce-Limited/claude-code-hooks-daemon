"""Hello World handler for PreCompact - confirms hook system is active."""

from typing import Any

from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class HelloWorldPreCompactHandler(Handler):
    """Simple test handler that confirms PreCompact hook is working.

    Always matches, non-terminal, provides confirmation message to Claude.
    Controlled by global config: daemon.enable_hello_world_handlers
    """

    def __init__(self, priority: int = 5) -> None:
        """Initialise handler with low priority to run first."""
        super().__init__(
            name="hello_world",
            priority=priority,
            terminal=False,  # Allow other handlers to run
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Always match - this is a universal test handler."""
        return True

    def handle(self, _hook_input: dict[str, Any]) -> HookResult:
        """Return confirmation that PreCompact hook is active."""
        return HookResult(
            decision=Decision.ALLOW,
            reason=None,
            context=["✅ PreCompact hook system active"],
            guidance=None,
        )
