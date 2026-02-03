"""Daemon Restart Verifier Handler.

Prevents git commits in the hooks daemon repository if the daemon cannot
restart successfully with the current code changes.

This handler dogfoods the daemon on itself - ensuring that code changes
that break the daemon (import errors, etc.) cannot be committed.

CRITICAL: This would have caught the 5-handler import bug!
"""

from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, Handler, HookResult, TestType
from claude_code_hooks_daemon.daemon.validation import is_hooks_daemon_repo


class DaemonRestartVerifierHandler(Handler):
    """Verify daemon can restart before allowing git commits."""

    def __init__(self) -> None:
        """Initialize handler."""
        super().__init__(
            handler_id=HandlerID.DAEMON_RESTART_VERIFIER,
            priority=Priority.DAEMON_RESTART_VERIFIER,
            terminal=False,  # Advisory - suggest verification but don't block
            tags=[HandlerTag.SAFETY, HandlerTag.WORKFLOW, HandlerTag.ADVISORY],
        )

        # Configuration attributes (set by registry after instantiation)
        # Default to current directory, will be overridden by registry if workspace_root option is set
        from pathlib import Path

        self._workspace_root = Path.cwd()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match git commit commands in hooks daemon repo.

        Args:
            hook_input: Hook input data

        Returns:
            True if this is a git commit in hooks daemon repo
        """
        # Only match Bash tool
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False

        # Only in hooks daemon repo (dogfooding)
        if not is_hooks_daemon_repo(self._workspace_root):
            return False

        command = hook_input.get(HookInputField.TOOL_INPUT, {}).get("command", "")
        if not command:
            return False

        # Match git commit commands
        import re

        # Pattern: git commit (with any flags/options)
        if re.search(r"\bgit\s+commit\b", command):
            return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Suggest daemon restart verification before commit.

        Args:
            hook_input: Hook input data

        Returns:
            HookResult with advisory message
        """
        # Advisory message suggesting verification
        guidance = (
            "💡 RECOMMENDED: Verify daemon can restart before committing:\n\n"
            "```bash\n"
            "$PYTHON -m claude_code_hooks_daemon.daemon.cli restart\n"
            "$PYTHON -m claude_code_hooks_daemon.daemon.cli status\n"
            "```\n\n"
            "This catches import errors and loading failures that unit tests miss.\n"
            "The 5-handler import bug would have been caught by this check!"
        )

        return HookResult.allow(guidance=guidance)

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for daemon restart verifier."""
        return [
            AcceptanceTest(
                title="Daemon restart verification advisory",
                command="git status",
                description="Suggests verifying daemon restart before git commits (advisory only)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"RECOMMENDED", r"restart"],
                safety_notes="Advisory handler - suggests best practice",
                test_type=TestType.ADVISORY,
                requires_event="PreToolUse on git commit in hooks daemon repo",
            ),
        ]
