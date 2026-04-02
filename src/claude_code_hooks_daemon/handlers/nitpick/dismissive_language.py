"""DismissiveLanguageNitpickHandler - Nitpick pseudo-event handler for dismissive language.

Audits assistant messages (provided by NitpickSetup) for dismissive language
patterns that signal the agent is deflecting responsibility instead of fixing issues.

Reuses compiled patterns from the Stop-event DismissiveLanguageDetectorHandler
to maintain a single source of truth.
"""

from __future__ import annotations

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.handlers.stop.dismissive_language_detector import (
    DismissiveLanguageDetectorHandler,
)

HANDLER_ID = HandlerID.NITPICK_DISMISSIVE
HANDLER_PRIORITY = Priority.NITPICK_DISMISSIVE

# Category name -> pattern list, imported from the Stop handler (single source of truth)
_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("not_our_problem", DismissiveLanguageDetectorHandler.NOT_OUR_PROBLEM_PATTERNS),
    ("out_of_scope", DismissiveLanguageDetectorHandler.OUT_OF_SCOPE_PATTERNS),
    ("someone_elses_job", DismissiveLanguageDetectorHandler.SOMEONE_ELSES_JOB_PATTERNS),
    ("defer_ignore", DismissiveLanguageDetectorHandler.DEFER_IGNORE_PATTERNS),
]


class DismissiveLanguageNitpickHandler(Handler):
    """Detect dismissive language in assistant messages via nitpick pseudo-event.

    Advisory handler that runs as part of the nitpick handler chain.
    Receives pre-extracted assistant_messages from NitpickSetup and scans
    each message for dismissive phrases.

    Non-terminal: accumulates findings as context, never blocks.
    """

    def __init__(self) -> None:
        """Initialise the dismissive language nitpick handler."""
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
        """Scan assistant messages for dismissive language.

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
                        f"Dismissive language detected ({readable}): "
                        f"acknowledge and offer to fix instead of deflecting"
                    )

        return HookResult(decision=Decision.ALLOW, context=context_lines)

    def get_claude_md(self) -> str | None:
        return None

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
                title="nitpick dismissive language - detects deflecting in transcript",
                command='echo "test"',
                description=(
                    "Tests that the nitpick handler detects dismissive language "
                    "like 'pre-existing issue', 'out of scope' in assistant messages "
                    "provided by the NitpickSetup pseudo-event."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"dismissive", r"deflecting"],
                safety_notes="Advisory handler - warns but does not block",
                test_type=TestType.CONTEXT,
                requires_event="Nitpick pseudo-event with assistant_messages",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
