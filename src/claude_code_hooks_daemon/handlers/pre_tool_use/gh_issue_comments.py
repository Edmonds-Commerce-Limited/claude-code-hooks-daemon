"""Handler to ensure gh issue view commands always include --comments."""

from __future__ import annotations

import re
from typing import Any

from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.utils import get_bash_command


class GhIssueCommentsHandler(Handler):
    """Ensure gh issue view commands always include --comments flag.

    Comments on GitHub issues often contain critical context, clarifications,
    and updates that aren't in the issue body. Claude should always read them.
    """

    def __init__(self) -> None:
        super().__init__(
            name="require-gh-issue-comments",
            priority=40,
            tags=["workflow", "github", "blocking", "terminal"],
        )
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

        # Already has --comments? Allow it through
        return "--comments" not in command

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block and suggest adding --comments flag."""
        command = get_bash_command(hook_input)
        if not command:
            return HookResult(decision=Decision.ALLOW)

        # Suggest the corrected command
        suggested_command = f"{command} --comments"

        return HookResult(
            decision=Decision.DENY,
            reason=(
                "BLOCKED: gh issue view requires --comments flag\n\n"
                "WHY REQUIRED:\n"
                "  • Issue comments contain critical context and clarifications\n"
                "  • Updates and decisions are often discussed in comments\n"
                "  • Without comments, you miss half the conversation\n\n"
                "REQUIRED ACTION:\n"
                f"  Add --comments to your command:\n\n"
                f"  {suggested_command}\n"
            ),
        )
