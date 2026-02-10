"""Build asset checker handler for project handler loading tests."""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision


class BuildCheckerHandler(Handler):
    """Remind to rebuild assets after TS/SCSS changes."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="build-checker",
            priority=50,
            terminal=False,
            tags=["project", "build"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        tool_input = hook_input.get("tool_input", {})
        file_path = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""
        return ".ts" in file_path or ".scss" in file_path

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(
            decision=Decision.ALLOW,
            context=["BUILD REMINDER: Run yarn build after TS/SCSS changes"],
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="Build checker triggers on TS file",
                command='echo "Write to file.ts"',
                description="Advisory reminder for build assets",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"BUILD REMINDER"],
                test_type=TestType.ADVISORY,
            ),
        ]
