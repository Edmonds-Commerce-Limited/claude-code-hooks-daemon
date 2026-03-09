"""HedgingLanguageNitpickHandler - Nitpick pseudo-event handler for hedging language.

Audits assistant messages (provided by NitpickSetup) for hedging language
patterns that signal the agent is guessing instead of researching with tools.

Reuses compiled patterns from the Stop-event HedgingLanguageDetectorHandler
to maintain a single source of truth.
"""

from __future__ import annotations

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.handlers.stop.hedging_language_detector import (
    HedgingLanguageDetectorHandler,
)

HANDLER_ID = HandlerID.NITPICK_HEDGING
HANDLER_PRIORITY = Priority.NITPICK_HEDGING

# Category name -> pattern list, imported from the Stop handler (single source of truth)
_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("memory_guessing", HedgingLanguageDetectorHandler.MEMORY_PATTERNS),
    ("uncertainty", HedgingLanguageDetectorHandler.UNCERTAINTY_PATTERNS),
    ("weak_confidence", HedgingLanguageDetectorHandler.WEAK_CONFIDENCE_PATTERNS),
]


class HedgingLanguageNitpickHandler(Handler):
    """Detect hedging language in assistant messages via nitpick pseudo-event.

    Advisory handler that runs as part of the nitpick handler chain.
    Receives pre-extracted assistant_messages from NitpickSetup and scans
    each message for hedging phrases that indicate guessing.

    Non-terminal: accumulates findings as context, never blocks.
    """

    def __init__(self) -> None:
        """Initialise the hedging language nitpick handler."""
        super().__init__(
            handler_id=HANDLER_ID,
            priority=HANDLER_PRIORITY,
            terminal=False,
            tags=[
                HandlerTag.VALIDATION,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.CONTENT_QUALITY,
            ],
        )
        # Compile all patterns once for performance
        self._compiled: list[tuple[str, re.Pattern[str]]] = []
        for category, patterns in _CATEGORY_PATTERNS:
            for pattern_str in patterns:
                self._compiled.append((category, re.compile(pattern_str, re.IGNORECASE)))

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match when assistant_messages are present in hook_input.

        NitpickSetup enriches hook_input with assistant_messages when new
        messages are available for auditing.

        Args:
            hook_input: Enriched hook input from NitpickSetup

        Returns:
            True if assistant_messages present and non-empty
        """
        messages = hook_input.get("assistant_messages")
        return bool(messages)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Scan assistant messages for hedging language.

        Args:
            hook_input: Enriched hook input with assistant_messages list

        Returns:
            HookResult with ALLOW decision and any findings as context
        """
        messages: list[dict[str, str]] = hook_input.get("assistant_messages", [])
        context_lines: list[str] = []

        for msg in messages:
            text = msg.get("content", "")
            if not text:
                continue
            for category, compiled in self._compiled:
                if compiled.search(text):
                    readable = category.replace("_", " ")
                    context_lines.append(
                        f"Hedging language detected ({readable}): "
                        f"use tools to verify instead of guessing"
                    )

        return HookResult(decision=Decision.ALLOW, context=context_lines)

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
                title="nitpick hedging language - detects guessing in transcript",
                command='echo "test"',
                description=(
                    "Tests that the nitpick handler detects hedging language "
                    "like 'if I recall', 'probably', 'I believe' in assistant "
                    "messages provided by the NitpickSetup pseudo-event."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"hedging", r"verify"],
                safety_notes="Advisory handler - warns but does not block",
                test_type=TestType.CONTEXT,
                requires_event="Nitpick pseudo-event with assistant_messages",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
