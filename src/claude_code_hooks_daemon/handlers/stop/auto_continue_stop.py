"""AutoContinueStopHandler - True auto-continue without user input.

Intercepts ALL Stop events (except re-entry and AskUserQuestion) and routes
to one of five branches:

1. QA failure: last Bash command was a QA tool and output indicates failure
   -> DENY with "fix failures and continue" message
2. Explicit stop explanation: last assistant message starts with "STOPPING BECAUSE:"
   -> ALLOW (Claude has given a valid reason to stop)
2.5. tool_use_error recovery (Plan 00101 Phase 6): last tool_result has
   is_error=true and no STOPPING BECAUSE: was provided
   -> DENY with specific recovery instruction (Read the file + retry)
3. Confirmation question (backwards compat): last message contains a
   confirmation-style question (existing auto-continue behaviour)
   -> DENY with auto-continue instruction
4. Default (requires explanation): everything else
   -> DENY with "explain or use STOPPING BECAUSE: prefix" message
   (only when force_explanation=True, the default)
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from pathlib import Path

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, ToolName
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.transcript_reader import (
    ContentBlock,
    TranscriptMessage,
    TranscriptReader,
)
from claude_code_hooks_daemon.utils.stop_hook_helpers import (
    get_transcript_reader,
    has_recent_stop_hook_block,
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
    "Do not stop without a reason — continue working or explain why you stopped.\n\n"
    "DO NOT STOP because the context window is getting full. Claude Code's "
    "auto-compact triggers automatically when the context-usage threshold is "
    "crossed and preserves the conversation state for you. Voluntarily stopping "
    "to 'checkpoint' before compaction wastes a turn and delays the user's work. "
    "If you are tempted to stop because context is high, keep working instead — "
    "auto-compact will handle context pressure on its own."
)

_TOOL_ERROR_RECOVERY_REASON = (
    "TOOL ERROR RECOVERY: Your last tool_use returned a tool_use_error and "
    "you stopped without recovering. Do NOT stop after a tool error — "
    "the correct action is to address the cause and retry.\n\n"
    "Common pattern: Edit/Write failed because the file was not read first "
    "(e.g. 'File has not been read yet'). Recovery: Read the file, then "
    "retry the Edit/Write in the same turn.\n\n"
    "Examine the tool_use_error text, address its specific cause, then "
    "retry. Only stop (with STOPPING BECAUSE: prefix) once recovery is "
    "genuinely impossible."
)

# Prefix an assistant message uses to signal an intentional, explained stop.
_STOP_EXPLANATION_PREFIX = "STOPPING BECAUSE:"

# Turn-freshness threshold. Real Claude Code stamps each transcript entry at
# completion, so a genuine current-turn final assistant message is ~0s old when
# the Stop hook fires, whereas a stale previous-turn tail (whose fresh content
# has not flushed yet) is seconds+ old. A complete tail older than this is
# treated as suspect and triggers a re-read poll for the real current content.
_STALE_TAIL_THRESHOLD_SECONDS = 4.0

# Poll budget used to wait for the current turn's assistant text to flush.
_HAS_EXPLANATION_RETRY_ATTEMPTS = 6
_HAS_EXPLANATION_RETRY_DELAY_SECONDS = 0.1


def _parse_iso_timestamp(value: object) -> datetime | None:
    """Parse an ISO-8601 transcript timestamp into a tz-aware datetime.

    Accepts a trailing ``Z`` (UTC designator) and explicit offsets. Returns
    None for missing/non-string/unparseable values. A tz-naive timestamp is
    assumed to be UTC (never left naive) so age arithmetic is always valid.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # A malformed timestamp means "age unknown", a valid domain outcome
        # (not a swallowed error) — surface it at debug and fall through.
        logger.debug("Ignoring unparseable transcript timestamp: %r", value)
        parsed = None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _message_age_seconds(msg: TranscriptMessage, now: datetime) -> float | None:
    """Return how many seconds ago ``msg`` was written, or None if unknowable.

    Reads the entry-level ``timestamp`` (present in real Claude Code
    transcripts, absent in synthetic/legacy ones). None means "cannot judge
    staleness"; callers treat that as not-stale for backward compatibility.
    """
    raw = msg.raw or {}
    written = _parse_iso_timestamp(raw.get("timestamp"))
    if written is None:
        return None
    return (now - written).total_seconds()


def _message_has_text(msg: TranscriptMessage) -> bool:
    """Return True if the message carries any text content."""
    return bool(msg.content) or any(
        block.block_type == "text" and block.text for block in msg.content_blocks
    )


