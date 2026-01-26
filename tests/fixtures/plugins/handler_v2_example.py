"""Handler with version number in name for naming conversion tests."""

from claude_code_hooks_daemon.core import Handler, HookResult


class HandlerV2Example(Handler):
    """Handler with version number in class name."""

    def __init__(self, config=None):
        """Initialise the handler.

        Args:
            config: Optional configuration dictionary
        """
        super().__init__(name="handler-v2", priority=40)
        self.config = config

    def matches(self, hook_input: dict) -> bool:
        """Always matches.

        Args:
            hook_input: Hook input dictionary

        Returns:
            True
        """
        return True

    def handle(self, hook_input: dict) -> HookResult:
        """Return test result.

        Args:
            hook_input: Hook input dictionary

        Returns:
            HookResult with allow decision
        """
        return HookResult(decision="allow", context="Handler V2")
