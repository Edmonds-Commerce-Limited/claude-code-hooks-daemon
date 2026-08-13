"""HedgingLanguageNitpickHandler - Nitpick pseudo-event handler for hedging language.

Audits assistant messages (provided by NitpickSetup) for hedging language
patterns that signal the agent is guessing instead of researching with tools.

Owns the pattern definitions. They previously lived on a Stop-event twin that
this module imported from, under a comment calling that twin the single source
of truth — but the twin sat behind ``auto_continue_stop`` (priority 10,
terminal) and never ran, so the authoritative copy was the one nothing
executed. Plan 00237 inverted the dependency and deleted the twin.
"""

from __future__ import annotations

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.utils.quoted_spans import blank_quoted_spans

HANDLER_ID = HandlerID.NITPICK_HEDGING
HANDLER_PRIORITY = Priority.NITPICK_HEDGING

# Memory-based guessing - agent relying on recall instead of looking
MEMORY_PATTERNS: list[str] = [
    r"\bif I recall\b",
    r"\bIIRC\b",
    r"\bfrom memory\b",
    r"\bif memory serves\b",
    r"\bfrom what I remember\b",
]

# Uncertainty hedging - agent unsure about verifiable facts
UNCERTAINTY_PATTERNS: list[str] = [
    r"\bshould probably\b",
    r"\blikely\b",
    r"\bprobably\b",
    r"\bapparently\b",
    r"\bseemingly\b",
    r"\bpossibly\b",
    r"\bmost likely\b",
    r"\bpresumably\b",
    r"\bI assume\b",
    r"\bI believe\b",
    r"\bI suspect\b",
]

# Weak confidence - agent hedging on things it could verify
WEAK_CONFIDENCE_PATTERNS: list[str] = [
    r"\bI'm not sure but\b",
    r"\bI'm fairly confident\b",
    r"\bI'm pretty sure\b",
    r"\bit seems like\b",
    r"\bmight be\b",
    r"\bcould be\b",
]

# Category name -> pattern list
_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("memory_guessing", MEMORY_PATTERNS),
    ("uncertainty", UNCERTAINTY_PATTERNS),
    ("weak_confidence", WEAK_CONFIDENCE_PATTERNS),
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
        # Dedupe by category (Plan 00146): one advisory line per category, no
        # matter how many patterns or messages match it — mirrors the
        # dismissive nitpick handler's duplicate-spam fix.
        found_categories: dict[str, None] = {}

        for msg in messages:
            text = msg.get("content", "")
            if not text:
                continue
            # Scan a copy with quoted spans blanked (Plan 00225): a QUOTED
            # hedge is being mentioned, not asserted. The advisory tells the
            # agent to verify rather than guess, and naming the hedge is how
            # one reports having done so — so complying re-fired it. The
            # patterns are unchanged; only the scanned text is normalised.
            scan_target = blank_quoted_spans(text)
            for category, compiled in self._compiled:
                if category not in found_categories and compiled.search(scan_target):
                    found_categories[category] = None

        context_lines = [
            f"Hedging language detected ({category.replace('_', ' ')}): "
            f"use tools to verify instead of guessing"
            for category in found_categories
        ]

        return HookResult(decision=Decision.ALLOW, context=context_lines)

    def get_claude_md(self) -> str | None:
        return """## nitpick.hedging_language — the guessing is the defect, not the wording

Your messages are scanned for hedges — "if I recall", "IIRC", "from memory",
"probably", "likely", "apparently", "presumably", "I believe" — and a
non-blocking advisory is injected.

**Do not respond by deleting the word.** Dropping "probably" while still
guessing is worse than the hedge: it removes the only signal that the claim
was unverified, and leaves a confident-sounding sentence with nothing behind
it. The remedy is to verify — `Read` the file, `Grep` the codebase, `Glob` for
the name, run the command. Almost every hedge in this repository is about
something one tool call would settle.

**Honest uncertainty is fine — say it plainly, and say what would settle it.**
"I have not checked whether X still exists" is accurate reporting, not
hedging. What this handler is looking for is confident prose standing in for a
check you could have made.

**A QUOTED phrase is a mention, not a hedge.** Naming the phrase is how you
acknowledge it, so quoting one never re-fires the advisory.

The sibling `nitpick.dismissive_language` covers the same ground for
avoidance rather than uncertainty."""

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
