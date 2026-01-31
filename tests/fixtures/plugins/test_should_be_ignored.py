"""Test file that should be ignored by plugin discovery (starts with 'test_')."""

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class TestShouldBeIgnored(Handler):
    """This handler should be ignored during discovery."""

    def __init__(self, config=None):
        """Initialise."""
        super().__init__(name="should-be-ignored", priority=Priority.HELLO_WORLD)

    def matches(self, hook_input: dict) -> bool:
        """Match."""
        return True

    def handle(self, hook_input: dict) -> HookResult:
        """Handle."""
        return HookResult(decision=Decision.DENY, reason="This should never be loaded")
