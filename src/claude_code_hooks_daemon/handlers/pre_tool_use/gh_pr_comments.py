"""Handler to ensure gh pr view commands always include --comments."""

from __future__ import annotations

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.utils import get_bash_command


class GhPrCommentsHandler(Handler):
    """Ensure gh pr view commands always include --comments flag.

    Review comments and general conversation on GitHub pull requests often
    contain critical context, review feedback, and decisions that aren't in
    the PR body. Claude should always read them.
    """

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(
            handler_id=HandlerID.GH_PR_COMMENTS,
            priority=Priority.GH_PR_COMMENTS,
            tags=[HandlerTag.WORKFLOW, HandlerTag.GITHUB, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        # Match: gh pr view [number] [--repo owner/repo] [other flags]
        # But NOT already containing --comments
        self._gh_pr_view_pattern = re.compile(
            r"\bgh\s+pr\s+view\b",
            re.IGNORECASE,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a gh pr view command without --comments."""
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Must be a gh pr view command
        if not self._gh_pr_view_pattern.search(command):
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
        """Block and suggest adding --comments flag."""
        command = get_bash_command(hook_input)
        if not command:
            return HookResult(decision=Decision.ALLOW)

        suggested_command = self._compute_suggested_command(command)

        reason = (
            "BLOCKED: gh pr view requires --comments flag\n\n"
            "WHY REQUIRED:\n"
            "  • PR comments contain review feedback and discussion context\n"
            "  • Reviewer requests and decisions are often discussed in comments\n"
            "  • Without comments, you miss half the conversation\n\n"
            "REQUIRED ACTION:\n"
            f"  Add --comments to your command:\n\n"
            f"  {suggested_command}\n"
        )

        return HookResult(decision=Decision.DENY, reason=reason)

    def get_claude_md(self) -> str | None:
        return (
            "## gh_pr_comments — always include --comments on gh pr view\n\n"
            "`gh pr view` without `--comments` is blocked. PR comments often contain "
            "review feedback, reviewer requests, and decisions not in the PR body.\n\n"
            "**Blocked**: `gh pr view 123`, `gh pr view 123 --repo owner/repo`\n\n"
            "**Allowed**: `gh pr view 123 --comments`, "
            "`gh pr view 123 --json title,body,comments`\n\n"
            "If using `--json`, include `comments` in the field list instead of adding `--comments`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Gh Pr Comments."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="gh pr view without --comments is blocked",
                command='echo "gh pr view 123"',
                description="Blocks gh pr view without --comments flag",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"--comments"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
