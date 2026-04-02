"""AskUserQuestionBlockerHandler - prevent progress-blocking user questions.

When enabled, blocks AskUserQuestion tool calls so Claude continues working
autonomously without stopping to ask the user for input. Useful for fully
unattended or batch workflows where user interaction is not desired.

Disabled by default — enable in hooks-daemon.yaml when you want uninterrupted
autonomous operation.
"""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class AskUserQuestionBlockerHandler(Handler):
    """Block AskUserQuestion to prevent progress-blocking user prompts.

    When enabled, prevents Claude from stopping to ask the user questions.
    Instead, Claude should make reasonable decisions autonomously and
    continue working without interruption.

    This is useful for:
    - Fully unattended/batch workflows
    - Long-running tasks where stopping for questions wastes time
    - Situations where the user prefers autonomous decision-making

    Disabled by default. Enable in config when uninterrupted operation
    is desired.
    """

    def __init__(self) -> None:
        """Initialise handler."""
        super().__init__(
            handler_id=HandlerID.ASK_USER_QUESTION_BLOCKER,
            priority=Priority.ASK_USER_QUESTION_BLOCKER,
            tags=[HandlerTag.WORKFLOW, HandlerTag.TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is an AskUserQuestion tool call.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            True if tool_name is AskUserQuestion
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        return tool_name == ToolName.ASK_USER_QUESTION

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block the question and instruct Claude to decide autonomously.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            HookResult with deny decision and guidance
        """
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "BLOCKED: User questions are disabled in this session.\n\n"
                "The user does not want you to stop and ask questions.\n"
                "Make a reasonable decision autonomously and continue working.\n"
                "If you need to communicate choices you made, mention them\n"
                "in your output text instead of blocking progress."
            ),
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for AskUserQuestion Blocker."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Block AskUserQuestion for unattended operation",
                command="AskUserQuestion tool call",
                description=(
                    "Blocks AskUserQuestion so Claude works autonomously "
                    "without stopping for user input"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"autonomously"],
                safety_notes="Only active when explicitly enabled in config",
                test_type=TestType.BLOCKING,
                requires_event="PreToolUse for AskUserQuestion",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
