"""TeammateReapAdvisorHandler - name the unreaped teammates a stop is waiting on.

Plan 00419 Task 1.7 (niggle N5). Claude Code's ``/goal`` command is a
session-scoped prompt-based Stop hook, and its documentation states that "if a
subagent or a background shell command is still running when a turn ends,
Claude Code skips the evaluation for that turn". An in-process teammate that
has FINISHED its work and gone idle is still REGISTERED, and the Stop payload
lists it in ``background_tasks`` with ``status: "running"`` -- so the natural
end state of a correct parallel workflow (every branch merged, every teammate
idle) is a session ``/goal`` can never release.

**This handler cannot fix that, and does not try.** The evaluator is Claude
Code's, not this daemon's: nothing here changes when a stop is allowed. What
the daemon CAN do is say what the payload says, because the agent otherwise has
no way to see it -- N5 cost four refused stops and a full turn each before the
cause was found, while ``harvest-background``, ``ps`` and ``ListAgents`` all
correctly reported nothing running.

So this is advisory and only advisory: every path returns ALLOW, and the module
contains no deny branch at all (pinned by its own unit test, which reads this
source). Reaping the teammate is the agent's call, exactly as
``background_process_tracker`` surfaces a runaway without ever killing one.

**Silence is the default.** ``background_tasks`` is CONDITIONAL
(``contracts/claude-code-hooks/Stop.json``): an ABSENT list means *unknown* and
must never be read as *empty*, so an absent or malformed field says nothing
here. An empty list is the post-reap state and needs no nudge. And because a
Stop handler fires on every single stop, a present non-empty list is advised
on the first stop of a session and then only every ``ADVISE_INTERVAL``-th --
the same rate limit, for the same reason, as ``background_process_tracker``.

**Ordering.** Priority 9 puts it below ``auto_continue_stop`` (10 in this
project's config), whose deny would otherwise shadow it on every stop lacking a
``STOPPING BECAUSE:`` line; ``terminal=False`` keeps it from shadowing anything
itself. See ``tests/integration/test_stop_chain_terminal_shadowing.py``, which
denies the other placement outright.
"""

from __future__ import annotations

from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import StopHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope

#: Advise on the first qualifying stop of a session, then every Nth. Public
#: because the rate-limit test must assert against the real interval rather
#: than a second copy of the number. Matched to
#: ``background_process_tracker``'s interval on purpose: both are default-on
#: advisories on a high-frequency event.
ADVISE_INTERVAL: Final[int] = 10

_COUNT_START: Final[int] = 1

# Bound the per-session counter map on the daemon-lifetime singleton.
_MAX_TRACKED_SESSIONS: Final[int] = 256

_UNKNOWN_SESSION: Final[str] = "unknown"


def _background_task_count(hook_input: dict[str, Any]) -> int:
    """How many background tasks this payload REPORTS, or 0 for "no information".

    Zero is returned for three genuinely different states -- field absent,
    field empty, field malformed -- because the handler's response to all
    three is identical: say nothing. Absent is *unknown* rather than *empty*
    (``Stop.json``), and an advisory that guessed at a count it was not given
    would be inventing the very fact it exists to report.
    """
    tasks = hook_input.get(HookInputField.BACKGROUND_TASKS)
    if not isinstance(tasks, list):
        return 0
    return len(tasks)


def _advisory(count: int) -> str:
    """The nudge, naming the count and the remedy."""
    plural = "task" if count == 1 else "tasks"
    return (
        f"🧹 UNREAPED BACKGROUND WORK: the payload lists {count} background "
        f"{plural}; if these are finished teammates, `TaskStop` them or "
        "`/goal` cannot evaluate.\n\n"
        "Claude Code defers its `/goal` stop-condition evaluation while any "
        "background work is registered, and a teammate that has finished and "
        "gone IDLE is still registered — it is listed here with status "
        "`running` even though nothing is in flight. `ListAgents` reports the "
        "idle/running distinction correctly; this list does not.\n\n"
        "Run `ListAgents`, then `TaskStop` every teammate whose work you have "
        "already harvested. An idle teammate also holds context for no return.\n\n"
        "Advisory only — this changes nothing about whether the stop is allowed."
    )


