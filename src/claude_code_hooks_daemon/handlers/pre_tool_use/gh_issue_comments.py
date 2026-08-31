"""Handler to ensure gh issue view commands always include --comments."""

from __future__ import annotations

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command


class GhIssueCommentsHandler(PreToolUseHandlerBase):
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
        self._rule = Rule(
            rule_id=RuleID.GH_ISSUE_VIEW_NO_COMMENTS,
            blocked="`gh issue view` without `--comments`",
            why="Issue comments contain critical context, clarifications and "
            "updates not in the issue body",
            fix="Add --comments, or include comments in --json fields",
            verbose=(
                "WHY REQUIRED:\n"
                "  • Issue comments contain critical context and clarifications\n"
                "  • Updates and decisions are often discussed in comments\n"
                "  • Without comments, you miss half the conversation"
            ),
        )
        self._formatter = RuleFormatter()

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's deny path."""
        return [self._rule]

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

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block and suggest adding --comments flag."""
        command = get_bash_command(hook_input)
        if not command:
            return GatingResult(decision=Decision.ALLOW)

        suggested_command = self._compute_suggested_command(command)

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        rule_id = self._rule.rule_id

        if transcript_path and tracker.was_disclosed(transcript_path, rule_id):
            message = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule_id)
            message = self._formatter.verbose(self._rule)

        # The suggested command is invocation-specific and always shown,
        # regardless of disclosure state -- it is the concrete fix, not
        # teaching content.
        message += (
            f"\n\nREQUIRED ACTION:\n  Add --comments to your command:\n\n  {suggested_command}\n"
        )

        return GatingResult(decision=Decision.DENY, reason=message)

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
