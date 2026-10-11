"""Handler to ensure gh issue view commands always include --comments."""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.gh_view_comments import (
    suggest_with_comments,
    uncommented_view_segment,
)

_NOUN = "issue"


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

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this runs a gh issue view command without --comments."""
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Only a view the command RUNS counts (ledger N408): a mention in an
        # echo, a message or a grep pattern is not one, and the flags are read
        # from that view's own segment, so a flag in a chained command cannot
        # satisfy it.
        return uncommented_view_segment(command, _NOUN) is not None

    def _compute_suggested_command(self, command: str) -> str:
        """Compute the suggested corrected command string.

        Scoped to the `gh issue view` segment that lacks the request, not the
        whole command: a whole-command append put `--comments` after a chained
        command's own trailing arguments (`gh issue view 123 && echo done` ->
        `... && echo done --comments`, fixing nothing).

        Args:
            command: Original bash command

        Returns:
            Corrected command string with --comments added
        """
        view = uncommented_view_segment(command, _NOUN)
        if view is None:  # pragma: no cover - handle() only calls this after a match
            return f"{command} --comments"
        return suggest_with_comments(command, view)

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
                command="bash -n -c 'gh issue view 999999999'",
                dispatch_as_bash=True,
                description="Blocks gh issue view without --comments flag",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"--comments"],
                safety_notes="bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
