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

    def __init__(self, options: dict[str, Any] | None = None) -> None:
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

    def _gh_issue_view_segment(self, command: str) -> str | None:
        """Return the 'gh issue view ...' sub-command segment, or None if absent.

        The segment runs from 'gh issue view' up to the next shell command separator
        (;, &&, ||, |). Anchoring the --comments / --json checks to THIS segment stops
        a flag in an unrelated chained command (e.g. `gh issue view 5 && echo
        "--comments"`) from spuriously exempting the view.
        """
        view_match = self._gh_issue_view_pattern.search(command)
        if not view_match:
            return None

        rest = command[view_match.start() :]
        # End the segment at the first command separator.
        separator_match = re.search(r"(?:;|&&|\|\||\|)", rest)
        if separator_match:
            return rest[: separator_match.start()]
        return rest

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a gh issue view command without --comments."""
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Must be a gh issue view command; scope all flag checks to its segment so
        # flags in chained commands cannot bypass the block.
        segment = self._gh_issue_view_segment(command)
        if segment is None:
            return False

        # Already has --comments flag in the view segment? Allow it through.
        if "--comments" in segment:
            return False

        # Using --json with comments field in the view segment? Equivalent to --comments.
        if "--json" in segment:
            # Pattern: --json <fields> where fields might be quoted or unquoted
            json_match = re.search(r"--json\s+([^\s|]+)", segment)
            if json_match:
                fields = json_match.group(1)
                # Check if 'comments' is one of the comma-separated fields
                if re.search(r"\bcomments\b", fields):
                    return False

        # No --comments flag and no --json with comments field in the view segment.
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
            "BLOCKED: gh issue view requires --comments flag\n\n"
            "WHY REQUIRED:\n"
            "  • Issue comments contain critical context and clarifications\n"
            "  • Updates and decisions are often discussed in comments\n"
            "  • Without comments, you miss half the conversation\n\n"
            "REQUIRED ACTION:\n"
            f"  Add --comments to your command:\n\n"
            f"  {suggested_command}\n"
        )

        return HookResult(decision=Decision.DENY, reason=reason)

    def get_claude_md(self) -> str | None:
        return (
            "## gh_issue_comments — always include --comments on gh issue view\n\n"
            "`gh issue view` without `--comments` is blocked. Issue comments often "
            "contain critical context, clarifications, and updates not in the issue body.\n\n"
            "**Blocked**: `gh issue view 123`, `gh issue view 123 --repo owner/repo`\n\n"
            "**Allowed**: `gh issue view 123 --comments`, "
            "`gh issue view 123 --json title,body,comments`\n\n"
            "If using `--json`, include `comments` in the field list instead of adding `--comments`."
        )

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
