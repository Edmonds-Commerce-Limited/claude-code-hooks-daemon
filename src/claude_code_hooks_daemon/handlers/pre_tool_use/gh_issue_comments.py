"""Handler to ensure gh issue view commands always include --comments."""

from __future__ import annotations

import logging
import re
import shlex
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.core.command_redirection import (
    COMMAND_REDIRECTION_SUBDIR,
    execute_and_save,
    format_redirection_context,
)
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.utils import get_bash_command

logger = logging.getLogger(__name__)


class GhIssueCommentsHandler(Handler):
    """Ensure gh issue view commands always include --comments flag.

    Comments on GitHub issues often contain critical context, clarifications,
    and updates that aren't in the issue body. Claude should always read them.

    Options:
        command_redirection: bool (default True) — When enabled, the handler
            executes the corrected command automatically and saves output to a
            file, so Claude gets both the educational message AND the result
            in one turn.
    """

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(
            handler_id=HandlerID.GH_ISSUE_COMMENTS,
            priority=Priority.GH_ISSUE_COMMENTS,
            tags=[HandlerTag.WORKFLOW, HandlerTag.GITHUB, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        options = options or {}
        self._command_redirection: bool = options.get("command_redirection", True)

        # Match: gh issue view [number] [--repo owner/repo] [other flags]
        # But NOT already containing --comments
        self._gh_issue_view_pattern = re.compile(
            r"\bgh\s+issue\s+view\b",
            re.IGNORECASE,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a gh issue view command without --comments."""
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Must be a gh issue view command
        if not self._gh_issue_view_pattern.search(command):
            return False

        # Already has --comments flag? Allow it through
        if "--comments" in command:
            return False

        # Using --json with comments field? That's equivalent to --comments
        if "--json" in command:
            # Extract the fields after --json
            # Pattern: --json <fields> where fields might be quoted or unquoted
            json_match = re.search(r"--json\s+([^\s|]+)", command)
            if json_match:
                fields = json_match.group(1)
                # Check if 'comments' is one of the comma-separated fields
                if re.search(r"\bcomments\b", fields):
                    return False

        # No --comments flag and no --json with comments field
        return True

    def get_redirected_command(self, hook_input: dict[str, Any]) -> list[str] | None:
        """Compute the corrected command as a list of args for subprocess.

        Returns None if no bash command is present.

        Args:
            hook_input: Hook input data

        Returns:
            Corrected command as list of strings, or None
        """
        command = get_bash_command(hook_input)
        if not command:
            return None

        suggested = self._compute_suggested_command(command)
        try:
            return shlex.split(suggested)
        except ValueError:
            # Fallback: simple split if shlex fails on complex quoting
            return suggested.split()

    def _compute_suggested_command(self, command: str) -> str:
        """Compute the suggested corrected command string.

        Args:
            command: Original bash command

        Returns:
            Corrected command string with --comments added
        """
        if "--json" in command:
            json_match = re.search(r"(--json\s+)([^\s|]+)", command)
            if json_match:
                prefix = json_match.group(1)
                fields = json_match.group(2)
                new_fields = f"{fields},comments"
                return command.replace(f"{prefix}{fields}", f"{prefix}{new_fields}", 1)
        return f"{command} --comments"

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block and suggest adding --comments flag.

        When command_redirection is enabled, also executes the corrected
        command and saves output to a file for immediate access.
        """
        command = get_bash_command(hook_input)
        if not command:
            return HookResult(decision=Decision.ALLOW)

        suggested_command = self._compute_suggested_command(command)

        reason = (
            "BLOCKED: gh issue view requires --comments flag\n\n"
            "WHY REQUIRED:\n"
            "  • Issue comments contain critical context and clarifications\n"
            "  • Updates and decisions are often discussed in comments\n"
            "  • Without comments, you miss half the conversation\n\n"
            "REQUIRED ACTION:\n"
            f"  Add --comments to your command:\n\n"
            f"  {suggested_command}\n"
        )

        # Command redirection: execute corrected command and save output
        context: list[str] = []
        if self._command_redirection:
            redirected_args = self.get_redirected_command(hook_input)
            if redirected_args:
                try:
                    output_dir = ProjectContext.daemon_untracked_dir() / COMMAND_REDIRECTION_SUBDIR
                    result = execute_and_save(
                        command=redirected_args,
                        output_dir=output_dir,
                        label="gh_issue_view",
                        cwd=ProjectContext.project_root(),
                    )
                    context = format_redirection_context(result)
                except (OSError, RuntimeError) as e:
                    logger.warning("Command redirection failed for gh_issue_comments: %s", e)

        return HookResult(decision=Decision.DENY, reason=reason, context=context)

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Gh Issue Comments."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="gh issue view without --comments is blocked",
                command='echo "gh issue view 123"',
                description="Blocks gh issue view without --comments flag",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"--comments"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
