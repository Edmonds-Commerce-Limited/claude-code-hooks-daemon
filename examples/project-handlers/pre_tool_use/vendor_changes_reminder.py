"""Vendor changes workflow reminder handler.

Example project handler that detects git add/commit commands including
vendor/ paths and provides an advisory reminder about the first-party
vendor commit workflow.

Copy this to .claude/project-handlers/pre_tool_use/ and adapt to your project.
"""

import re
from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.utils import get_bash_command


class VendorChangesReminderHandler(Handler):
    """Remind about vendor commit workflow when staging/committing vendor files.

    First-party vendor packages must be committed and pushed in their own
    vendor directory first, then the dependency manager updated in the
    main project.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id="vendor-changes-reminder",
            priority=45,
            terminal=False,  # Advisory - don't block
            tags=["project", "vendor", "workflow"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match git add/commit commands that include vendor/ paths."""
        command = get_bash_command(hook_input)
        if not command:
            return False
        return bool(re.search(r"\bgit\s+(add|commit)\b", command)) and "vendor/" in command

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Provide reminder about vendor workflow."""
        return HookResult(
            decision=Decision.ALLOW,
            context=[
                "VENDOR WORKFLOW REMINDER:",
                "When modifying first-party vendor packages:",
                "1. cd into vendor/{vendor}/{package}",
                "2. git add, commit, and push changes there FIRST",
                "3. Then in main project: update dependency lock file",
                "4. Commit the updated lock file in main project",
            ],
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Acceptance tests for vendor changes reminder."""
        return [
            AcceptanceTest(
                title="Vendor git add triggers reminder",
                command='echo "git add vendor/my-org/my-package/src/file.php"',
                description="Advisory reminder when staging vendor files",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"VENDOR WORKFLOW REMINDER"],
                safety_notes="Uses echo - safe to execute",
                test_type=TestType.ADVISORY,
            ),
        ]