class TeammateReapAdvisorHandler(StopHandlerBase):
    """Report the Stop payload's ``background_tasks`` count and name ``TaskStop``.

    Never denies. ``StopHandlerBase`` is the blocking tier because the Stop
    EVENT can refuse, so the return type is ``BlockingResult`` — but every
    path here builds one with ``Decision.ALLOW``, which is the advisory
    behaviour the tier cannot express in its own type.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.TEAMMATE_REAP_ADVISOR,
            priority=Priority.TEAMMATE_REAP_ADVISOR,
            terminal=False,
            # Only the coordinator has teammates to reap, so only the
            # coordinator can act on this advice (Plan 00423).
            scope=HandlerScope.MAIN,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # Per-session count of qualifying stops seen (insertion-ordered for
        # bounded eviction), mirroring background_process_tracker.
        self._session_counts: dict[str, int] = {}

    def get_default_enabled(self) -> bool:
        """Opt-OUT handler — ON by default.

        Advisory-only and rate-limited, so it is safe to ship enabled, and it
        is silent for every project that never registers background work.
        Must stay consistent with the config template.
        """
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True only when the payload REPORTS at least one background task."""
        return _background_task_count(hook_input) > 0

    def _should_advise(self, session_id: str) -> bool:
        """Record a qualifying stop for ``session_id`` and say whether to speak."""
        count = self._session_counts.get(session_id)
        if count is None:
            if len(self._session_counts) >= _MAX_TRACKED_SESSIONS:
                del self._session_counts[next(iter(self._session_counts))]
            count = _COUNT_START
        else:
            count += 1
        self._session_counts[session_id] = count
        return (count - _COUNT_START) % ADVISE_INTERVAL == 0

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Advise, or stay silent — never refuse."""
        count = _background_task_count(hook_input)
        if count <= 0:
            return BlockingResult(decision=Decision.ALLOW)

        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or _UNKNOWN_SESSION)
        if not self._should_advise(session_id):
            return BlockingResult(decision=Decision.ALLOW)

        return BlockingResult(decision=Decision.ALLOW, context=[_advisory(count)])

    def get_claude_md(self) -> str | None:
        """No resident guidance.

        The fire-time message names the count, the remedy and the reason in
        full, and it fires exactly when the situation exists — criterion T4 in
        ``CLAUDE/HANDLER_DEVELOPMENT.md``. The standing half of the rule (reap
        a teammate once its work is harvested) has a canonical home in
        ``CLAUDE/AgentTeam.md``, so duplicating it into every client's
        resident context would buy nothing and cost it on every session.
        """
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Two cases, both driven by a synthetic ``hook_input``.

        A live probe would need a real idle teammate in the dispatching
        session, which no payload can create — the same limitation
        ``cron_stop_enforcer`` records for ``session_crons``.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="teammate reap advisor - reports the background_tasks count",
                command="echo 'background_tasks: 2 entries'",
                description=(
                    "A Stop whose payload lists background tasks gets one advisory "
                    "naming the count and TaskStop. Never blocks the stop."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"TaskStop", r"/goal"],
                safety_notes="Advisory only — it adds context and changes no stop control.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="Stop",
                requires_main_thread=True,
                hook_input={
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                    "background_tasks": [
                        {"id": "task-001", "type": "teammate", "status": "running"},
                        {"id": "task-002", "type": "teammate", "status": "running"},
                    ],
                },
            ),
            AcceptanceTest(
                title="teammate reap advisor - silent when background_tasks is absent",
                command="echo 'ordinary stop'",
                description=(
                    "An ABSENT background_tasks field is 'unknown', never 'no tasks "
                    "running' — so nothing is said."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Negative case: an advisory on every stop would be ignored by the third.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="Stop",
                requires_main_thread=False,
                hook_input={
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                },
            ),
        ]
