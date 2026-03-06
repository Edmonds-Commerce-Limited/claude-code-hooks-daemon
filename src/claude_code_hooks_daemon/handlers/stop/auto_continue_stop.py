"""AutoContinueStopHandler - True auto-continue without user input.

Blocks Stop events when Claude asks confirmation questions, making Claude
continue automatically in YOLO mode without requiring any user interaction.
"""

import logging
import re
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, ToolName
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.utils.stop_hook_helpers import (
    get_transcript_reader,
    is_stop_hook_active,
)

logger = logging.getLogger(__name__)


class AutoContinueStopHandler(Handler):
    """Auto-continue when Claude asks confirmation questions.

    This handler intercepts Stop events, reads the transcript to detect
    if Claude's last message was a confirmation question, and blocks
    the stop with an auto-continue instruction. No user input required.

    Critical: Checks stop_hook_active to prevent infinite loops.
    """

    # Confirmation patterns that indicate Claude is asking to continue
    CONFIRMATION_PATTERNS: ClassVar[list[str]] = [
        r"would you like me to (?:continue|proceed|start|begin)",
        r"would you like to (?:continue|proceed|start|begin)",
        r"should I (?:continue|proceed|start|begin)",
        r"shall I (?:continue|proceed|start|begin)",
        r"do you want me to (?:continue|proceed|start|begin)",
        r"may I (?:continue|proceed|start|begin)",
        r"can I (?:continue|proceed|start|begin)",
        r"ready (?:for me )?to (?:continue|proceed|start|begin)",
        r"ready to (?:implement|execute|run)",
        r"would you like me to (?:launch|execute|run)",
        r"should I (?:launch|execute|run)",
        r"would you like me to move (?:on|forward)",
        r"shall we (?:continue|proceed|move on)",
        r"continue with (?:batch|phase|step)",
        r"would you like.+(?:batch|phase|step)",
        r"shall I proceed.+(?:batch|phase|step)",
        # Patterns ported from php-qa-ci (Phase 2 integration)
        r"let me know if you.*(?:continue|proceed)",
        r"want me to (?:go ahead|keep going)",
        r"if you'd like.*(?:continue|proceed)",
        r"i can (?:continue|proceed) with",
    ]

    # Patterns that indicate an error or problem - should NOT auto-continue
    ERROR_PATTERNS: ClassVar[list[str]] = [
        r"error:",
        r"failed:",
        r"what would you like me to do",
        r"how should I (?:handle|proceed|fix)",
        r"what do you (?:think|suggest|prefer)",
    ]

    def __init__(self) -> None:
        """Initialize the auto-continue stop handler."""
        super().__init__(
            handler_id=HandlerID.AUTO_CONTINUE_STOP,
            priority=Priority.AUTO_CONTINUE_STOP,
            terminal=True,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.AUTOMATION,
                HandlerTag.YOLO_MODE,
                HandlerTag.TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a confirmation question stop that should auto-continue.

        Args:
            hook_input: Hook input with transcript_path and stop_hook_active

        Returns:
            True if Claude asked a confirmation question and we should auto-continue
        """
        # CRITICAL: Prevent infinite loops - check both casing variants
        if is_stop_hook_active(hook_input):
            logger.debug("Stop hook is active (re-entry) - skipping to prevent infinite loop")
            return False

        reader = get_transcript_reader(hook_input)
        if not reader:
            logger.debug("No transcript available - cannot check for confirmation")
            return False

        last_message = reader.get_last_assistant_text()
        if not last_message:
            logger.debug("No assistant message found in transcript")
            return False

        # Must contain a question mark
        if "?" not in last_message:
            logger.debug("Last assistant message has no question mark - not a confirmation")
            return False

        # Check for error patterns - don't auto-continue on errors
        if self._contains_error_pattern(last_message):
            logger.debug("Last message contains error pattern - not auto-continuing")
            return False

        # Check if it's a confirmation question
        is_confirmation = self._contains_confirmation_pattern(last_message)
        if not is_confirmation:
            logger.debug("Question found but no confirmation pattern matched")
            return False

        # CRITICAL: Don't auto-continue when Claude used AskUserQuestion
        # The text may contain confirmation-like phrasing ("Would you like...")
        # but the user MUST see and answer the question
        if reader.last_assistant_used_tool(ToolName.ASK_USER_QUESTION):
            logger.info("AskUserQuestion detected - user must answer, not auto-continuing")
            return False

        logger.info("Confirmation question detected - will auto-continue")
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block the stop and tell Claude to auto-continue.

        Args:
            hook_input: Hook input (unused, we just block)

        Returns:
            HookResult with DENY decision and auto-continue instruction
        """
        reason = (
            "AUTO-CONTINUE: Yes, proceed with all remaining work. "
            "Do not ask for confirmation again. "
            "Continue automatically without asking for permission."
        )
        return HookResult(decision=Decision.DENY, reason=reason)

    def _contains_confirmation_pattern(self, text: str) -> bool:
        """Check if text contains a confirmation pattern.

        Args:
            text: Text to check

        Returns:
            True if text contains a confirmation pattern
        """
        text_lower = text.lower()
        for pattern in self.CONFIRMATION_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def _contains_error_pattern(self, text: str) -> bool:
        """Check if text contains an error pattern.

        Args:
            text: Text to check

        Returns:
            True if text contains an error pattern (should not auto-continue)
        """
        text_lower = text.lower()
        return any(re.search(pattern, text_lower, re.IGNORECASE) for pattern in self.ERROR_PATTERNS)

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="auto continue stop handler test",
                command='echo "test"',
                description="Tests auto continue stop handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="Stop event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
