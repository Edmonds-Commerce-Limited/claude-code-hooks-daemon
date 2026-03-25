"""DaemonDocsGuardHandler - warns when reading from hooks-daemon internal docs directory."""

from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

# Pattern that identifies the daemon's internal docs directory.
# In normal installs, the daemon is cloned to .claude/hooks-daemon/, which brings
# along the daemon's own CLAUDE/ docs directory. This collides with the project's
# CLAUDE/ convention — both paths contain "CLAUDE/" as a segment.
_DAEMON_CLAUDE_PATTERN = "hooks-daemon/CLAUDE/"

_TARGET_TOOLS = {ToolName.READ, ToolName.WRITE, ToolName.EDIT}


def _get_file_path(hook_input: dict[str, Any]) -> str:
    """Extract file_path from tool_input for Read, Write, and Edit tools."""
    tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
    return str(tool_input.get("file_path", ""))


class DaemonDocsGuardHandler(Handler):
    """Warn when reading from the hooks-daemon internal CLAUDE/ docs directory.

    The daemon is git-cloned to .claude/hooks-daemon/, which creates
    .claude/hooks-daemon/CLAUDE/ alongside the project's own CLAUDE/ directory.
    When Claude Code resolves @CLAUDE/... references, it can mistakenly read
    from the daemon's internal copy instead of the project's authoritative docs.

    This handler detects such reads and injects a corrective advisory.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DAEMON_DOCS_GUARD,
            priority=Priority.DAEMON_DOCS_GUARD,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.DAEMON,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if the tool is accessing the daemon's internal CLAUDE/ directory."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in _TARGET_TOOLS:
            return False

        file_path = _get_file_path(hook_input)
        if not file_path:
            return False

        return _DAEMON_CLAUDE_PATTERN in file_path

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Allow the operation but inject a warning about the wrong CLAUDE/ directory."""
        file_path = _get_file_path(hook_input)
        filename = file_path.split("/")[-1] if file_path else ""

        warning = (
            f"⚠️  WRONG CLAUDE/ DIRECTORY: You are reading from the hooks-daemon's "
            f"internal docs copy, not your project's authoritative docs.\n\n"
            f"  Reading: {file_path}\n\n"
            f"The daemon is installed at .claude/hooks-daemon/ which includes its own "
            f"CLAUDE/ subdirectory. This is NOT your project's CLAUDE/ directory.\n\n"
            f"If you meant to read project documentation, use the project root path:\n"
            f"  CLAUDE/{filename}\n\n"
            f"The hooks-daemon internal docs may be a different version or have "
            f"different content from your project's documentation."
        )

        return HookResult(decision=Decision.ALLOW, context=[warning])

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for daemon docs guard."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Read from hooks-daemon CLAUDE dir warns about wrong path",
                command=(
                    "Use the Read tool to read the file "
                    "/tmp/acceptance-test-daemon-docs/.claude/hooks-daemon/CLAUDE/PlanWorkflow.md"
                ),
                description="Warns about reading from daemon internal docs (advisory, allows read)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"WRONG CLAUDE", r"hooks-daemon"],
                safety_notes="Uses /tmp path - safe. Advisory handler allows read but warns.",
                test_type=TestType.ADVISORY,
                setup_commands=[
                    "mkdir -p /tmp/acceptance-test-daemon-docs/.claude/hooks-daemon/CLAUDE",
                    "echo '# Test PlanWorkflow' > "
                    "/tmp/acceptance-test-daemon-docs/.claude/hooks-daemon/CLAUDE/PlanWorkflow.md",
                ],
                cleanup_commands=["rm -rf /tmp/acceptance-test-daemon-docs"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
