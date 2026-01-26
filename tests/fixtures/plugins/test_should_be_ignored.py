"""Test file that should be ignored by plugin discovery (starts with 'test_')."""

from claude_code_hooks_daemon.core import Handler, HookResult


class TestShouldBeIgnored(Handler):
    """This handler should be ignored during discovery."""

    def __init__(self, config=None):
        """Initialise."""
        super().__init__(name="should-be-ignored", priority=50)

    def matches(self, hook_input: dict) -> bool:
        """Match."""
        return True

    def handle(self, hook_input: dict) -> HookResult:
        """Handle."""
        return HookResult(decision="deny", reason="This should never be loaded")
