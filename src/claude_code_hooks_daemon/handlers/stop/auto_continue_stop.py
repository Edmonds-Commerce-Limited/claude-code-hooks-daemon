"""AutoContinueStopHandler - True auto-continue without user input.

Intercepts ALL Stop events (except re-entry and AskUserQuestion) and routes
to one of four branches:

1. QA failure: last Bash command was a QA tool and output indicates failure
   -> DENY with "fix failures and continue" message
2. Explicit stop explanation: last assistant message starts with "STOPPING BECAUSE:"
   -> ALLOW (Claude has given a valid reason to stop)
3. Confirmation question (backwards compat): last message contains a
   confirmation-style question (existing auto-continue behaviour)
   -> DENY with auto-continue instruction
4. Default (requires explanation): everything else
   -> DENY with "explain or use STOPPING BECAUSE: prefix" message
   (only when force_explanation=True, the default)
"""

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, ToolName
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.transcript_reader import ContentBlock, TranscriptReader
from claude_code_hooks_daemon.utils.stop_hook_helpers import (
    get_transcript_reader,
    is_stop_hook_active,
)

logger = logging.getLogger(__name__)

# Reason constants — named, no magic strings
_CONFIRMATION_CONTINUE_REASON = (
    "AUTO-CONTINUE: Yes, proceed with all remaining work. "
    "Do not ask for confirmation again. "
    "If a command failed, analyse the error, fix the root cause, and retry. "
    "If you are truly stuck and cannot make progress, you may stop and wait "
    "for human guidance. Otherwise, continue automatically without asking."
)

_QA_FAIL_REASON = (
    "AUTO-CONTINUE: QA failures detected. Do NOT stop — fix the failures and continue. "
    "Analyse each failure, fix the root cause, re-run the QA tool, and proceed. "
    "Only stop (with STOPPING BECAUSE: prefix) once all checks pass."
)

_EXPLAIN_OR_CONTINUE_REASON = (
    "You stopped without explaining why. Either:\n"
    "1. Prefix your stop message with STOPPING BECAUSE: followed by a clear reason "
    "(e.g. 'STOPPING BECAUSE: all tasks complete and QA passes'), or\n"
    "2. Use AUTO-CONTINUE to keep working without asking.\n"
    "Do not stop without a reason — continue working or explain why you stopped."
)


