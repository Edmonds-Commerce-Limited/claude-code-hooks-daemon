"""Build asset watcher handler.

Example project handler that detects writes to frontend source files
(TypeScript, SCSS, etc.) and reminds to rebuild compiled assets.

Copy this to .claude/project-handlers/post_tool_use/ and adapt the
source patterns to your project's asset structure.
"""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, BlockingResult, TestType
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.utils import get_file_path

# Adapt these patterns to your project's asset source locations
_SOURCE_PATTERNS = (
    "assets/ts/",
    "assets/scss/",
    "assets/css/",
)


class BuildAssetWatcherHandler(PostToolUseHandlerBase):
    """Remind to rebuild assets after editing frontend source files.

    Frontend source files (TypeScript, SCSS) must be compiled before
    they take effect. This handler provides advisory reminders.

    This handler only ever advises, but `PostToolUse` is a BLOCKING event —
    it can deny, just not ask — so subclassing `PostToolUseHandlerBase`
    narrows `handle()` to `BlockingResult` rather than the advisory-only
    tier. The narrowing tracks what the EVENT can deliver, not what this
    particular handler happens to do with it.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id="build-asset-watcher",
            priority=50,
            terminal=False,  # Advisory - don't block
            tags=["project", "build", "frontend"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match Write/Edit operations on frontend source files."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return False
        return any(pattern in file_path for pattern in _SOURCE_PATTERNS)

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Provide reminder about rebuilding assets."""
        return BlockingResult(
            decision=Decision.ALLOW,
            context=[
                "ASSET BUILD REMINDER:",
                "You modified a frontend source file.",
                "Run your build command (e.g., 'npm run build' or 'yarn build')",
                "to rebuild compiled assets before testing.",
            ],
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Acceptance tests for build asset watcher."""
        return [
            AcceptanceTest(
                title="Frontend file edit triggers build reminder",
                command='echo "Edit TS file in assets/ts/"',
                description="Advisory reminder when editing frontend source",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"ASSET BUILD REMINDER"],
                safety_notes="Uses echo - safe to execute",
                test_type=TestType.ADVISORY,
                requires_event="PostToolUse after Write/Edit to frontend file",
            ),
        ]
