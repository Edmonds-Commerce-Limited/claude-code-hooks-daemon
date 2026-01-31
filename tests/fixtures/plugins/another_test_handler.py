"""Another test handler with config support."""

from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class AnotherTestHandler(Handler):
    """Another valid test handler for plugin loading tests."""

    def __init__(self, config=None):
        """Initialise the handler.

        Args:
            config: Optional configuration dictionary
        """
        super().__init__(name="another-test", priority=30)
        self.config = config or {}
        self.test_value = self.config.get("test_value", "default")

    def matches(self, hook_input: dict) -> bool:
        """Check if tool_name is 'test'.

        Args:
            hook_input: Hook input dictionary

        Returns:
            True if tool_name is 'test'
        """
        return hook_input.get("tool_name") == "test"

    def handle(self, hook_input: dict) -> HookResult:
        """Return a test result with config value.

        Args:
            hook_input: Hook input dictionary

        Returns:
            HookResult with allow decision and config value in context
        """
        return HookResult(decision=Decision.ALLOW, context=[f"Another handler: {self.test_value}"])
