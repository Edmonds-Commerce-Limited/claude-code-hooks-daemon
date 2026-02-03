"""Blocking handler for E2E smoke testing."""

from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class BlockingTestHandler(Handler):
    """A test handler that blocks specific patterns."""

    def __init__(self, config=None):
        """Initialise the blocking test handler.

        Args:
            config: Optional configuration dictionary
        """
        super().__init__(name="blocking-test", priority=10, terminal=True)
        self.config = config or {}

    def matches(self, hook_input: dict) -> bool:
        """Match commands containing 'BLOCK_THIS'.

        Args:
            hook_input: Hook input dictionary

        Returns:
            True if command contains BLOCK_THIS
        """
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command", "")
        return "BLOCK_THIS" in command

    def handle(self, hook_input: dict) -> HookResult:
        """Block the command.

        Args:
            hook_input: Hook input dictionary

        Returns:
            HookResult with deny decision
        """
        return HookResult(
            decision=Decision.DENY,
            reason="🚫 Blocked by E2E smoke test plugin",
            context=["Plugin successfully blocked through daemon socket"],
        )

    def get_acceptance_tests(self) -> list:
        """Test handler - stub implementation."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="blocking test handler",
                command="bash -c 'echo BLOCK_THIS'",
                description="Blocking handler for E2E smoke tests",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Blocked by E2E smoke test"],
                test_type=TestType.BLOCKING,
            )
        ]
