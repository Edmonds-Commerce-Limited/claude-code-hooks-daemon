"""Handler with version number in name for naming conversion tests."""

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class HandlerV2Example(Handler):
    """Handler with version number in class name."""

    def __init__(self, config=None):
        """Initialise the handler.

        Args:
            config: Optional configuration dictionary
        """
        super().__init__(name="handler-v2", priority=Priority.GH_ISSUE_COMMENTS)
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
        return HookResult(decision=Decision.ALLOW, context="Handler V2")

    def get_acceptance_tests(self) -> list:
        """Test handler - stub implementation."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="handler v2",
                command="echo 'test'",
                description="Handler V2 for plugin tests",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                test_type=TestType.BLOCKING,
            )
        ]
