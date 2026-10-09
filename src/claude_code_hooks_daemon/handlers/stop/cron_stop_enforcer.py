"""CronStopEnforcerHandler - block a stop while a declared cron is missing.

Plan 00416 Task 1.1. ``persistent_cron_assertor`` (SessionStart) can only
DECLARE the project's ``persistent_crons`` jobs and instruct a ``CronList``
reconcile -- ``session_crons`` is not delivered that early, so nothing can be
VERIFIED at session start. It IS delivered to ``Stop``
(``contracts/claude-code-hooks/Stop.json``), which is what makes THIS handler
possible: compare declared jobs against the session's actual crons and block
the stop, naming the exact ``CronCreate`` to run, when one was never created.

**Ordering note, both halves.** This handler's ``Priority.CRON_STOP_ENFORCER``
(7) sits deliberately BELOW ``auto_continue_stop`` (15; overridden to 10 in
this project's own config), which is terminal and matches nearly every
ordinary stop. A handler registered AFTER it is shadowed on every stop that
lacks a ``STOPPING BECAUSE:`` line -- the common case, not the exception --
and ``tests/integration/test_stop_chain_terminal_shadowing.py`` denies that
placement outright rather than accepting "still reachable once the stop is
eventually allowed". Running first solves half the problem; the other half is
that THIS handler also matches nearly every ordinary stop (whenever a job is
declared) and must not become a NEW shadow for whatever runs after it. That is
why it is ``terminal=False``: a DENY still wins the final response
(most-restrictive-wins), but dispatch always continues, so auto_continue_stop
and every other Stop handler still run on the same turn. Read that test before
changing either this priority or the terminal flag.

Mirrors ``persistent_cron_assertor``'s config-loading shape (inert on an
unloadable config, gated by the SAME ``persistent_crons.enabled`` switch) so
the two handlers cannot disagree about which jobs are "declared".

**A session-scoped pause is the one sanctioned gap** (ledger 00422 N4). A
session told to cancel a declared job had no legal move: obeying failed this
gate, satisfying it disobeyed the instruction. ``hooks-daemon cron-pause``
records an expiring, session-keyed pause (``utils.cron_pause``); a paused job
may be missing, and the output always names it with its reason and expiry.
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
from claude_code_hooks_daemon.core.handler_bases import StopHandlerBase
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


class CronStopEnforcerHandler(InitialThreadExemption, StopHandlerBase):
    """Block a Stop while a declared persistent cron was never created."""

    # Demands crons: gated on the project's `autonomy:` config (Plan 00498).
    drives_autonomy = True

    def __init__(self) -> None:
        """Initialise as a non-terminal blocking handler.

        ``terminal=False`` is deliberate, not an oversight: this handler runs
        FIRST (priority 7, below every other Stop handler in this project) so
        it can never be shadowed, but that same early, near-universal match
        would make it shadow everything AFTER it if it were terminal. Staying
        non-terminal keeps a DENY in the final response via
        most-restrictive-wins while letting auto_continue_stop and every
        other Stop handler still run on the same turn. See the module
        docstring's "Ordering note".
        """
        super().__init__(
            handler_id=HandlerID.CRON_STOP_ENFORCER,
            priority=Priority.CRON_STOP_ENFORCER,
            terminal=False,
            # Session crons belong to the COORDINATOR's session. The incident
            # behind issue #40 was a subagent deleting a shared recovery cron
            # on its own initiative, so instructing a subagent to create or
            # reconcile them is the same category of mistake (Plan 00423).
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
            return load_config_cached(config_path)
        except (ValidationError, OSError, ValueError) as exc:
            logger.debug("cron_stop_enforcer: cannot load %s: %s", config_path, exc)
            return default_config()

    def _active_jobs(self, hook_input: dict[str, Any]) -> list[PersistentCronConfig]:
        """The jobs this session must hold: declared for its hostname (``hosts:``),
        and none for a thread opened later in a session (``initial_thread_only``).
        """
        crons = self._load_config().persistent_crons
        jobs = crons.active_jobs(effective_hostname(hook_input))
        return self._jobs_held_by_session(hook_input, crons, jobs)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Fire only when the project has at least one active job declared for this host.

        Never while the session is paused on its usage ceiling (Plan 00479): the
        pause DELETES every cron, so demanding the declared ones back would
        fight it. They are re-established when the pause lifts.
        """
        if hook_is_usage_paused(hook_input):
            return False
        return bool(self._active_jobs(hook_input))

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Verify declared jobs against ``session_crons``; block on a gap.

        An ABSENT ``session_crons`` (``parse_session_crons`` returning
        ``None``) is "no information", not "no crons exist" -- ALLOW, never a
        block, is the only correct reading. A PRESENT list (even empty) is a
        genuine report of session state and is compared for real. A missing
        job paused for this session (``hooks-daemon cron-pause``) is allowed
        and named -- see ``verdict_for_missing_crons``.
        """
        jobs = self._active_jobs(hook_input)
        if not jobs:
            return BlockingResult(decision=Decision.ALLOW)

        # A live job older than ``refresh_after_days`` is denied too (Plan 00470
        # Task 2.2): see ``utils.cron_refresh``.
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
            "**Only jobs declared for this host are checked.** A job with `hosts:` "
            "counts only where the session's hostname (`HOOKS_DAEMON_HOSTNAME`, "
            "then `CCY_HOST_HOSTNAME`, then the system hostname) matches an entry, "
            "so a session elsewhere is never told to create it. A job without "
            "`hosts:` is global.\n\n"
            "**Only the initial thread of a Claude Code session is checked.** A "
            "thread opened later in the same session (left arrow, new thread) is a "
            "separate session to the hooks and holds no crons of its own, so it is "
            "never asked for the declared ones; the session's initial thread (its "
            "worker carries `--fork-session --resume`, a later thread's is a "
            "`bg-spare`, both under one shared `claude daemon run` process) is. The "
            "holder is a live worker: if it exits the next thread takes over, and a "
            "`/clear` in it keeps holding. Whenever the placement is unsure every "
            "session is checked as before. "
            "`persistent_crons.initial_thread_only: false` checks every thread.\n\n"
            "**An absent `session_crons` field always ALLOWs.** It means no "
            "information was delivered, never that no crons exist — only a "
            "PRESENT list (even an empty one) is treated as a real report of "
            "session state.\n\n"
            "**This handler runs FIRST and is deliberately non-terminal.** "
            "Priority 7 puts it ahead of every other Stop handler in this "
            "project, so it is never shadowed; `terminal=False` means its own "
            "DENY never shadows anything else either — every other Stop "
            "handler (including `auto_continue_stop`) still runs on the same "
            "turn, and the DENY still wins the final response.\n\n"
            "**Fix**: run `CronCreate` (recurring: true) for every job named in "
            "the block message, using the schedule and prompt given verbatim, "
            "then stop again.\n\n"
            "**A live job is also refreshed before it expires.** Recurring crons die "
            "7 days after creation and an expired cron fires no more ticks, so an idle "
            "session would never be woken. `cron_record_keeper` records each "
            "`CronCreate`; once a live declared job is older than "
            "`options.refresh_after_days` (default 6, valid above 0 and below 7) the stop "
            "is blocked, naming the `CronDelete <id>` and `CronCreate` that refresh it. "
            "A job with no record is stamped, never blocked; a job paused with "
            "`cron-pause` is not refreshed.\n\n"
            "**One deny per stop chain.** A stop that re-enters "
            "(`stop_hook_active`) after the deny is allowed and logged as a "
            "warning, so a session that cannot create the job is never "
            "trapped; the next fresh stop is checked again. The deny always "
            "names the `cron-pause` escape below.\n\n"
            "**Told to cancel a declared cron for now? Pause it, do not fight "
            'the gate.** `hooks-daemon cron-pause <job> --reason "..."` '
            "records a pause for THIS session only, which expires within 24 "
            "hours on its own; `hooks-daemon cron-resume <job>` ends it early. "
            "While it is live the job may be missing, and the stop output names "
            "the job, the reason and the expiry. An unknown job id is refused. "
            "Editing `persistent_crons` stays the only permanent switch."
        )
