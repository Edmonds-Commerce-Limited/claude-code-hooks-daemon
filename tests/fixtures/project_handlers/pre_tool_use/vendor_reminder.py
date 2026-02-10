"""Vendor changes reminder handler for project handler loading tests."""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision


class VendorReminderHandler(Handler):
    """Remind about vendor commit workflow."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="vendor-reminder",
            priority=45,
            terminal=False,
            tags=["project", "vendor"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        tool_input = hook_input.get("toolInput", {})
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        return "vendor/" in command

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(
            decision=Decision.ALLOW,
            context=["VENDOR REMINDER: Commit in vendor dir first"],
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="Vendor reminder triggers",
                command='echo "git add vendor/file.php"',
                description="Advisory reminder for vendor changes",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"VENDOR REMINDER"],
                test_type=TestType.ADVISORY,
            ),
        ]
