"""Handler that raises error in __init__."""

from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class InitErrorHandler(Handler):
    """Handler that fails during initialisation."""

    def __init__(self, config=None):
        """Initialise the handler - raises error.

        Args:
            config: Optional configuration dictionary

        Raises:
            ValueError: Always raised for testing
        """
        raise ValueError("Intentional initialisation error for testing")

    def matches(self, hook_input: dict) -> bool:
        """Check match.

        Args:
            hook_input: Hook input dictionary

        Returns:
            True
        """
        return True

    def handle(self, hook_input: dict) -> HookResult:
        """Handle input.

        Args:
            hook_input: Hook input dictionary

        Returns:
            HookResult
        """
        return HookResult(decision=Decision.ALLOW)
