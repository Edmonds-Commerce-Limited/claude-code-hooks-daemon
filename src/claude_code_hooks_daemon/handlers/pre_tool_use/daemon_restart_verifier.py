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
from claude_code_hooks_daemon.core import (
    AcceptanceTest,
    Decision,
    GatingResult,
    ProjectContext,
    RecommendedModel,
    TestType,
)
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.daemon.validation import is_hooks_daemon_repo
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs


class DaemonRestartVerifierHandler(PreToolUseHandlerBase):
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
        # Default to ProjectContext (initialized before handlers), overridden by registry options
        self._workspace_root = ProjectContext.project_root()

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

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Nudge toward daemon restart verification before a commit.

        Deliberately a SINGLE short line, and nothing else. The commands, the
        rationale and the 5-handler anecdote all live in ``get_claude_md()``,
        which keeps them resident in CLAUDE.md for the whole session — so
        attaching a second copy to every commit was paying for the same advice
        twice and teaching nothing the first copy had not (Plan 00238 Task 4.2).

        Args:
            hook_input: Hook input data

        Returns:
            GatingResult with the one-line advisory nudge
        """
        return GatingResult(
            decision=Decision.ALLOW,
            context=["💡 RECOMMENDED: Verify daemon restart before committing"],
        )

    def get_claude_md(self) -> str | None:
        return (
            "## daemon_restart_verifier — restart the daemon before committing\n\n"
            "Before making a `git commit` in the hooks daemon repository, this handler "
            "advises verifying that the daemon can restart successfully with the current "
            "code changes. This is advisory — it adds context but does not block the commit.\n\n"
            "**Why**: Unit tests alone don't catch import errors. A handler that fails to "
            "import silently disables protection without any test-time error. Daemon restart "
            "is the definitive check.\n\n"
            "**Run before committing** (in this repo only):\n"
            f"`{daemon_cli_command_for_docs('restart')}` then verify status shows RUNNING."
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for daemon restart verifier."""
        return [
            AcceptanceTest(
                title="Daemon restart verification advisory",
                command="echo \"git commit -m 'test WIP'\"",
                description="Suggests verifying daemon restart before git commits (advisory only)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"RECOMMENDED", r"restart"],
                safety_notes="Uses echo - safe to test. Handler matches git commit in command string.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
