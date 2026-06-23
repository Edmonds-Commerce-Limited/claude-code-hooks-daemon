"""DismissiveLanguageDetectorHandler - Detects deflecting instead of fixing.

Scans the last assistant message in the transcript for dismissive language
that signals the agent is avoiding work by labelling issues as "pre-existing",
"out of scope", or "someone else's problem" instead of offering to fix them.

Detected patterns:
- Not our problem: "pre-existing issue", "not caused by our changes", "was already broken",
  "not introduced by my change", "no issues with my code", "my code is correct"
- Out of scope: "outside the scope of", "out of scope", "separate issue"
- Someone else's job: "not our responsibility", "different task entirely"
- Defer/ignore: "can be addressed later", "not worth fixing", "best left alone"
- Premature stop: "natural checkpoint", "logical stopping point", "clean break",
  "good pausing point", "pausing here", "ready to continue on your cue" — used to
  quit partway through a multi-step plan when an auto-continue / proceed directive
  is active
"""

import logging
import re
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.utils.stop_hook_helpers import (
    get_transcript_reader,
    is_stop_hook_active,
)

logger = logging.getLogger(__name__)

HANDLER_ID = HandlerID.DISMISSIVE_LANGUAGE_DETECTOR
HANDLER_PRIORITY = Priority.DISMISSIVE_LANGUAGE_DETECTOR


