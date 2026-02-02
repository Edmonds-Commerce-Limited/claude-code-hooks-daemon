"""CleanupHandler - cleans up temporary files at session end."""

import contextlib
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class CleanupHandler(Handler):
    """Clean up temporary files when session ends.

    Removes temporary hook-related files from untracked/temp directory.
    Non-terminal to allow session cleanup to proceed normally.
    """

    def __init__(self) -> None:
        """Initialise handler as non-terminal cleanup."""
        super().__init__(
            handler_id=HandlerID.SESSION_CLEANUP,
            priority=Priority.SESSION_CLEANUP,
            terminal=False,
            tags=[HandlerTag.CLEANUP, HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Match all session end events.

        Args:
            _hook_input: Hook input dictionary from Claude Code (unused)

        Returns:
            Always True (clean up on all session ends)
        """
        return True

    def handle(self, _hook_input: dict[str, Any]) -> HookResult:
        """Clean up temporary files.

        Args:
            _hook_input: Hook input dictionary from Claude Code (unused)

        Returns:
            HookResult with allow decision (silent cleanup)
        """
        try:
            temp_dir = Path("untracked/temp/hooks")

            # Only proceed if temp directory exists
            if not temp_dir.exists() or not temp_dir.is_dir():
                return HookResult(decision=Decision.ALLOW)

            # Remove all files in temp directory (but not subdirectories)
            for temp_file in temp_dir.glob("*"):
                if temp_file.is_file():
                    with contextlib.suppress(OSError):
                        temp_file.unlink()

        except OSError:
            # Silently ignore cleanup errors (don't block session end)
            pass

        return HookResult(decision=Decision.ALLOW)

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="cleanup handler handler test",
                command='echo "test"',
                description="Tests cleanup handler handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="SessionEnd event",
            ),
        ]
