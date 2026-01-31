"""Custom handler for plugin loading tests."""

from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class CustomHandler(Handler):
    """A valid custom handler for plugin loading tests."""

    def __init__(self, config=None):
        """Initialise the test custom handler.

        Args:
            config: Optional configuration dictionary
        """
        super().__init__(name="test-custom", priority=50)
        self.config = config

    def matches(self, hook_input: dict) -> bool:
        """Always matches for testing.

        Args:
            hook_input: Hook input dictionary

        Returns:
            True
        """
        return True

    def handle(self, hook_input: dict) -> HookResult:
        """Return a test result.

        Args:
            hook_input: Hook input dictionary

        Returns:
            HookResult with allow decision
        """
        return HookResult(decision=Decision.ALLOW, context="Test custom handler")
