"""Handler missing get_claude_md() - simulates a pre-v2.30.0 project handler.

This fixture intentionally omits get_claude_md() to test that the loader
detects the missing abstract method and emits a version-specific error message.
"""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision


class MissingGetClaudeMdHandler(Handler):
    """Handler that does not implement get_claude_md().

    Simulates a project handler written before v2.30.0 when get_claude_md()
    was not yet an abstract method. Used to test that the loader produces a
    helpful, version-specific error message rather than the generic
    "No Handler subclass found" message.
    """

    def __init__(self) -> None:
        super().__init__(handler_id="missing-get-claude-md", priority=50)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    # get_claude_md() intentionally omitted — breaks after v2.30.0 upgrade

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="test",
                command="echo test",
                description="test",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                test_type=TestType.BLOCKING,
            )
        ]
