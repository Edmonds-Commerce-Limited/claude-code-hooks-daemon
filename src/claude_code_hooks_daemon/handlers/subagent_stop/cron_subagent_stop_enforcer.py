"""CronSubagentStopEnforcerHandler - the SubagentStop twin of the Stop enforcer.

Plan 00416 Task 1.1. ``session_crons`` reaches ``SubagentStop`` exactly as it
reaches ``Stop`` (``contracts/claude-code-hooks/Stop.json`` documents the
field for both). The comparison logic is identical and lives once in
``utils.cron_enforcement``; only the event wiring differs.

**Scope is ``MAIN``** (issue #62). A SubagentStop always carries ``agent_id``,
and session crons belong to the COORDINATOR's session, so a finished subagent
must never be denied for a missing cron or told to ``CronCreate`` (same
ownership principle as Plan 00423 and the ``CronDelete`` guard). The chain
therefore never dispatches a real subagent stop here; the coordinator's own
``Stop`` is where the gap is enforced. The scope is overridable per project
with ``scope: ALL`` for anyone who wants the old behaviour.

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
from typing import Any, Final

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, PersistentCronConfig
from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import SubagentStopHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.handlers.utils.initial_thread_exemption import (
    InitialThreadExemption,
)
from claude_code_hooks_daemon.handlers.utils.session_advice_counter import (
    SessionAdviceCounter,
)
from claude_code_hooks_daemon.utils.config_cache import default_config, load_config_cached
from claude_code_hooks_daemon.utils.cron_hosts import effective_hostname
from claude_code_hooks_daemon.utils.cron_pause import PAUSE_ADVISE_INTERVAL, default_pauses_path
from claude_code_hooks_daemon.utils.cron_records import (
    DEFAULT_REFRESH_AFTER_DAYS,
    default_records_path,
)
from claude_code_hooks_daemon.utils.cron_refresh import (
    judge_declared_crons,
    refresh_days_to_seconds,
)
from claude_code_hooks_daemon.utils.usage_pause_gate import hook_is_usage_paused

logger = logging.getLogger(__name__)

# Bound the per-session pause-advice map on the daemon-lifetime singleton.
_MAX_TRACKED_PAUSE_KEYS: Final[int] = 256


class CronSubagentStopEnforcerHandler(InitialThreadExemption, SubagentStopHandlerBase):
    """Block a SubagentStop while a declared persistent cron is missing."""

    # Demands crons: gated on the project's `autonomy:` config (Plan 00498).
    drives_autonomy = True

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
            # Issue #62: a SubagentStop always carries ``agent_id``, and the
            # session's crons belong to the COORDINATOR. Telling a finished
            # subagent to CronCreate is the mistake Plan 00423 scoped the Stop
            # twin against, so a real subagent stop is never judged here.
            scope=HandlerScope.MAIN,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.SAFETY,
                HandlerTag.BLOCKING,
                HandlerTag.NON_TERMINAL,
            ],
        )
        self._pause_advice = SessionAdviceCounter(
            interval=PAUSE_ADVISE_INTERVAL, max_sessions=_MAX_TRACKED_PAUSE_KEYS
        )
        # Option, injected by the registry (``options.refresh_after_days``).
        self._refresh_after_days: float = DEFAULT_REFRESH_AFTER_DAYS

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
            return load_config_cached(config_path)
        except (ValidationError, OSError, ValueError) as exc:
            logger.debug("cron_subagent_stop_enforcer: cannot load %s: %s", config_path, exc)
            return default_config()

    def _active_jobs(self, hook_input: dict[str, Any]) -> list[PersistentCronConfig]:
        """The jobs this session must hold: declared for its hostname (``hosts:``),
        and none for a thread opened later in a session (``initial_thread_only``).
        """
        crons = self._load_config().persistent_crons
        jobs = crons.active_jobs(effective_hostname(hook_input))
        if jobs and self._exempt_holder(hook_input, crons) is not None:
            return []
        return jobs

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Fire only when the project has at least one active job declared for this host.

        Never while the session is paused on its usage ceiling (Plan 00479); see
        ``CronStopEnforcerHandler.matches``.
        """
        if hook_is_usage_paused(hook_input):
            return False
        return bool(self._active_jobs(hook_input))

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Verify declared jobs against ``session_crons``; block on a gap.

        Identical semantics to ``CronStopEnforcerHandler.handle`` -- see
        that module's docstring for the absent-vs-empty reasoning.
        """
        jobs = self._active_jobs(hook_input)
        if not jobs:
            return BlockingResult(decision=Decision.ALLOW)

        # Also denies a live job past ``refresh_after_days`` (Plan 00470 Task
        # 2.2), through the same shared judgement as the Stop twin.
        return judge_declared_crons(
            jobs,
            hook_input,
            pauses_path=self._pauses_path(),
            records_path=self._records_path(),
            should_advise=self._pause_advice.should_advise,
            refresh_after_seconds=refresh_days_to_seconds(self._refresh_after_days),
        )

    def _pauses_path(self) -> Path | None:
        """Where ``hooks-daemon cron-pause`` records this project's pauses."""
        return default_pauses_path()

    def _records_path(self) -> Path | None:
        """Where ``cron_record_keeper`` records when each cron was created."""
        return default_records_path()

    def get_acceptance_tests(self) -> list[Any]:
        """Two cases, mirroring the Stop twin against this repo's real job."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title=(
                    "cron subagent-stop enforcer - never blocks a subagent, "
                    "even on an empty session_crons"
                ),
                command="echo 'session_crons: []'",
                description=(
                    "With persistent_crons.enabled true and at least one declared "
                    "job, a subagent's SubagentStop with a PRESENT but empty "
                    "session_crons is allowed: the session's crons belong to "
                    "the coordinator, so a subagent is never told to CronCreate."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Scope MAIN keeps a real subagent stop out of this handler "
                    "(issue #62); the main-thread Stop twin still enforces."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SubagentStop",
                requires_main_thread=False,
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
            "`session_crons` semantics, same refresh of a job older than "
            "`options.refresh_after_days`, same `cron-pause` session pause, same "
            "priority-7/non-terminal "
            "ordering reasoning as `cron_stop_enforcer` — see its guidance "
            "above. Scoped to the main thread like `cron_stop_enforcer`: session "
            "crons belong to the coordinator, so a subagent's own stop is "
            "never denied for a missing cron and is never told to run "
            "`CronCreate`."
        )
