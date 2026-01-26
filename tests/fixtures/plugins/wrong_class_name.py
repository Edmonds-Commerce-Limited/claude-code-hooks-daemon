"""Handler with wrong class name (doesn't match snake_to_pascal conversion)."""

from claude_code_hooks_daemon.core import Handler, HookResult


class WrongName(Handler):
    """Class name doesn't match file name conversion."""

    def __init__(self, config=None):
        """Initialise."""
        super().__init__(name="wrong", priority=50)

    def matches(self, hook_input: dict) -> bool:
        """Match."""
        return True

    def handle(self, hook_input: dict) -> HookResult:
        """Handle."""
        return HookResult(decision="allow")
