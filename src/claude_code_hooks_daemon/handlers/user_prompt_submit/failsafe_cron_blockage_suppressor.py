"""FailsafeCronBlockageSuppressorHandler - zero-token cadence for a stably
human-input-blocked session (Plan 00298).

The failsafe recovery cron (``recovery_cron_advisor``) fires the canonical
cron prompt hourly while the REPL is idle, to recover from EXTERNAL
interruptions (API error, rate limit, 5-hour usage limit, network failure). A
session that is blocked ONLY on human input is not that state -- every tick
against it is a guaranteed no-op that still costs one full model turn (prompt
in, generation out, transcript write, stop-hook round trip) for nothing.

This handler is the ``UserPromptSubmit`` half of the design: it recognises a
DELIVERED canonical-cron-prompt tick and, when ``auto_continue_stop`` has
recorded a still-valid "blocked only on human input" marker for THIS session,
blocks the prompt before it ever reaches the model (Claude Code's documented
``UserPromptSubmit`` "block" behaviour -- the prompt is dropped, not
forwarded). That is genuinely zero-token, unlike a convention/prompt-text
backoff which still costs a turn to read and act on.

**Minimal by design (owner ruling, Plan 00298 BRAINSTORM.md: "sounds complex
and brittle to me").** One marker, one session-scoped validity check, no
fallback chains. See ``blockage_marker`` for the shared primitive and
``auto_continue_stop._HUMAN_BLOCKED_PATTERNS`` for the narrow write-side
pattern set.

**Fails open everywhere**: no marker, wrong session, expired marker, corrupt
marker, or no resolvable project context all ALLOW the tick through
unchanged -- suppression is a positive assertion made only when every
condition is individually verified, never the default. A genuine external
interruption during the blocked window is still bounded by "however long the
owner takes to respond" (BRAINSTORM.md), and the expiry itself further bounds
an unresponsive owner's silence.

**Never terminal.** ``idle_housekeeping_advisory`` and
``standing_authorisations`` also key off the same canonical cron prompt and
must keep running on every NON-suppressed tick. A non-terminal DENY still
survives later handlers regardless of registration order
(``core/router.py``: "a non-terminal deny now survives later handlers"), so
staying non-terminal costs nothing on the suppressed path either.
"""

import logging
import time
from collections.abc import Callable
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    CANONICAL_CRON_PROMPT_MARKER,
)
from claude_code_hooks_daemon.utils.blockage_marker import (
    MARKER_FILENAME,
    marker_is_valid,
    read_marker,
)

logger = logging.getLogger(__name__)

_DEFAULT_EXPIRY_HOURS: Final[float] = 24.0
_SECONDS_PER_HOUR: Final[int] = 3600
_UNKNOWN_SESSION: Final[str] = "unknown"

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.FAILSAFE_CRON_SUPPRESSED,
    blocked="A delivered failsafe-cron tick, while a 'blocked only on human input' marker is live",
    why="Every tick against a session blocked only on human input is a guaranteed no-op model turn",
    fix="Nothing to do -- this is expected. Send a real message to clear the marker and resume ticks",
    verbose=(
        "This session recorded a 'blocked only on human input' marker (Plan "
        "00298) still within its expiry window, so this failsafe-cron tick "
        "was dropped before reaching the model -- no turn spent. A real "
        "(non-cron) user prompt clears the marker immediately; the marker's "
        "own expiry restores full hourly cron coverage automatically if the "
        "owner stays silent for longer."
    ),
)


class FailsafeCronBlockageSuppressorHandler(UserPromptSubmitHandlerBase):
    """Suppress a delivered failsafe-cron tick while the session is stably
    blocked only on human input (Plan 00298)."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.FAILSAFE_CRON_BLOCKAGE_SUPPRESSOR,
            priority=Priority.FAILSAFE_CRON_BLOCKAGE_SUPPRESSOR,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.AUTOMATION, HandlerTag.NON_TERMINAL],
        )
        # Config option (hours); overridden by the registry from handler
        # options via setattr.
        self._expiry_hours: float = _DEFAULT_EXPIRY_HOURS
        # Injectable wall clock (tests substitute a fake). Not a config option.
        self._clock: Callable[[], float] = time.time

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match a delivered canonical-cron-prompt tick, and nothing else."""
        prompt = hook_input.get(HookInputField.PROMPT)
        return isinstance(prompt, str) and CANONICAL_CRON_PROMPT_MARKER in prompt

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Suppress the tick when a still-valid marker exists for this session.

        Args:
            hook_input: The UserPromptSubmit event's hook input.

        Returns:
            DENY (blocks/erases the prompt) only when a valid marker is
            found; ALLOW in every other case, including every failure mode.
        """
        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or _UNKNOWN_SESSION)
        try:
            marker_path = ProjectContext.daemon_untracked_dir() / MARKER_FILENAME
        except RuntimeError as e:
            logger.debug("failsafe_cron_blockage_suppressor: no project context: %s", e)
            return BlockingResult(decision=Decision.ALLOW)

        marker = read_marker(marker_path)
        now = self._clock()
        expiry_seconds = self._expiry_hours * _SECONDS_PER_HOUR
        if not marker_is_valid(marker, session_id, now, expiry_seconds):
            return BlockingResult(decision=Decision.ALLOW)

        logger.info(
            "failsafe_cron_blockage_suppressor: suppressing cron tick for session %s",
            session_id,
        )
        return BlockingResult(decision=Decision.DENY, reason=RuleFormatter().verbose(_RULE))

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's DENY path."""
        return [_RULE]

    def get_claude_md(self) -> str | None:
        """Document the suppression contract."""
        return (
            "## failsafe_cron_blockage_suppressor — zero-token cadence for "
            "human-input blockage\n\n"
            "When a Stop is allowed with a narrow 'blocked only on human "
            "input' STOPPING BECAUSE: shape, `auto_continue_stop` records a "
            "session-scoped marker. This handler recognises a DELIVERED "
            "failsafe-cron tick (the canonical prompt from "
            "`recovery_cron_advisor`) and, while a still-valid marker exists "
            "for the session, blocks the tick before it reaches the model — "
            "genuinely zero-token, not just cheaper. A real (non-cron) user "
            "prompt clears the marker; the marker also expires "
            "(`expiry_hours`, default 24) so an extended silence restores "
            "full hourly coverage automatically. Never terminal: other "
            "handlers keyed on the same canonical prompt still run.\n\n"
            "**On by default** (dogfooding purpose). Disable with:\n\n"
            "```yaml\n"
            "handlers:\n"
            "  user_prompt_submit:\n"
            "    failsafe_cron_blockage_suppressor:\n"
            "      enabled: false\n"
            "```\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="No marker: a delivered cron tick is allowed through unchanged",
                command='echo "test"',
                description=(
                    "Default state check. With no blockage marker recorded, "
                    "submitting the canonical failsafe-cron prompt must be "
                    "allowed through unchanged (ALLOW, no suppression)."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Advisory-adjacent handler; this test asserts the SAFE default "
                    "(no suppression without a marker)."
                ),
                test_type=TestType.CONTEXT,
                requires_event="UserPromptSubmit event (cannot be triggered by subagent)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
