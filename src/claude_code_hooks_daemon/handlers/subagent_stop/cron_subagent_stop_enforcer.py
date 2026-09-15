"""CronSubagentStopEnforcerHandler - the SubagentStop twin of the Stop enforcer.

Plan 00416 Task 1.1. ``session_crons`` reaches ``SubagentStop`` exactly as it
reaches ``Stop`` (``contracts/claude-code-hooks/Stop.json`` documents the
field for both), and a subagent-only session can end without the main-thread
Stop event ever firing -- so cron enforcement needs this twin rather than
relying on ``cron_stop_enforcer`` alone. The comparison logic is identical and
lives once in ``utils.cron_enforcement``; only the event wiring differs.

**Ordering note** -- same reasoning as the Stop twin, both halves: ``Priority.
CRON_SUBAGENT_STOP_ENFORCER`` (7) sits deliberately BELOW
``subagent_report_size_blocker`` (15), which is terminal and matches nearly
every SubagentStop, so this handler runs first and is never shadowed. It is
also ``terminal=False``, so its own near-universal match cannot shadow
``subagent_report_size_blocker`` (or anything else) in turn -- a DENY still
wins the final response via most-restrictive-wins, but dispatch always
continues. See ``cron_stop_enforcer``'s module docstring for the full
argument and the test that enforces this ordering.
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
from claude_code_hooks_daemon.core.handler_bases import SubagentStopHandlerBase
from claude_code_hooks_daemon.utils.cron_enforcement import (
    find_missing_crons,
    parse_session_crons,
    render_missing_crons_reason,
)

logger = logging.getLogger(__name__)


class CronSubagentStopEnforcerHandler(SubagentStopHandlerBase):
    """Block a SubagentStop while a declared persistent cron is missing."""

    def __init__(self) -> None:
        """Initialise as a non-terminal blocking handler.

        See ``CronStopEnforcerHandler.__init__`` -- same reasoning: running
        first (priority 7) avoids being shadowed, and staying non-terminal
        avoids shadowing everything registered after it in turn.
        """
        super().__init__(
            handler_id=HandlerID.CRON_SUBAGENT_STOP_ENFORCER,
            priority=Priority.CRON_SUBAGENT_STOP_ENFORCER,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.SAFETY,
                HandlerTag.BLOCKING,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def get_default_enabled(self) -> bool:
        """Enabled, but silent until the project declares a job.

        Matched to ``persistent_cron_assertor`` and ``cron_stop_enforcer``:
        the config section is the master switch.
        """
        return True

    def _project_root(self) -> Path:
        root = getattr(self, "_workspace_root", None)
        return Path(root) if root is not None else ProjectContext.project_root()

    def _load_config(self) -> Config:
        """The project's daemon config; defaults on an unloadable file."""
        config_path = self._project_root() / ".claude" / "hooks-daemon.yaml"
        try:
            return Config.load_or_default(config_path)
        except (ValidationError, OSError, ValueError) as exc:
            logger.debug("cron_subagent_stop_enforcer: cannot load %s: %s", config_path, exc)
            return Config()

    def _active_jobs(self) -> list[PersistentCronConfig]:
        return self._load_config().persistent_crons.active_jobs()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Fire only when the project has at least one active declared job."""
        return bool(self._active_jobs())

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Verify declared jobs against ``session_crons``; block on a gap.

        Identical semantics to ``CronStopEnforcerHandler.handle`` -- see
        that module's docstring for the absent-vs-empty reasoning.
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
        """Two cases, mirroring the Stop twin against this repo's real job."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title=(
                    "cron subagent-stop enforcer - blocks when session_crons is present but empty"
                ),
                command="echo 'session_crons: []'",
                description=(
                    "With persistent_crons.enabled true and at least one declared "
                    "job, a PRESENT but empty session_crons blocks the "
                    "SubagentStop, naming CronCreate."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"CronCreate"],
                safety_notes=(
                    "Blocks only when session_crons is PRESENT and shows a genuine "
                    "gap -- see the sibling ALLOW test for the absent-field case."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SubagentStop",
                requires_main_thread=True,
                hook_input={
                    "hook_event_name": "SubagentStop",
                    "agent_id": "agent-1",
                    "stop_hook_active": False,
                    "session_crons": [],
                },
            ),
            AcceptanceTest(
                title="cron subagent-stop enforcer - allows when session_crons is absent",
                command="echo 'ordinary subagent stop'",
                description=(
                    "An ABSENT session_crons field is 'no information', never "
                    "'no crons exist' -- the SubagentStop is never blocked on it."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Negative case: no information must never be read as a gap.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SubagentStop",
                requires_main_thread=False,
                hook_input={
                    "hook_event_name": "SubagentStop",
                    "agent_id": "agent-1",
                    "stop_hook_active": False,
                },
            ),
        ]

    def get_claude_md(self) -> str | None:
        """Resident guidance -- points at the Stop twin, which carries the
        full explanation to avoid two divergent copies of the same prose."""
        return (
            "## cron_subagent_stop_enforcer — SubagentStop twin of "
            "`cron_stop_enforcer`\n\n"
            "Same verification, same matching rules, same absent-vs-empty "
            "`session_crons` semantics, same priority-7/non-terminal "
            "ordering reasoning as `cron_stop_enforcer` — see its guidance "
            "above. This twin exists because a subagent-only session can "
            "reach `SubagentStop` without the main-thread `Stop` event ever "
            "firing."
        )
