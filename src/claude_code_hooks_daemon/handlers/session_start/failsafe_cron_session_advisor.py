"""FailsafeCronSessionAdvisorHandler - failsafe recovery cron from session start.

Plan 00394 option 2. The failsafe recovery cron resumes a session stalled by a
rate limit, a usage limit, an API error or a network failure, and Claude Code
crons do not survive into a new session. Its only advisory was
``recovery_cron_advisor``, a PostToolUse handler that speaks at a plan
CREATION, PROGRESS or COMPLETION moment, so a session had the net only from its
first plan write. A Q&A session, a review, a ``/release`` run or an
``issue-sdlc`` tick that stalled before writing a plan had none, and nothing
said so.

This is the SessionStart counterpart. It shares the canonical prompt with the
PostToolUse advisory, so every surface hands the agent one text, and it asks
for the same ``CronList``-first reconcile, so a second surface speaking in one
session can never produce a second cron.

**Silent where it would add nothing:**

* a resumed session keeps the crons it already had;
* ``recovery_cron_advisor`` switched off -- one switch for the failsafe cron's
  advice, not two, so a project that opted out does not start hearing about
  it at every session start;
* the failsafe cron declared under an enabled ``persistent_crons`` --
  ``persistent_cron_assertor`` already states it at session start, and two
  SessionStart surfaces naming one cron is noise.

**It asserts by instruction, never by verification.** SessionStart receives no
``session_crons``, so the daemon cannot know whether a failsafe cron is already
running; the advice says what to check, never that one is missing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    CANONICAL_CRON_PROMPT,
    declares_failsafe_cron,
)
from claude_code_hooks_daemon.utils.config_cache import load_config_cached
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

#: Where the failsafe cron's own advisory lives in config. Its switch is this
#: handler's switch as well.
_RECOVERY_ADVISOR_EVENT: Final[str] = "post_tool_use"

_GUIDANCE: Final[tuple[str, ...]] = (
    "⏱️  FAILSAFE RECOVERY CRON — this session needs EXACTLY ONE.",
    "",
    "It is the net that resumes a session stalled by a rate limit, a 5-hour usage "
    "limit, an API error or a network failure. Claude Code crons do not survive "
    "into a new session, and the daemon cannot read session memory, so it cannot "
    "tell whether one is already running. Reconcile it yourself:",
    "",
    "  1. Run CronList FIRST.",
    "  2. If a recurring failsafe recovery cron is listed (its prompt carries "
    "[tick:failsafe] or FAILSAFE RECOVERY CHECK): REUSE it and create nothing. "
    "If more than one is listed, CronDelete the extras so one remains.",
    "  3. ONLY IF none is listed, create it: CronCreate with recurring:true and "
    "durable:false, on an off-:00 minute (e.g. 47 * * * *).",
    "  4. Do NOT wait for it to fire — keep working at full speed.",
    "",
    "This is a FAILSAFE RECOVERY cron, NOT a heartbeat: never pace work to it. "
    "Paste the following text verbatim as the cron prompt, first line included — "
    "that line is how the daemon tells this tick from you:",
    "",
)


class FailsafeCronSessionAdvisorHandler(SessionStartHandlerBase):
    """Advise establishing the failsafe recovery cron at session start."""

    def __init__(self) -> None:
        """Initialise as a non-terminal advisory."""
        super().__init__(
            handler_id=HandlerID.FAILSAFE_CRON_SESSION_ADVISOR,
            priority=Priority.FAILSAFE_CRON_SESSION_ADVISOR,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def get_default_enabled(self) -> bool:
        """On by default, like ``recovery_cron_advisor`` whose switch it follows."""
        return True

    def _project_root(self) -> Path:
        root = getattr(self, "_workspace_root", None)
        return Path(root) if root is not None else ProjectContext.project_root()

    def _load_config(self) -> Config:
        """The project's daemon config; defaults on an unloadable file.

        Defaults mean "advise": the advice is a CronList-first reconcile, so
        speaking costs a few lines, while silence costs a session with no
        recovery net.
        """
        try:
            config_path = self._project_root() / ".claude" / "hooks-daemon.yaml"
            return load_config_cached(config_path)
        except (ValidationError, OSError, ValueError, RuntimeError) as exc:
            logger.debug("failsafe_cron_session_advisor: config unavailable: %s", exc)
            return Config()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A new session, the failsafe advice on, and no declaration covering it."""
        if is_resume_session(hook_input):
            return False
        config = self._load_config()
        recovery_advisor = config.get_handler_config(
            _RECOVERY_ADVISOR_EVENT, HandlerID.RECOVERY_CRON_ADVISOR.config_key
        )
        if not recovery_advisor.enabled:
            return False
        return not declares_failsafe_cron(config)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """State the reconcile steps and the canonical prompt."""
        return AdvisoryResult(
            decision=Decision.ALLOW,
            context=[*_GUIDANCE, *CANONICAL_CRON_PROMPT.splitlines()],
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One CONTEXT case: a new session is told to reconcile the failsafe cron."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="failsafe cron session advisor - a new session is covered from its start",
                command='echo "test"',
                description=(
                    "In a project that does not declare the failsafe cron under "
                    "persistent_crons, a new session's start carries the "
                    "CronList-first reconcile and the canonical failsafe prompt. "
                    "In this repository the cron IS declared, so the assertor "
                    "states it instead and this handler stays silent."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"FAILSAFE RECOVERY|CronList"],
                safety_notes="Advisory only — never creates a cron itself, never blocks.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SessionStart event (new session only)",
                requires_main_thread=False,
            ),
        ]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## failsafe_cron_session_advisor — the failsafe cron from session "
            "start\n\n"
            "At the start of a NEW session this tells you to reconcile the "
            "failsafe recovery cron: `CronList` first, reuse the one already "
            "listed, and `CronCreate` it with the canonical prompt only if none "
            "is. Without it a session had the net only from its first plan "
            "write, so a session that stalled before one was never resumed.\n\n"
            "It says what to check, never that the cron is missing — the daemon "
            "cannot read session memory. Silent on a resumed session, when "
            "`recovery_cron_advisor` is disabled (that is its switch too), and "
            "when the failsafe cron is declared under `persistent_crons`, where "
            "`persistent_cron_assertor` states it instead."
        )
