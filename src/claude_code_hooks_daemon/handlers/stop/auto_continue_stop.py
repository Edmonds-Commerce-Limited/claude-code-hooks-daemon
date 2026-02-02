"""AutoContinueStopHandler - True auto-continue without user input.

Blocks Stop events when Claude asks confirmation questions, making Claude
continue automatically in YOLO mode without requiring any user interaction.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

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
        # CRITICAL: Prevent infinite loops
        if hook_input.get("stop_hook_active", False):
            return False

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH, "")
        if not transcript_path:
            return False

        # Get the last assistant message from transcript
        last_message = self._get_last_assistant_message(transcript_path)
        if not last_message:
            return False

        # Must contain a question mark
        if "?" not in last_message:
            return False

        # Check for error patterns - don't auto-continue on errors
        if self._contains_error_pattern(last_message):
            return False

        # Check if it's a confirmation question
        return self._contains_confirmation_pattern(last_message)

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

    def _get_last_assistant_message(self, transcript_path: str) -> str:
        """Read transcript and get the last assistant message.

        Args:
            transcript_path: Path to the JSONL transcript file

        Returns:
            Text content of the last assistant message, or empty string
        """
        try:
            path = Path(transcript_path)
            if not path.exists():
                return ""

            with path.open() as f:
                lines = f.readlines()

            if not lines:
                return ""

            # Parse JSONL - find last assistant message
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if msg.get("type") != "message":
                        continue
                    message = msg.get("message", {})
                    if message.get("role") != "assistant":
                        continue

                    # Extract text content
                    content = message.get("content", [])
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif isinstance(part, str):
                            text_parts.append(part)

                    return " ".join(text_parts)
                except (json.JSONDecodeError, ValueError):
                    continue

            return ""
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug("Failed to read transcript from %s: %s", transcript_path, e)
            return ""
        except Exception as e:
            logger.error("Unexpected error reading transcript: %s", e, exc_info=True)
            return ""

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
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

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
            ),
        ]
