"""DismissiveLanguageNitpickHandler - Nitpick pseudo-event handler for dismissive language.

Audits assistant messages (provided by NitpickSetup) for dismissive language
patterns that signal the agent is deflecting responsibility instead of fixing issues.

Owns the pattern definitions. They previously lived on a Stop-event twin that
this module imported from, under a comment calling that twin the single source
of truth — but the twin sat behind ``auto_continue_stop`` (priority 10,
terminal) and never ran, so the authoritative copy was the one nothing
executed. This module also imported only FOUR of the five sets, which is why
premature-halt language went undetected in production entirely. Plan 00237
inverted the dependency, wired the fifth set in, and deleted the twin.
"""

from __future__ import annotations

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.utils.quoted_spans import blank_quoted_spans

HANDLER_ID = HandlerID.NITPICK_DISMISSIVE
HANDLER_PRIORITY = Priority.NITPICK_DISMISSIVE

# "Not our problem" - deflecting responsibility for issues
NOT_OUR_PROBLEM_PATTERNS: list[str] = [
    r"\bpre-existing issue\b",
    r"\bpre-existing problem\b",
    r"\bnot caused by (?:our|my) changes?\b",
    r"\bunrelated to (?:our|my|what we're)\b",
    r"\bexisted before (?:our|my) changes\b",
    r"\bwas already (?:there|present|broken|failing)\b",
    r"\bnot (?:our|my) (?:problem|issue|concern|fault|bug)\b",
    r"\bnot something we (?:introduced|caused|broke)\b",
    r"\bnot (?:introduced|caused|created) by (?:our|my) changes?\b",
    r"\bnot (?:related|due) to (?:our|my) changes?\b",
    r"\bnothing to do with (?:our|my) changes?\b",
    r"\bnot a result of (?:our|my) changes?\b",
    r"\bnot from (?:our|my) changes?\b",
    r"\bno issues with (?:our|my)\b",
    r"\b(?:our|my) (?:code|implementation|changes?) (?:is|are) correct\b",
]

# "Out of scope" - arbitrarily scoping out encountered issues
OUT_OF_SCOPE_PATTERNS: list[str] = [
    r"\boutside (?:the )?scope of\b",
    r"\bbeyond (?:the )?scope of\b",
    r"\bout of scope\b",
    r"\bseparate concern\b",
    r"\bseparate issue\b",
    r"\bnot (?:within|in) scope\b",
    r"\bfalls outside\b",
]

# "Someone else's job" - pushing work to others
SOMEONE_ELSES_JOB_PATTERNS: list[str] = [
    r"\bnot (?:our|my) (?:responsibility|work|task|job)\b",
    r"\bnot (?:my|our) (?:area|domain)\b",
    r"\bdifferent task entirely\b",
    r"\ba different (?:effort|initiative|project)\b",
    r"\bnot what we're (?:here|working on|doing|tasked)\b",
]

# "Defer/ignore" - putting off issues instead of fixing them
DEFER_IGNORE_PATTERNS: list[str] = [
    r"\bcan be (?:addressed|fixed|handled|resolved) (?:later|separately)\b",
    r"\bleave (?:that|this|it) for (?:now|later)\b",
    r"\btackle (?:that|this) separately\b",
    r"\bdefer (?:that|this) (?:to|for)\b",
    r"\bnot worth (?:fixing|addressing|worrying)\b",
    r"\bignore (?:that|this) for now\b",
    r"\bbest left (?:alone|as-is)\b",
    r"\blet's not (?:worry|concern ourselves) (?:about|with)\b",
]

# "Premature stop" - dressing up a mid-task halt as a principled pause.
# The agent uses these phrases to quit partway through a multi-step plan
# without actually finishing the next task. "Natural checkpoint",
# "logical stopping point", "clean break" etc. are thin cover for:
# "I've done some work, now I want you to explicitly tell me to continue."
# When the user has issued an auto-continue / proceed directive, these
# phrases are a direct violation — surface them and challenge explicitly.
PREMATURE_STOP_PATTERNS: list[str] = [
    r"\bnatural (?:checkpoint|stopping point|pause|pausing point|break)\b",
    r"\blogical (?:checkpoint|stopping point|pause|pausing point|break)\b",
    r"\bclean (?:checkpoint|break)\b",
    r"\bgood (?:pausing point|place to pause|stopping point|time to stop)\b",
    r"\bpausing here\b",
    r"\bready to continue (?:on your cue|when you'?re ready|at your signal)\b",
    r"\bawait(?:ing)? (?:your|further) (?:instruction|direction|signal|cue|go-?ahead)\b",
]

# Category name -> pattern list
_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("not_our_problem", NOT_OUR_PROBLEM_PATTERNS),
    ("out_of_scope", OUT_OF_SCOPE_PATTERNS),
    ("someone_elses_job", SOMEONE_ELSES_JOB_PATTERNS),
    ("defer_ignore", DEFER_IGNORE_PATTERNS),
    ("premature_stop", PREMATURE_STOP_PATTERNS),
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
        # Dedupe by category (Plan 00146): one advisory line per category, no
        # matter how many patterns or messages match it. Without this, a single
        # 'out of scope' discussion emitted one identical line per matching
        # pattern per message — six duplicates observed in one advisory.
        found_categories: dict[str, None] = {}

        for msg in messages:
            text = msg.get("content", "")
            if not text:
                continue
            # Scan a copy with quoted spans blanked (Plan 00225): a QUOTED
            # phrase is being mentioned, not used to deflect. The advisory asks
            # the agent to acknowledge rather than deflect, and naming the
            # phrase is how one acknowledges — so complying re-fired it. The
            # patterns are unchanged; only the scanned text is normalised, so a
            # real trigger elsewhere in the same message is still found.
            scan_target = blank_quoted_spans(text)
            for category, compiled in self._compiled:
                if category not in found_categories and compiled.search(scan_target):
                    found_categories[category] = None

        context_lines = [
            f"Dismissive language detected ({category.replace('_', ' ')}): "
            f"acknowledge and offer to fix instead of deflecting"
            for category in found_categories
        ]

        return HookResult(decision=Decision.ALLOW, context=context_lines)

    def get_claude_md(self) -> str | None:
        return (
            "## nitpick.dismissive_language — do not deflect or prematurely halt\n\n"
            "Your messages are scanned for language patterns signalling avoidance of "
            "work. The handler does NOT block anything, but injects context so you "
            "self-correct. Identical advisories (same session, same phrase set) are "
            "emitted once, not repeated.\n\n"
            "**Avoid**:\n\n"
            "- Dismissing issues as `pre-existing`, `out of scope`, `not our problem`, "
            "  or `not relevant` to deflect work that is in fact yours.\n"
            "- Premature-halt phrasing like `natural checkpoint`, `ready to continue on your "
            "  cue`, `pausing here`, `awaiting your instruction` mid-plan when there is "
            "  more to do — finish the task rather than dressing up a halt.\n"
            "- Speculative `should be fine` or `probably works` when verification is "
            "  cheap (run the test, read the file).\n\n"
            "**Do**: acknowledge the issue, fix it, or — if it genuinely is out of scope — "
            "say so once with the specific reason and continue with the in-scope work.\n\n"
            "**A QUOTED phrase is a mention, not a deflection.** Naming the phrase is how "
            "you acknowledge it, so quoting one never re-fires the advisory."
        )

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
