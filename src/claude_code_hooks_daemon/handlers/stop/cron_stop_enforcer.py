"""CronStopEnforcerHandler - block a stop while a declared cron is missing.

Plan 00416 Task 1.1. ``persistent_cron_assertor`` (SessionStart) can only
DECLARE the project's ``persistent_crons`` jobs and instruct a ``CronList``
reconcile -- ``session_crons`` is not delivered that early, so nothing can be
VERIFIED at session start. It IS delivered to ``Stop``
(``contracts/claude-code-hooks/Stop.json``), which is what makes THIS handler
possible: compare declared jobs against the session's actual crons and block
the stop, naming the exact ``CronCreate`` to run, when one was never created.

**Ordering note, because it looks like a hazard and is not one.** This
handler's ``Priority.CRON_STOP_ENFORCER`` (40) sits numerically AFTER the
Stop-chain's safety-band terminal handlers (``auto_continue_stop`` at 15,
overridden to 10 in this project's own config). Plan 00242 made an ALLOW
never end the dispatch chain, so that ordering is safe rather than a
shadowing bug: whichever of those handlers DENIES only ends the SAME dispatch
that was already refusing to end the session for its own reason, and the
moment either one genuinely ALLOWs -- the session is actually about to stop --
dispatch continues into this handler regardless of registration order. See
``tests/integration/test_stop_chain_terminal_shadowing.py`` before changing
this reasoning, and the plan's ``DESIGN-cron-enforcement.md`` for the full
argument.

Mirrors ``persistent_cron_assertor``'s config-loading shape (inert on an
unloadable config, gated by the SAME ``persistent_crons.enabled`` switch) so
the two handlers cannot disagree about which jobs are "declared".
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, PersistentCronConfig
from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import StopHandlerBase
from claude_code_hooks_daemon.utils.cron_enforcement import (
    find_missing_crons,
    parse_session_crons,
    render_missing_crons_reason,
)

logger = logging.getLogger(__name__)


class CronStopEnforcerHandler(StopHandlerBase):
    """Block a Stop while a declared persistent cron was never created."""

    def __init__(self) -> None:
        """Initialise as a terminal blocking handler."""
        super().__init__(
            handler_id=HandlerID.CRON_STOP_ENFORCER,
            priority=Priority.CRON_STOP_ENFORCER,
            terminal=True,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.SAFETY,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
            ],
        )

    def get_default_enabled(self) -> bool:
        """Enabled, but silent until the project declares a job.

        Matched to ``persistent_cron_assertor``: the config section is the
        master switch, so a project that declares jobs and enables the
        section is not left with a second switch to remember to also flip.
        """
        return True

    def _project_root(self) -> Path:
        root = getattr(self, "_workspace_root", None)
        return Path(root) if root is not None else ProjectContext.project_root()

    def _load_config(self) -> Config:
        """The project's daemon config; defaults on an unloadable file.

        A config the daemon already reports as invalid must degrade this
        enforcer to silent rather than raise out of the Stop chain and take
        every other Stop handler down with it.
        """
        config_path = self._project_root() / ".claude" / "hooks-daemon.yaml"
        try:
            return Config.load_or_default(config_path)
        except (ValidationError, OSError, ValueError) as exc:
            logger.debug("cron_stop_enforcer: cannot load %s: %s", config_path, exc)
            return Config()

    def _active_jobs(self) -> list[PersistentCronConfig]:
        return self._load_config().persistent_crons.active_jobs()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Fire only when the project has at least one active declared job."""
        return bool(self._active_jobs())

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Verify declared jobs against ``session_crons``; block on a gap.

        An ABSENT ``session_crons`` (``parse_session_crons`` returning
        ``None``) is "no information", not "no crons exist" -- ALLOW, never a
        block, is the only correct reading. A PRESENT list (even empty) is a
        genuine report of session state and is compared for real.
        """
        jobs = self._active_jobs()
        if not jobs:
            return BlockingResult(decision=Decision.ALLOW)

        session_crons = parse_session_crons(hook_input)
        if session_crons is None:
            return BlockingResult(decision=Decision.ALLOW)

        missing = find_missing_crons(jobs, session_crons)
        if not missing:
            return BlockingResult(decision=Decision.ALLOW)

        return BlockingResult.deny(render_missing_crons_reason(missing))

    def get_acceptance_tests(self) -> list[Any]:
        """Two cases, driven against this repo's own real declared job.

        Neither depends on the declared prompt's exact text (it is a long,
        multi-line YAML block that would make a hardcoded fixture fragile) --
        both rely only on whether ``session_crons`` is present, mirroring
        ``subagent_report_size_blocker``'s pattern of a synthetic
        ``hook_input`` driving a deterministic CI-time contract test.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="cron stop enforcer - blocks when session_crons is present but empty",
                command="echo 'session_crons: []'",
                description=(
                    "With persistent_crons.enabled true and at least one declared "
                    "job, a PRESENT but empty session_crons is a genuine report of "
                    "'nothing running' and blocks the Stop, naming CronCreate."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"CronCreate"],
                safety_notes=(
                    "Blocks only when session_crons is PRESENT and shows a genuine "
                    "gap -- see the sibling ALLOW test for the absent-field case."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="Stop",
                requires_main_thread=True,
                hook_input={
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                    "session_crons": [],
                },
            ),
            AcceptanceTest(
                title="cron stop enforcer - allows when session_crons is absent",
                command="echo 'ordinary stop'",
                description=(
                    "An ABSENT session_crons field is 'no information', never "
                    "'no crons exist' -- the stop is never blocked on it."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Negative case: no information must never be read as a gap.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="Stop",
                requires_main_thread=False,
                hook_input={
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                },
            ),
        ]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## cron_stop_enforcer — declared crons are verified, not just "
            "asked for\n\n"
            "**This is the teeth `persistent_cron_assertor` cannot have.** "
            "SessionStart never receives `session_crons`, so that handler can "
            "only ask you to reconcile against `CronList`. `Stop` DOES receive "
            "`session_crons`, so this handler compares every active "
            "`persistent_crons` job against it and BLOCKS the stop — naming the "
            "exact `CronCreate` to run — when a declared job has no matching "
            "entry.\n\n"
            "**Matching is on schedule + prompt, never on id.** The delivered "
            "`prompt` is capped at 1000 characters with a truncation marker, so "
            "a declared prompt longer than that is compared by its truncated "
            "prefix, never by exact equality.\n\n"
            "**An absent `session_crons` field always ALLOWs.** It means no "
            "information was delivered, never that no crons exist — only a "
            "PRESENT list (even an empty one) is treated as a real report of "
            "session state.\n\n"
            "**Fix**: run `CronCreate` (recurring: true) for every job named in "
            "the block message, using the schedule and prompt given verbatim, "
            "then stop again."
        )
