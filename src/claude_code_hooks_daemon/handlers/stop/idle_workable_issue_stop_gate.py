"""IdleWorkableIssueStopGateHandler - the cron is a safety net, not a scheduler.

Plan 00470 Phase 7 Task 7.1. The issue-sdlc coordinator closed an issue and
stopped with "the next issue is for the hourly tick" while workable issues
existed and nothing was in flight. The Stop hook accepted it because the
message carried the ``STOPPING BECAUSE:`` prefix; nothing tested whether the
stated reason was true. This handler tests it, on facts only:

- ``issue-sdlc`` (``options.job_id``) is a declared, enabled
  ``persistent_crons`` job that applies to this host and to this thread;
- nothing is in flight: the work queue has no ``running`` entry, the Stop payload's
  ``background_tasks`` lists none with ``status: "running"`` (an absent or malformed
  field is no information), and no ``release-state.json`` exists;
- the workable-issues cache is fresh (``options.max_cache_age_hours``) and
  lists at least one issue.

The cache is written by ``work-queue done`` and ``issue-validity
--list-eligible`` (``utils.workable_issues``), so this Stop hook reads a local
file and never calls GitHub.

**Never a trap.** It stands aside for a usage pause, a non-holder thread
(Task 6.4), a live or just-declared ``[awaiting-human]``, an unreadable queue
or cache, and a stop that re-enters after its own deny (``stop_hook_active``):
the facts on a re-entry are the facts the first deny already named, so one deny
per stop chain is the whole of the pressure, the convention every other
one-shot Stop block follows. A sub-agent stop never reaches it (``MAIN`` scope).

**Ordering.** Priority 4 puts it ahead of ``usage_pause_stop_gate`` (6),
``cron_stop_enforcer`` (7) and ``auto_continue_stop``; it is non-terminal for the
reason those are (see ``cron_stop_enforcer``'s "Ordering note"). Because it runs
BEFORE ``auto_continue_stop``, which writes the awaiting-human marker, it also
reads the current message for the declaration, or the stop that declares it
would be refused one step too early.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, PersistentCronConfig
from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import StopHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import _declares_human_blocked
from claude_code_hooks_daemon.handlers.utils.initial_thread_exemption import (
    InitialThreadExemption,
)
from claude_code_hooks_daemon.utils.blockage_marker import (
    MARKER_FILENAME,
    marker_is_valid,
    read_marker,
)
from claude_code_hooks_daemon.utils.config_cache import default_config, load_config_cached
from claude_code_hooks_daemon.utils.cron_hosts import effective_hostname
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.session_modes import DECLARED_BLOCKED_TTL_SECONDS
from claude_code_hooks_daemon.utils.stop_hook_helpers import (
    get_transcript_reader,
    has_running_background_task,
    is_stop_hook_active,
)
from claude_code_hooks_daemon.utils.usage_pause_gate import hook_is_usage_paused
from claude_code_hooks_daemon.utils.work_queue import (
    WORK_QUEUE_FILENAME,
    WorkQueueError,
    active_records,
    read_queue,
)
from claude_code_hooks_daemon.utils.workable_issues import (
    WORKABLE_ISSUES_FILENAME,
    read_workable,
)

logger = logging.getLogger(__name__)

#: The declared job whose idle stops are judged.
DEFAULT_JOB_ID: Final[str] = "issue-sdlc"
#: How old the workable-issues cache may be before the gate stops trusting it.
DEFAULT_MAX_CACHE_AGE_HOURS: Final[float] = 2.0
_SECONDS_PER_HOUR: Final[float] = 3600.0
#: The release runbook's state file, in the daemon's state directory. Its presence
#: means a release is in progress. Same name the project's ``release_blocker`` Stop
#: handler reads; that handler lives under ``.claude/project-handlers`` and cannot be
#: imported from the package, so the name is repeated here.
RELEASE_STATE_FILENAME: Final[str] = "release-state.json"

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.STOP_IDLE_WITH_WORKABLE_ISSUE,
    blocked="a main-thread stop with workable issues listed, nothing in flight, and the next one left for a cron tick",
    why="The declared cron is a safety net, not a scheduler: a stop that waits for the tick while workable issues exist idles the loop for up to an hour",
    fix="Start the named issue now; or stop naming the real blocker (`[awaiting-human]` if only a human can unblock it)",
    verbose=(
        "The project declares an issue-sdlc cron, nothing is in flight (no running work\n"
        "queue entry, no running background task in the payload, no release state file),\n"
        "and the workable-issues cache (written by `work-queue done` and `issue-validity\n"
        "--list-eligible`) lists an issue. The deny names it. One deny per stop chain:\n"
        "a re-entered stop is allowed, so the session is never trapped."
    ),
)


class IdleWorkableIssueStopGateHandler(InitialThreadExemption, StopHandlerBase):
    """Refuse a main-thread idle stop while a workable issue is cached and nothing runs."""

    def __init__(self) -> None:
        """Initialise as a non-terminal blocking handler (see the module docstring)."""
        super().__init__(
            handler_id=HandlerID.IDLE_WORKABLE_ISSUE_STOP_GATE,
            priority=Priority.IDLE_WORKABLE_ISSUE_STOP_GATE,
            terminal=False,
            scope=HandlerScope.MAIN,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.BLOCKING,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # Options, injected by the registry from ``options.<name>``.
        self._job_id: str = DEFAULT_JOB_ID
        self._max_cache_age_hours: float = DEFAULT_MAX_CACHE_AGE_HOURS
        # Injectable wall clock; not a config option.
        self._clock: Callable[[], float] = time.time

    def get_default_enabled(self) -> bool:
        """On by default; inert unless the project declares the issue-sdlc job."""
        return True

    def _project_root(self) -> Path:
        root = getattr(self, "_workspace_root", None)
        return Path(root) if root is not None else ProjectContext.project_root()

    def _load_config(self) -> Config:
        """The project's config; defaults (so: silent) on an unloadable file."""
        config_path = self._project_root() / ".claude" / "hooks-daemon.yaml"
        try:
            return load_config_cached(config_path)
        except (ValidationError, OSError, ValueError, RuntimeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason=f"an unloadable config {config_path} declares no issue-sdlc job, so the gate stays silent rather than raising out of the Stop chain",
                level=logging.DEBUG,
            )
            return default_config()

    def _untracked_dir(self) -> Path | None:
        """The daemon's state directory, or None without a project context."""
        if not ProjectContext.is_initialized():
            logger.debug("idle_workable_issue_stop_gate: no project context, so no state")
            return None
        return ProjectContext.daemon_untracked_dir()

    def _declared_job(self, hook_input: dict[str, Any]) -> PersistentCronConfig | None:
        """The watched job when this session must hold it, else None."""
        crons = self._load_config().persistent_crons
        jobs = crons.active_jobs(effective_hostname(hook_input))
        held = self._jobs_held_by_session(hook_input, crons, jobs)
        return next((job for job in held if job.id == self._job_id), None)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Fire only on a session that holds the watched job and is not usage-paused."""
        if hook_is_usage_paused(hook_input):
            return False
        return self._declared_job(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Deny an idle stop that leaves a cached workable issue to the next tick."""
        if is_stop_hook_active(hook_input):
            return BlockingResult(decision=Decision.ALLOW)
        state = self._untracked_dir()
        if state is None:
            return BlockingResult(decision=Decision.ALLOW)
        cache = read_workable(state / WORKABLE_ISSUES_FILENAME)
        now = self._clock()
        if (
            cache is None
            or not cache.numbers
            or not cache.is_fresh(
                now=now, max_age_seconds=self._max_cache_age_hours * _SECONDS_PER_HOUR
            )
        ):
            return BlockingResult(decision=Decision.ALLOW)
        if (
            has_running_background_task(hook_input)
            or (state / RELEASE_STATE_FILENAME).exists()
            or self._queue_holds_the_gate_back(state)
        ):
            return BlockingResult(decision=Decision.ALLOW)
        if self._awaiting_human(hook_input, state, now):
            return BlockingResult(decision=Decision.ALLOW)
        return BlockingResult.deny(self._render(cache.numbers)).under_rule(_RULE)

    @staticmethod
    def _queue_holds_the_gate_back(state: Path) -> bool:
        """True when a queue entry is running, or the queue cannot be read.

        An unreadable queue cannot show that nothing is in flight, so the gate
        stands aside rather than deny a session that may be running work.
        """
        try:
            return bool(active_records(read_queue(state / WORK_QUEUE_FILENAME)))
        except WorkQueueError as exc:
            log_and_continue(
                logger,
                exc,
                reason="an unreadable work queue cannot show that nothing is in flight, so the gate stands aside (True) rather than deny a session that may be running work",
            )
            return True

    def _awaiting_human(self, hook_input: dict[str, Any], state: Path, now: float) -> bool:
        """Whether this session is blocked only on a human: a live marker, or this stop says so."""
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        marker = read_marker(state / MARKER_FILENAME)
        if marker_is_valid(marker, session_id, now, DECLARED_BLOCKED_TTL_SECONDS):
            return True
        # The marker is written by auto_continue_stop, which runs after this handler.
        reader = get_transcript_reader(hook_input)
        text = reader.get_last_assistant_text() if reader is not None else ""
        return bool(text) and _declares_human_blocked(text)

    def _render(self, numbers: tuple[int, ...]) -> str:
        first, rest = numbers[0], numbers[1:]
        others = f" ({len(rest)} more workable after it)" if rest else ""
        return (
            f"Issue #{first} is workable and nothing is in flight{others} (checked: the work "
            "queue, the payload's background tasks, and the release state file). "
            f"The `{self._job_id}` "
            "cron is a safety net, not a scheduler: it exists to restart a session that "
            "has stopped, not to hand out the next issue. Do not wait for the tick.\n\n"
            f"Start #{first} now (claim it with `bin/hooks-daemon issue-validity {first} --claim`, "
            "then follow the runbook). If a real blocker prevents it, stop again and name that "
            "blocker; if only a human can unblock it, say `[awaiting-human]` after "
            "`STOPPING BECAUSE:`."
        )

    def get_rules(self) -> list[Rule]:
        """The single rule behind this handler's deny."""
        return [_RULE]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## idle_workable_issue_stop_gate — the cron is a safety net, not a scheduler\n\n"
            "Where the project declares the `issue-sdlc` cron job, a MAIN-THREAD stop is "
            "denied when nothing is in flight and the workable-issues cache lists an issue. "
            "In flight means a `running` entry in the work queue, a `background_tasks` entry "
            'with `status: "running"` in the Stop payload, or an `untracked/release-state.json` '
            "file; an absent or malformed `background_tasks` field is no information. `work-queue done` and `issue-validity "
            "--list-eligible` write that cache and `work-queue done` prints the next issue "
            "too. The deny names the first issue: start it, or stop again naming the real "
            "blocker.\n\n"
            "**Stands aside** for a sub-agent stop, a usage pause, a non-holder thread, a live "
            "or just-declared `[awaiting-human]`, a stale (older than "
            "`options.max_cache_age_hours`, default 2) or missing cache, an unreadable queue, "
            "and a stop that re-enters after the deny (`stop_hook_active`), so a session is "
            "never trapped. It reads local files only and never calls GitHub.\n\n"
            "Options (`handlers.stop.idle_workable_issue_stop_gate.options`): `job_id` "
            "(default `issue-sdlc`), `max_cache_age_hours`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One undrivable deny case and one near-miss allow case."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="idle workable issue stop gate - an idle stop with a workable issue is refused",
                command="echo 'idle stop with a cached workable issue'",
                description=(
                    "With the issue-sdlc job declared, nothing running in the work queue or in "
                    "the payload's background tasks, no release state file and a fresh "
                    "workable-issues cache listing an issue, a main-thread Stop is denied "
                    "and names the issue."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"safety net"],
                safety_notes="Blocks only while the cache is fresh and the queue is empty.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="Stop",
                requires_main_thread=True,
                harness_cannot_produce=(
                    "The deny needs a fresh workable-issues cache in the daemon's state "
                    "directory, and a probe cannot write one without altering the state it "
                    "observes. Verified by unit tests."
                ),
            ),
            AcceptanceTest(
                title="idle workable issue stop gate - an ordinary stop with no cache",
                command="echo 'ordinary stop'",
                description="Near-miss: with no workable-issues cache the gate stands aside.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Negative case: no cache is no information, never a deny.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="Stop",
                requires_main_thread=False,
                hook_input={"hook_event_name": "Stop", "stop_hook_active": False},
            ),
        ]
