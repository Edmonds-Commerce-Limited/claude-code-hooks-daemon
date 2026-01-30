"""Sample handler for acceptance testing."""

from claude_code_hooks_daemon.core import Handler, HookResult


class SampleHandler(Handler):
    """Sample handler for testing."""

    def __init__(self) -> None:
        super().__init__(name="sample-handler", priority=50, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        """Check if handler should process this input."""
        return "sample" in hook_input.get("tool_input", {})

    def handle(self, hook_input: dict) -> HookResult:
        """Process the hook input."""
        return HookResult(decision="deny", reason="Sample handler triggered")
