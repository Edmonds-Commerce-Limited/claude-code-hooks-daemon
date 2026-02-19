"""HedgingLanguageDetectorHandler - Detects guessing instead of researching.

Scans the last assistant message in the transcript for hedging language
that signals the agent is making assumptions instead of using tools
(Read, Grep, Glob) to verify facts. This is a HUGE red flag - when agents
guess instead of research, things go very wrong.

Detected patterns:
- Memory-based guessing: "if I recall", "IIRC", "from memory"
- Uncertainty hedging: "should probably", "most likely", "presumably"
- Weak confidence: "I'm not sure but", "I'm pretty sure", "I believe"
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

logger = logging.getLogger(__name__)

# Handler constants (will be registered in constants modules)
HANDLER_ID = HandlerID.HEDGING_LANGUAGE_DETECTOR
HANDLER_PRIORITY = Priority.HEDGING_LANGUAGE_DETECTOR


class HedgingLanguageDetectorHandler(Handler):
    """Detect hedging language that signals guessing instead of researching.

    Advisory handler that fires on Stop events. Reads the transcript to
    check the last assistant message for hedging phrases. When detected,
    injects a warning telling the agent to stop guessing and verify with tools.

    Non-terminal: does not block the stop, only injects context.
    """

    # Memory-based guessing - agent relying on recall instead of looking
    MEMORY_PATTERNS: ClassVar[list[str]] = [
        r"\bif I recall\b",
        r"\bIIRC\b",
        r"\bfrom memory\b",
        r"\bif memory serves\b",
        r"\bfrom what I remember\b",
    ]

    # Uncertainty hedging - agent unsure about verifiable facts
    UNCERTAINTY_PATTERNS: ClassVar[list[str]] = [
        r"\bshould probably\b",
        r"\bmost likely\b",
        r"\bpresumably\b",
        r"\bI assume\b",
        r"\bI believe\b",
        r"\bI suspect\b",
    ]

    # Weak confidence - agent hedging on things it could verify
    WEAK_CONFIDENCE_PATTERNS: ClassVar[list[str]] = [
        r"\bI'm not sure but\b",
        r"\bI'm fairly confident\b",
        r"\bI'm pretty sure\b",
        r"\bit seems like\b",
        r"\bmight be\b",
        r"\bcould be\b",
    ]

    def __init__(self) -> None:
        """Initialise the hedging language detector handler."""
        super().__init__(
            handler_id=HANDLER_ID,
            priority=HANDLER_PRIORITY,
            terminal=False,
            tags=[
                HandlerTag.VALIDATION,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.WORKFLOW,
            ],
        )
        # Compile all patterns once for performance
        self._all_patterns: list[tuple[str, re.Pattern[str]]] = []
        for pattern_str in (
            self.MEMORY_PATTERNS + self.UNCERTAINTY_PATTERNS + self.WEAK_CONFIDENCE_PATTERNS
        ):
            self._all_patterns.append((pattern_str, re.compile(pattern_str, re.IGNORECASE)))

    def _is_stop_hook_active(self, hook_input: dict[str, Any]) -> bool:
        """Check if stop hook is in re-entry state (prevents infinite loops).

        Claude Code may send this field as snake_case or camelCase.

        Args:
            hook_input: Hook input dictionary

        Returns:
            True if stop hook is active (re-entry detected)
        """
        return bool(
            hook_input.get("stop_hook_active", False) or hook_input.get("stopHookActive", False)
        )

    def _get_last_assistant_message(self, transcript_path: str) -> str:
        """Read transcript and extract the last assistant message text.

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

            # Parse JSONL in reverse - find last assistant message
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

                    # Extract text content from content array
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

    def _find_hedging_phrases(self, text: str) -> list[str]:
        """Find all hedging phrases in the given text.

        Args:
            text: Text to scan for hedging language

        Returns:
            List of matched phrase patterns (human-readable)
        """
        found: list[str] = []
        for pattern_str, compiled in self._all_patterns:
            if compiled.search(text):
                # Extract the readable phrase from the regex (strip \b markers)
                readable = pattern_str.replace(r"\b", "")
                found.append(readable)
        return found

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if the last assistant message contains hedging language.

        Args:
            hook_input: Hook input with transcript_path

        Returns:
            True if hedging language detected in last assistant message
        """
        # Prevent infinite loops on re-entry
        if self._is_stop_hook_active(hook_input):
            logger.debug("Stop hook active (re-entry) - skipping hedging check")
            return False

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if not transcript_path:
            logger.debug("No transcript_path in hook_input - cannot check for hedging")
            return False

        last_message = self._get_last_assistant_message(str(transcript_path))
        if not last_message:
            logger.debug("No assistant message found in transcript")
            return False

        phrases = self._find_hedging_phrases(last_message)
        if phrases:
            logger.info(
                "Hedging language detected: %s",
                ", ".join(phrases),
            )
            return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return advisory warning about hedging language.

        Args:
            hook_input: Hook input with transcript_path

        Returns:
            HookResult with ALLOW decision and warning context
        """
        # Find the specific phrases for the warning message
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        phrases: list[str] = []
        if transcript_path:
            last_message = self._get_last_assistant_message(str(transcript_path))
            if last_message:
                phrases = self._find_hedging_phrases(last_message)

        if phrases:
            phrase_list = ", ".join(f'"{p}"' for p in phrases)
            context = (
                f"HEDGING LANGUAGE DETECTED: {phrase_list}\n"
                "\n"
                "No GUESSING, no ASSUMPTIONS, only FACT BASED decisions "
                "based on RESEARCH both online and in the codebase.\n"
                "\n"
                "STOP and VERIFY before continuing:\n"
                "  - Use Read to check actual file contents\n"
                "  - Use Grep to search for patterns in code\n"
                "  - Use Glob to find files by name\n"
                "  - Use Bash to run commands and check real state\n"
                "  - Use WebSearch / WebFetch for online research\n"
                "\n"
                "NEVER guess when you can look. Tools are fast - use them."
            )
        else:
            context = (
                "HEDGING LANGUAGE WARNING: Your response contained uncertain language.\n"
                "No GUESSING, no ASSUMPTIONS, only FACT BASED decisions "
                "based on RESEARCH both online and in the codebase."
            )

        return HookResult(decision=Decision.ALLOW, context=[context])

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
                title="hedging language detector - detects guessing phrases",
                command='echo "test"',
                description=(
                    "Tests that the handler detects hedging language like "
                    "'I believe', 'should probably', 'IIRC' in assistant messages "
                    "and injects a warning to use tools instead of guessing."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"hedging", r"verify"],
                safety_notes="Advisory handler - warns but does not block",
                test_type=TestType.CONTEXT,
                requires_event="Stop event with transcript_path",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