class AutoContinueStopHandler(Handler):
    """Intercept Stop events and enforce explicit stop reasons or auto-continue.

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

    # Error-question patterns — Claude asking what to do about an error.
    # Only matched when continue_on_errors is True.
    ERROR_QUESTION_PATTERNS: ClassVar[list[str]] = [
        r"what would you like me to do",
        r"how should I (?:handle|proceed|fix)",
        r"what do you (?:think|suggest|prefer)",
    ]

    # Patterns that indicate an error or problem — used to gate auto-continue
    # when continue_on_errors is False.
    ERROR_PATTERNS: ClassVar[list[str]] = [
        r"error:",
        r"failed:",
        r"what would you like me to do",
        r"how should I (?:handle|proceed|fix)",
        r"what do you (?:think|suggest|prefer)",
    ]

    # QA tool command patterns — used to detect QA tool runs in Bash history
    _QA_TOOL_PATTERNS: ClassVar[tuple[str, ...]] = (
        "pytest",
        "ruff",
        "mypy",
        "bandit",
        "shellcheck",
        "./scripts/qa/",
        "npm test",
        "npm run test",
        "php artisan test",
        "phpunit",
        "go test",
        "cargo test",
        "bundle exec rspec",
        "./gradlew test",
    )

    # Failure indicators found in QA tool output
    _QA_FAILURE_INDICATORS: ClassVar[tuple[str, ...]] = (
        "FAILED",
        "failed",
        "ERROR",
        "error:",
        "ERRORS",
        "error[",
        "FAIL",
        " fail",
        "failing",
        "failure",
        "passed=0",
        "no tests ran",
    )

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
        """Return True for all Stop events unless re-entry or AskUserQuestion.

        The routing logic (QA failure, stop explanation, confirmation question,
        force explanation) lives entirely in handle(). matches() is a broad
        gate that only excludes:
          - Re-entry loops (stop_hook_active=True)
          - AskUserQuestion tool use (user must see and answer the question)

        Args:
            hook_input: Hook input with transcript_path and stop_hook_active

        Returns:
            False only for re-entry or AskUserQuestion; True for everything else
        """
        # CRITICAL: Prevent infinite loops - check both casing variants
        if is_stop_hook_active(hook_input):
            logger.debug("Stop hook is active (re-entry) - skipping to prevent infinite loop")
            return False

        # Check AskUserQuestion — user must answer, not auto-continue
        reader = get_transcript_reader(hook_input)
        if reader and reader.last_assistant_used_tool(ToolName.ASK_USER_QUESTION):
            logger.info("AskUserQuestion detected - user must answer, not auto-continuing")
            return False

        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Route to the appropriate auto-continue branch.

        Branch 1 - QA failure:
            Last Bash was a QA tool AND result indicates failure -> DENY fix msg.
        Branch 2 - Explicit stop explanation:
            Last assistant text starts with "STOPPING BECAUSE:" -> ALLOW.
        Branch 3 - Confirmation question (backwards compat):
            Text contains a continuation question -> DENY auto-continue msg.
        Branch 4 - Default (requires explanation):
            Everything else -> DENY explain-or-continue msg
            (only when force_explanation=True, the default).

        Args:
            hook_input: Hook input with transcript_path

        Returns:
            HookResult with DENY or ALLOW decision
        """
        reader = get_transcript_reader(hook_input)

        # Branch 1: QA failure
        if reader and self._is_qa_failure(reader):
            logger.info("QA failure detected - instructing Claude to fix and continue")
            result = HookResult(decision=Decision.DENY, reason=_QA_FAIL_REASON)
            self._log_stop_event(hook_input, Decision.DENY, _QA_FAIL_REASON)
            return result

        # Branch 2: Explicit stop explanation
        if reader and self._has_stop_explanation(reader):
            logger.info("STOPPING BECAUSE: prefix detected - allowing stop")
            result = HookResult(decision=Decision.ALLOW)
            self._log_stop_event(hook_input, Decision.ALLOW, "")
            return result

        # Branch 3: Confirmation question (backwards compat)
        if reader:
            last_message = reader.get_last_assistant_text()
            if last_message:
                continue_on_errors = getattr(self, "_continue_on_errors", True)
                has_error = self._contains_error_pattern(last_message)

                is_confirmation = False
                if not (has_error and not continue_on_errors):
                    is_confirmation = self._contains_confirmation_pattern(last_message)
                    if not is_confirmation and has_error and continue_on_errors:
                        is_confirmation = self._contains_error_question_pattern(last_message)

                if is_confirmation and "?" in last_message:
                    logger.info("Confirmation question detected - will auto-continue")
                    result = HookResult(
                        decision=Decision.DENY, reason=_CONFIRMATION_CONTINUE_REASON
                    )
                    self._log_stop_event(hook_input, Decision.DENY, _CONFIRMATION_CONTINUE_REASON)
                    return result

        # Branch 4: Default - require explanation or force continue
        force_explanation = getattr(self, "_force_explanation", True)
        if force_explanation:
            logger.info("No stop explanation provided - requiring STOPPING BECAUSE: or continue")
            result = HookResult(decision=Decision.DENY, reason=_EXPLAIN_OR_CONTINUE_REASON)
            self._log_stop_event(hook_input, Decision.DENY, _EXPLAIN_OR_CONTINUE_REASON)
            return result

        # force_explanation=False: allow stop without explanation
        logger.info("force_explanation=False - allowing stop without explanation")
        result = HookResult(decision=Decision.ALLOW)
        self._log_stop_event(hook_input, Decision.ALLOW, "")
        return result

    def _is_qa_failure(self, reader: TranscriptReader) -> bool:
        """Return True if last Bash was a QA tool and output indicates failure.

        Args:
            reader: Loaded transcript reader

        Returns:
            True if a QA tool ran and its output contains failure indicators
        """
        bash_use: ContentBlock | None = reader.get_last_bash_tool_use()
        if bash_use is None:
            return False
        tool_input = bash_use.tool_input if bash_use.tool_input else {}
        command = tool_input.get("command", "")
        if not any(pat in command for pat in self._QA_TOOL_PATTERNS):
            return False
        result_text = reader.get_last_tool_result_text()
        return any(ind in result_text for ind in self._QA_FAILURE_INDICATORS)

    def _has_stop_explanation(self, reader: TranscriptReader) -> bool:
        """Return True if any line in last assistant message starts with 'STOPPING BECAUSE:'.

        Checks each line individually, stripping leading whitespace, so the prefix
        may appear anywhere in the message (not just at the very start).

        Args:
            reader: Loaded transcript reader

        Returns:
            True if any line starts with the STOPPING BECAUSE: prefix
        """
        last_text = reader.get_last_assistant_text()
        return any(line.lstrip().startswith("STOPPING BECAUSE:") for line in last_text.splitlines())

    def _log_stop_event(self, hook_input: dict[str, Any], decision: Decision, reason: str) -> None:
        """Log stop event to JSONL file for debugging.

        Appends one JSON line to {project_root}/untracked/stop-events.jsonl.
        Silently ignores write errors — this is non-critical logging.

        Args:
            hook_input: Original hook input
            decision: Decision made by the handler
            reason: Reason string (may be empty for ALLOW)
        """
        try:
            untracked_dir: Path = ProjectContext.daemon_untracked_dir()
            log_path = untracked_dir / "stop-events.jsonl"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "decision": decision.value,
                "reason_prefix": reason[:80],
                "stop_hook_active": bool(hook_input.get("stop_hook_active", False)),
            }
            with log_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except (RuntimeError, OSError):
            pass  # Non-critical — ProjectContext not initialised (tests) or file write errors

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

    def _contains_error_question_pattern(self, text: str) -> bool:
        """Check if text contains an error-question pattern.

        These are patterns where Claude is asking how to handle an error,
        e.g. "what would you like me to do?". Only used when continue_on_errors
        is True to auto-continue through error recovery.

        Args:
            text: Text to check

        Returns:
            True if text contains an error-question pattern
        """
        text_lower = text.lower()
        return any(
            re.search(pattern, text_lower, re.IGNORECASE)
            for pattern in self.ERROR_QUESTION_PATTERNS
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