def _transcript_last_is_assistant(reader: TranscriptReader) -> bool:
    """Return True if the most recent message in the transcript is from assistant."""
    messages = reader.get_messages()
    return bool(messages) and messages[-1].role == "assistant"


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

    # Anchored / structured failure signals in QA tool output.
    #
    # Each entry is a regex matched (case-sensitive unless the pattern says
    # otherwise) against the QA tool's OWN result text. Bare substrings like
    # "failure"/"failing"/" fail" are deliberately NOT used: verbose passing
    # output routinely contains them (e.g. a passing test named
    # "test_failure_recovery PASSED" contains "failure"), which previously
    # misclassified a fully-passing run as a failure and DENY-looped the agent.
    # We only match structured signals that genuinely denote failure.
    _QA_FAILURE_PATTERNS: ClassVar[tuple[str, ...]] = (
        r"\b[1-9]\d* failed\b",  # pytest "N failed" (N >= 1)
        r"\b[1-9]\d* errors?\b",  # mypy/ruff "N error(s)" (N >= 1)
        r"==+ FAILURES ==+",  # pytest failures banner
        r"==+ ERRORS ==+",  # pytest errors banner
        r"^FAILED\b",  # pytest per-test FAILED line (line-anchored)
        r"^ERROR\b",  # pytest per-test ERROR line (line-anchored)
        r":\s*FAILED\b",  # QA summary "Check : FAILED"
        r"Overall Status\s*:\s*FAILED",  # run_all.sh overall status
        r"\bno tests ran\b",  # pytest collected nothing
        r"\bpassed=0\b",  # zero tests passed
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
        # Config flags — declared and initialised here so mypy can verify them
        # and a typo in a config setter surfaces as a normal attribute rather
        # than silently falling back to a getattr default (fail-fast).
        self._continue_on_errors: bool = True
        self._force_explanation: bool = True

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
        # Discriminate genuine re-entry from silent-stop bug:
        # - Genuine re-entry: stop_hook_active=True AND a prior Stop block marker
        #   exists in the transcript tail (Claude Code re-fired Stop after we
        #   denied) — skip to avoid an infinite loop.
        # - Silent-stop bug: stop_hook_active=True but NO prior block marker —
        #   Claude Code spuriously set the flag after a tool error or empty turn.
        #   Treat as a normal Stop and run the routing logic.
        if is_stop_hook_active(hook_input):
            transcript_path = hook_input.get("transcript_path")
            if has_recent_stop_hook_block(transcript_path):
                logger.debug("Stop hook re-entry confirmed by transcript block marker - skipping")
                return False
            logger.info(
                "stop_hook_active=true but no prior block marker — silent-stop bug,"
                " treating as fresh Stop event"
            )

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
        Branch 2.5 - tool_use_error recovery (Plan 00101 Phase 6):
            Last tool_result has is_error=true and no STOPPING BECAUSE: was
            given -> DENY with specific recovery instruction (Read + retry).
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

        # Branch 2.5: tool_use_error recovery (Plan 00101 Phase 6)
        # Last tool_result has is_error=true and the agent did NOT explain.
        # Emit a specific recovery instruction (Read + retry) instead of the
        # generic explain-or-continue default. Branch 2 wins if STOPPING
        # BECAUSE: was provided, so this only fires on a genuine silent
        # stop after a tool error.
        if reader and reader.last_tool_result_was_error():
            logger.info("tool_use_error detected with no recovery - emitting recovery reason")
            result = HookResult(decision=Decision.DENY, reason=_TOOL_ERROR_RECOVERY_REASON)
            self._log_stop_event(hook_input, Decision.DENY, _TOOL_ERROR_RECOVERY_REASON)
            return result

        # Branch 3: Confirmation question (backwards compat)
        # Reload reader — the original from handle() entry may be stale.
        # Branch 2's retry logic reloads internally but doesn't propagate back.
        # By this point the transcript is more likely to have been flushed.
        reader = get_transcript_reader(hook_input)
        if reader:
            last_message = reader.get_last_assistant_text()
            if last_message:
                continue_on_errors = self._continue_on_errors
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
        force_explanation = self._force_explanation
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
        """Return True if the last QA Bash command's OWN result indicates failure.

        The Bash tool_use is paired with ITS tool_result by tool_use_id so a
        non-Bash tool that ran afterwards cannot cause QA detection to inspect
        an unrelated result. Failure is decided by anchored/structured signals
        (see _QA_FAILURE_PATTERNS), never by bare substrings that also appear
        in passing verbose output.

        Args:
            reader: Loaded transcript reader

        Returns:
            True if a QA tool ran and its own result contains a failure signal
        """
        bash_use: ContentBlock | None = reader.get_last_bash_tool_use()
        if bash_use is None:
            return False
        tool_input = bash_use.tool_input if bash_use.tool_input else {}
        command = tool_input.get("command", "")
        if not any(pat in command for pat in self._QA_TOOL_PATTERNS):
            return False

        # Pair the Bash tool_use with its OWN result by id. Fall back to the
        # latest tool_result only when the tool_use carries no id (legacy
        # transcripts) — pairing by id is the correct, unambiguous path.
        tool_use_id = bash_use.raw.get("id", "") if bash_use.raw else ""
        result_text: str | None = reader.get_tool_result_text_by_id(tool_use_id)
        if result_text is None:
            result_text = reader.get_last_tool_result_text()

        return self._result_indicates_failure(result_text)

    def _result_indicates_failure(self, result_text: str) -> bool:
        """Return True if QA result text matches any structured failure signal.

        Args:
            result_text: The QA tool's own result text

        Returns:
            True if any anchored failure pattern matches
        """
        return any(
            re.search(pattern, result_text, re.MULTILINE) for pattern in self._QA_FAILURE_PATTERNS
        )

    def _has_stop_explanation(self, reader: TranscriptReader) -> bool:
        """Return True if the CURRENT turn's assistant message explains the stop.

        Checks each content block independently to avoid false negatives from block
        joining. When TranscriptReader joins multiple text blocks with ' ' (space),
        'STOPPING BECAUSE:' at the start of a later block ends up mid-line in the
        joined string and the startswith check fails. Checking per-block preserves
        the original line boundaries. Falls back to the joined content string for
        legacy/string-format messages.

        Turn-freshness — the hard part. When the Stop hook fires, Claude Code may
        not have flushed the current turn's assistant text. Reading the transcript
        then can return the WRONG turn's message, in one of two shapes:

        1. Incomplete tail: the current turn's text is not written yet (thinking
           only, or the last entry is the user's prompt). ``complete`` is False.
        2. Stale-but-complete tail: NEITHER the new user prompt NOR the new
           assistant response has flushed, so the tail is the PREVIOUS turn's
           COMPLETE message. ``complete`` is True but its entry ``timestamp`` is
           old. This is the window that produced the "double STOPPING BECAUSE:"
           report — the previous fix only detected shape 1.

        Both shapes trigger a bounded re-read poll for the real current-turn
        content. A complete tail with a recent timestamp is trusted immediately
        (the common case), so normal stops incur no extra latency.

        Known residual: on a transcript with NO entry timestamps (synthetic/legacy
        only — real Claude Code always stamps entries) a fully-unflushed stale tail
        cannot be told apart from a genuine current message. The complete fix would
        be a turn-correlation id passed on the Stop ``hook_input``, which Claude
        Code does not currently provide.

        Args:
            reader: Loaded transcript reader

        Returns:
            True if any line in any text block of the CURRENT turn starts with
            the STOPPING BECAUSE: prefix
        """
        msg = reader.get_last_assistant_message()
        if not msg:
            return False

        def _line_starts_with_prefix(text: str) -> bool:
            return any(
                line.lstrip().startswith(_STOP_EXPLANATION_PREFIX) for line in text.splitlines()
            )

        def _check_msg(m: TranscriptMessage) -> bool:
            for block in m.content_blocks:
                if block.block_type == "text" and block.text:
                    if _line_starts_with_prefix(block.text):
                        return True
            return _line_starts_with_prefix(m.content)

        # A "complete" tail is the last transcript entry AND already carries text.
        complete = _message_has_text(msg) and _transcript_last_is_assistant(reader)

        # A complete tail older than the freshness threshold is a suspected stale
        # previous-turn message (shape 2). age is None when the entry carries no
        # timestamp — treated as not-stale for backward compatibility.
        age = _message_age_seconds(msg, datetime.now(tz=UTC))
        suspect_stale = complete and age is not None and age > _STALE_TAIL_THRESHOLD_SECONDS

        if complete and not suspect_stale:
            return _check_msg(msg)

        # Poll for the current turn's content. From a complete-but-stale tail we
        # only accept a DIFFERENT (newer-uuid) assistant message; from an
        # incomplete tail any complete assistant message qualifies.
        previous_uuid = msg.uuid if complete else None
        fresh = self._await_fresh_assistant_message(reader, previous_uuid)
        if fresh is not None:
            return _check_msg(fresh)

        # Nothing newer arrived within the budget — cannot verify that an
        # explanation belongs to THIS stop, so do not satisfy the gate. A
        # genuinely delayed stop re-fires and is re-evaluated once its fresh,
        # recent message lands; trusting the possibly-stale tail is exactly the
        # misread this guard exists to prevent.
        return False

    def _await_fresh_assistant_message(
        self, reader: TranscriptReader, previous_uuid: str | None
    ) -> TranscriptMessage | None:
        """Poll the transcript for the current turn's complete assistant message.

        Reloads the transcript up to a bounded number of times, waiting briefly
        between reads, to let Claude Code finish flushing the current turn. A
        candidate qualifies only when it is the last transcript entry and carries
        text; when we began from a complete-but-stale tail it must additionally
        have a different uuid from that stale message (i.e. genuinely newer
        content). Returns None if no qualifying message appears within the budget.

        Args:
            reader: The reader whose transcript path is polled
            previous_uuid: The uuid of the suspected-stale tail to supersede, or
                None when starting from an incomplete tail (any complete message
                qualifies)

        Returns:
            The fresh assistant message, or None if none appeared in time
        """
        transcript_path = getattr(reader, "_path", None)
        if not transcript_path:
            return None
        for _ in range(_HAS_EXPLANATION_RETRY_ATTEMPTS):
            time.sleep(_HAS_EXPLANATION_RETRY_DELAY_SECONDS)
            retry_reader = TranscriptReader()
            retry_reader.load(transcript_path)
            candidate = retry_reader.get_last_assistant_message()
            if candidate is None:
                continue
            if not (_message_has_text(candidate) and _transcript_last_is_assistant(retry_reader)):
                continue
            if previous_uuid is not None and candidate.uuid == previous_uuid:
                # Same stale message still at the tail — keep waiting.
                continue
            return candidate
        return None

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
        except (RuntimeError, OSError) as e:
            logger.debug("_log_stop_event: non-critical write failure: %s", e)

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

    def get_claude_md(self) -> str | None:
        """Return CLAUDE.md guidance about the stop explanation requirement."""
        return (
            "### Stop Explanation Required\n\n"
            "Before stopping, **prefix your final message** with `STOPPING BECAUSE:` "
            "followed by a clear reason:\n\n"
            "```\n"
            "STOPPING BECAUSE: all tasks complete, QA passes, daemon restart verified.\n"
            "```\n\n"
            "**Why**: The stop hook enforces intentional stops. Stopping without an "
            "explanation triggers an auto-block that asks you to explain or continue.\n\n"
            "**Alternatives**:\n"
            "- `STOPPING BECAUSE: <reason>` — stops cleanly with explanation\n"
            "- Continue working — no need to stop unless all work is genuinely complete\n\n"
            "**Do NOT**:\n"
            "- Stop mid-task without explanation\n"
            "- Ask confirmation questions and then stop (the hook auto-continues those)\n"
            "- Use `AUTO-CONTINUE` unless you intend to keep working indefinitely\n\n"
            "**Before asking a question, evaluate it critically**:\n"
            "- Tautological/rhetorical questions with obvious answers "
            '("Should I continue?", "Would you like me to proceed?") '
            "— do NOT ask, just do it\n"
            "- Errors with a clear next step "
            '("The test failed, should I fix it?") '
            "— do NOT ask, just fix it\n"
            "- Genuine choice questions where all options are valid "
            '("Which of A, B, or C should we use?") '
            "— these deserve a response. Use "
            "`STOPPING BECAUSE: need user input` and ask your question\n\n"
            "**Recovering from a `tool_use_error` — do NOT stop silently**:\n\n"
            "Some tool errors require an explicit recovery action, not a halt. "
            "The most common shape:\n"
            "- You call `Edit` or `Write` on a file you have not yet read.\n"
            "- Claude Code returns a `tool_use_error` (e.g. "
            '"File has not been read yet").\n'
            "- The correct recovery is **Read the file, then retry Edit/Write** — "
            "**do not stop**. Stopping silently after a tool error triggers a "
            "Stop-hook re-entry loop and wastes a turn.\n\n"
            "**Rule: Read before Edit/Write.** If you must edit a file you have not "
            "read, Read it first in the same turn. The daemon's Stop handler will "
            "detect a `tool_use_error` followed by a silent stop and re-fire to "
            "force recovery.\n\n"
            "**On Stop hook re-entry (the hook fires again after a prior block)**: "
            "your next response is treated like any other — it must either prefix "
            "with `STOPPING BECAUSE:` or continue the work. Re-entry does not "
            "exempt you from the explanation rule."
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
