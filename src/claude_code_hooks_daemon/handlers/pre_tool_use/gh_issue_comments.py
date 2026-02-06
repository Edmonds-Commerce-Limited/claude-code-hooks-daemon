"""Handler to ensure gh issue view commands always include --comments."""

from __future__ import annotations

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
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
            handler_id=HandlerID.GH_ISSUE_COMMENTS,
            priority=Priority.GH_ISSUE_COMMENTS,
            tags=[HandlerTag.WORKFLOW, HandlerTag.GITHUB, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
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

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block and suggest adding --comments flag."""
        command = get_bash_command(hook_input)
        if not command:
            return HookResult(decision=Decision.ALLOW)

        # Check if using --json format
        if "--json" in command:
            # Suggest adding 'comments' to the JSON fields
            json_match = re.search(r"(--json\s+)([^\s|]+)", command)
            if json_match:
                prefix = json_match.group(1)
                fields = json_match.group(2)
                new_fields = f"{fields},comments"
                suggested_command = command.replace(f"{prefix}{fields}", f"{prefix}{new_fields}", 1)
            else:
                suggested_command = f"{command} --comments"
        else:
            # Regular command - add --comments flag
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

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Gh Issue Comments."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="GitHub issue comment guidance",
                command='echo "gh issue comment 123"',
                description="Provides GitHub CLI guidance (advisory)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"GitHub", r"issue"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.ADVISORY,
            ),
        ]
