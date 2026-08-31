"""Handler to ensure gh pr view commands always include --comments."""

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

# Shell command separators that end the `gh pr view` sub-command. Flags after
# one of these belong to a DIFFERENT command and must not satisfy the
# --comments requirement of the gh-pr-view invocation.
_COMMAND_SEPARATOR_PATTERN = re.compile(r"&&|\|\||;|\|")

# The --comments flag (whole-token match within the gh-pr-view segment only).
_COMMENTS_FLAG = "--comments"

# The --json flag introducer.
_JSON_FLAG = "--json"


class GhPrCommentsHandler(PreToolUseHandlerBase):
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
        self._rule = Rule(
            rule_id=RuleID.GH_PR_VIEW_NO_COMMENTS,
            blocked="`gh pr view` without `--comments`",
            why="PR comments contain review feedback and discussion context " "not in the PR body",
            fix="Add --comments, or include comments in --json fields",
            verbose=(
                "WHY REQUIRED:\n"
                "  • PR comments contain review feedback and discussion context\n"
                "  • Reviewer requests and decisions are often discussed in comments\n"
                "  • Without comments, you miss half the conversation"
            ),
        )
        self._formatter = RuleFormatter()

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's deny path."""
        return [self._rule]

    def _extract_gh_pr_view_segment(self, command: str) -> str | None:
        """Return the `gh pr view` sub-command segment of a (possibly chained) command.

        Scopes flag analysis to the segment that starts at the `gh pr view`
        match and ends at the next shell command separator (``&&``/``||``/``;``/
        ``|``). This prevents an incidental ``--comments`` token in an unrelated
        chained command (e.g. ``gh pr view 5 && echo "--comments"``) from
        satisfying the requirement of the actual gh-pr-view invocation.

        Args:
            command: Full bash command string.

        Returns:
            The gh-pr-view segment, or None if the command is not a gh pr view.
        """
        view_match = self._gh_pr_view_pattern.search(command)
        if not view_match:
            return None

        remainder = command[view_match.start() :]
        separator_match = _COMMAND_SEPARATOR_PATTERN.search(remainder)
        if separator_match:
            return remainder[: separator_match.start()]
        return remainder

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a gh pr view command without --comments."""
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Scope all flag checks to the gh-pr-view sub-command segment only.
        segment = self._extract_gh_pr_view_segment(command)
        if segment is None:
            return False

        # Already has --comments flag in this segment? Allow it through.
        if _COMMENTS_FLAG in segment:
            return False

        # Using --json with comments field? That's equivalent to --comments.
        if _JSON_FLAG in segment:
            # Extract the fields after --json
            # Pattern: --json <fields> where fields might be quoted or unquoted
            json_match = re.search(r"--json\s+([^\s|]+)", segment)
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