class DismissiveLanguageDetectorHandler(Handler):
    """Detect dismissive language that signals avoiding work.

    Advisory handler that fires on Stop events. Reads the transcript to
    check the last assistant message for dismissive phrases. When detected,
    injects a warning telling the agent to acknowledge and offer to fix
    issues instead of deflecting.

    Non-terminal: does not block the stop, only injects context.
    """

    # "Not our problem" - deflecting responsibility for issues
    NOT_OUR_PROBLEM_PATTERNS: ClassVar[list[str]] = [
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
    OUT_OF_SCOPE_PATTERNS: ClassVar[list[str]] = [
        r"\boutside (?:the )?scope of\b",
        r"\bbeyond (?:the )?scope of\b",
        r"\bout of scope\b",
        r"\bseparate concern\b",
        r"\bseparate issue\b",
        r"\bnot (?:within|in) scope\b",
        r"\bfalls outside\b",
    ]

    # "Someone else's job" - pushing work to others
    SOMEONE_ELSES_JOB_PATTERNS: ClassVar[list[str]] = [
        r"\bnot (?:our|my) (?:responsibility|work|task|job)\b",
        r"\bnot (?:my|our) (?:area|domain)\b",
        r"\bdifferent task entirely\b",
        r"\ba different (?:effort|initiative|project)\b",
        r"\bnot what we're (?:here|working on|doing|tasked)\b",
    ]

    # "Defer/ignore" - putting off issues instead of fixing them
    DEFER_IGNORE_PATTERNS: ClassVar[list[str]] = [
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
    PREMATURE_STOP_PATTERNS: ClassVar[list[str]] = [
        r"\bnatural (?:checkpoint|stopping point|pause|pausing point|break)\b",
        r"\blogical (?:checkpoint|stopping point|pause|pausing point|break)\b",
        r"\bclean (?:checkpoint|break)\b",
        r"\bgood (?:pausing point|place to pause|stopping point|time to stop)\b",
        r"\bpausing here\b",
        r"\bready to continue (?:on your cue|when you'?re ready|at your signal)\b",
        r"\bawait(?:ing)? (?:your|further) (?:instruction|direction|signal|cue|go-?ahead)\b",
    ]

    def __init__(self) -> None:
        """Initialise the dismissive language detector handler."""
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
            self.NOT_OUR_PROBLEM_PATTERNS
            + self.OUT_OF_SCOPE_PATTERNS
            + self.SOMEONE_ELSES_JOB_PATTERNS
            + self.DEFER_IGNORE_PATTERNS
            + self.PREMATURE_STOP_PATTERNS
        ):
            self._all_patterns.append((pattern_str, re.compile(pattern_str, re.IGNORECASE)))

    def _get_last_assistant_message(self, transcript_path: str) -> str:
        """Read transcript and extract the last assistant message text.

        Uses shared get_transcript_reader() utility for loading,
        then delegates to TranscriptReader.get_last_assistant_text().

        Args:
            transcript_path: Path to the JSONL transcript file

        Returns:
            Text content of the last assistant message, or empty string
        """
        reader = get_transcript_reader({HookInputField.TRANSCRIPT_PATH: transcript_path})
        if not reader:
            return ""
        return reader.get_last_assistant_text()

    def _find_dismissive_phrases(self, text: str) -> list[str]:
        """Find all dismissive phrases in the given text.

        Args:
            text: Text to scan for dismissive language

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
        """Check if the last assistant message contains dismissive language.

        Args:
            hook_input: Hook input with transcript_path

        Returns:
            True if dismissive language detected in last assistant message
        """
        # Prevent infinite loops on re-entry
        if is_stop_hook_active(hook_input):
            logger.debug("Stop hook active (re-entry) - skipping dismissive check")
            return False

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if not transcript_path:
            logger.debug("No transcript_path in hook_input - cannot check for dismissive language")
            return False

        last_message = self._get_last_assistant_message(str(transcript_path))
        if not last_message:
            logger.debug("No assistant message found in transcript")
            return False

        phrases = self._find_dismissive_phrases(last_message)
        if phrases:
            logger.info(
                "Dismissive language detected: %s",
                ", ".join(phrases),
            )
            return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return advisory warning about dismissive language.

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
                phrases = self._find_dismissive_phrases(last_message)

        if phrases:
            phrase_list = ", ".join(f'"{p}"' for p in phrases)
            premature_readable = {p.replace(r"\b", "") for p in self.PREMATURE_STOP_PATTERNS}
            premature_stop_hit = any(p in premature_readable for p in phrases)
            if premature_stop_hit:
                context = (
                    f"PREMATURE-STOP LANGUAGE DETECTED: {phrase_list}\n"
                    "\n"
                    'Phrases like "natural checkpoint" / "logical stopping point" /\n'
                    '"clean break" / "ready to continue on your cue" are thin cover\n'
                    "for stopping mid-plan. They describe YOUR comfort, not the task.\n"
                    "\n"
                    "If an auto-continue / proceed directive is active, or the\n"
                    "current plan has more tasks queued, you must NOT stop here.\n"
                    "Keep going. Commit at real checkpoints (passing tests, completed\n"
                    "task) without announcing them as reasons to halt.\n"
                    "\n"
                    "If you genuinely need user input, say exactly what you need\n"
                    "('I need X to proceed') instead of dressing it up as a pause."
                )
            else:
                context = (
                    f"DISMISSIVE LANGUAGE DETECTED: {phrase_list}\n"
                    "\n"
                    "Don't dismiss issues as someone else's problem.\n"
                    "If you encountered an error, test failure, or quality issue:\n"
                    "\n"
                    "  1. ACKNOWLEDGE the problem clearly\n"
                    '  2. ASK the user: "I found [issue]. Want me to fix it?"\n'
                    "  3. NEVER assume it's pre-existing or out of scope without evidence\n"
                    "\n"
                    "The user expects you to FIX problems, not explain them away.\n"
                    "Only defer if the user explicitly asks you to stay focused on something else."
                )
        else:
            context = (
                "DISMISSIVE LANGUAGE WARNING: Your response dismissed an issue.\n"
                "ACKNOWLEDGE problems and offer to FIX them instead of deflecting."
            )

        return HookResult(decision=Decision.ALLOW, context=[context])

    def get_claude_md(self) -> str | None:
        return (
            "## dismissive_language_detector — do not deflect or prematurely halt\n\n"
            "Stop-time advisory that fires on language patterns signalling avoidance of "
            "work. The handler does NOT block the stop, but injects context for the next "
            "turn so the agent self-corrects.\n\n"
            "**Avoid**:\n\n"
            "- Dismissing issues as `pre-existing`, `out of scope`, `not our problem`, "
            "  or `not relevant` to deflect work that is in fact yours.\n"
            "- Premature-halt phrasing like `natural checkpoint`, `ready to continue on your "
            "  cue`, `pausing here` mid-plan when there is more to do — finish the task "
            "  rather than dressing up a halt.\n"
            "- Speculative `should be fine` or `probably works` when verification is "
            "  cheap (run the test, read the file).\n\n"
            "**Do**: acknowledge the issue, fix it, or — if it genuinely is out of scope — "
            "say so once with the specific reason and continue with the in-scope work."
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
                title="dismissive language detector - detects deflecting phrases",
                command='echo "test"',
                description=(
                    "Tests that the handler detects dismissive language like "
                    "'pre-existing issue', 'out of scope', 'not our problem' "
                    "in assistant messages and injects a warning to fix issues "
                    "instead of dismissing them."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"dismissive", r"fix"],
                safety_notes="Advisory handler - warns but does not block",
                test_type=TestType.CONTEXT,
                requires_event="Stop event with transcript_path",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
