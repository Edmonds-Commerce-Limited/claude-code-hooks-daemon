"""Handler without acceptance tests - for testing validation."""

from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class NoAcceptanceTestsHandler(Handler):
    """Handler that violates requirement by returning empty acceptance test list."""

    def __init__(self, config=None):
        """Initialise the handler.

        Args:
            config: Optional configuration dictionary
        """
        super().__init__(name="no-acceptance-tests", priority=50)
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
        return HookResult(decision=Decision.ALLOW, context="Test handler")

    def get_acceptance_tests(self) -> list:
        """Return empty list - VIOLATES REQUIREMENT."""
        return []
