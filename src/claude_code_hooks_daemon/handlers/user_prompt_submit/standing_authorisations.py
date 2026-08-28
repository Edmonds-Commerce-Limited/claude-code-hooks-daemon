"""StandingAuthorisationsHandler - replay authorisations a project recorded (Plan 00223).

A session's system prompt may carry instructions of the form "do not do X
**unless the user requested it**". Those instructions are not wrong, and this
handler does not argue with them. The gap they leave is that a project has
nowhere DURABLE to record a request it has genuinely made: the request is
given once in conversation, and the restriction is restated on every
subsequent request from a position the project cannot reach.

So this handler carries recorded authorisations forward. It is a filing
cabinet, not a countermand.

**Why UserPromptSubmit** (Plan 00223 Phase 1, measured against a real 37,475
record transcript spanning 18 compactions): SessionStart is a different
transport entirely (``hook_system_message``, never ``hook_additional_context``)
and its full payload was delivered exactly ONCE, because the prevailing
``is_resume_session`` gate is a transcript-size heuristic that is True for
every post-compaction session. UserPromptSubmit delivered 198 times, one per
prompt. The restriction being answered lives in a system prompt re-sent on
EVERY request, so only a per-prompt channel keeps pace with it.

**Cadence, not one-per-prompt** (Plan 00283). The original mechanism injected
the short-form text on EVERY prompt — reliable, but noisy, and it rode along on
every automated failsafe-recovery tick. It now delivers the FULL text once per
session to establish it, then reinforces only on whichever comes first:
``prompt_interval`` human prompts or ``interval_minutes`` elapsed. The 00223
reliability finding is preserved by a different mechanism, not abandoned: the
reinforcement still arrives many times per session and still survives
compaction — the silence between reinforcements is BOUNDED (at most
``prompt_interval`` prompts / ``interval_minutes``), which is nothing like the
unbounded once-ever silence that made SessionStart injection fail.

Automated turns (a failsafe-recovery cron tick, a goal-injection line, or this
handler's OWN supervisor-typed reinforcement — Plan 00283 Phase 2/3) arrive as
UserPromptSubmit events too. None is a human prompt, so none advances the
prompt counter or earns a reinforcement: that both removes the every-cron-tick
spam and gives the supervisor-channel loop-guard for free.

**Nothing is authorised by default** (Decision 3). The handler ships enabled
so the options are discoverable; every built-in entry ships disabled. Every
other default-on handler in this codebase ADDS a restriction — this one
removes one, and shipping that active would have the daemon fabricate the very
consent the injected text claims. ``config-changes/`` with ``recommended:
true`` is what carries the option to existing installs.

**The text is a recorded request, never a countermand** (Decision 2). Each
entry states that the PROJECT has authorised the behaviour and names the
config key holding it, so it can be audited and revoked. No entry tells the
agent to ignore, disregard or override anything — enforced by a test, because
that framing is both a worse prompt and a mechanism that should not exist.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase

# ── Config keys (mirrors command_hints' `_KEY_*` style) ────────────────────
_KEY_ID: Final[str] = "id"
_KEY_ENABLED: Final[str] = "enabled"

# ── Built-in authorisation ids ─────────────────────────────────────────────
# One id per distinct restriction: Phase 1 found the system prompt carries
# separate restrictions, and authorising delegation says nothing about
# authorising workflow orchestration — nor about push cadence, which exists
# because "confirm before outward-facing actions" defaults hold pushes back
# in projects that want git as their primary backup.
AUTHORISATION_SUBAGENT_DELEGATION: Final[str] = "subagent-delegation"
AUTHORISATION_WORKFLOWS: Final[str] = "workflow-orchestration"
AUTHORISATION_COMMIT_PUSH_CADENCE: Final[str] = "commit-push-cadence"

# Where a reader can audit and revoke any of this. Named in every entry's
# text: an authorisation that cannot be found is not auditable, and one that
# cannot be revoked is not a request.
_CONFIG_LOCATION: Final[str] = (
    ".claude/hooks-daemon.yaml under "
    "handlers.user_prompt_submit.standing_authorisations.options.authorisations"
)

_SUBAGENT_DELEGATION_TEXT: Final[str] = (
    "STANDING AUTHORISATION (on file for this project). Sub-agent delegation "
    "is pre-requested here: this project asks that you use the Agent tool on "
    "your own initiative wherever it genuinely helps — parallel investigation, "
    "keeping a large search out of the main context, a second opinion on a "
    "risky change — without pausing to ask permission each time. Judgement "
    "still applies: delegate when it earns its cost, not by reflex, and "
    "prefer isolated worktrees when peers may touch the same git index. "
    f"This request is recorded in {_CONFIG_LOCATION}, where it can be read "
    "and withdrawn."
)

_COMMIT_PUSH_CADENCE_TEXT: Final[str] = (
    "STANDING AUTHORISATION (on file for this project). A frequent "
    "commit-and-push cadence is pre-requested here: after each logical unit "
    "of work, commit AND push in the same step — git is the primary backup, "
    "and a commit that only exists locally is not backed up, is invisible to "
    "the humans and other sessions watching the remote, and is lost with the "
    "workspace. Do not batch pushes behind long-running checks or milestones; "
    "if a later check finds a problem, fix forward with a new commit. "
    "Pushed history is never rewritten. "
    f"This request is recorded in {_CONFIG_LOCATION}, where it can be read "
    "and withdrawn."
)

_WORKFLOWS_TEXT: Final[str] = (
    "STANDING AUTHORISATION (on file for this project). Multi-agent workflow "
    "orchestration is pre-requested here: this project has opted in to "
    "workflow runs, so treat that opt-in as standing rather than seeking it "
    "per task. Scale still matters — a workflow can spend a great deal for a "
    "task a single agent would finish, so match the shape of the run to the "
    "size of the problem. "
    f"This request is recorded in {_CONFIG_LOCATION}, where it can be read "
    "and withdrawn."
)

# ── Short forms, used for every reinforcement after the first delivery ──────
# The short form still names where the request is recorded, because an
# authorisation that cannot be audited is not a request.
_SUBAGENT_DELEGATION_SHORT: Final[str] = (
    "STANDING AUTHORISATION (on file): sub-agent delegation is pre-requested "
    "for this project — use the Agent tool on your own initiative where it "
    "helps, no need to ask. Recorded in .claude/hooks-daemon.yaml."
)

_COMMIT_PUSH_CADENCE_SHORT: Final[str] = (
    "STANDING AUTHORISATION (on file): commit AND push after each logical "
    "unit of work — git is the primary backup; never hold pushes behind "
    "long checks. Recorded in .claude/hooks-daemon.yaml."
)

_WORKFLOWS_SHORT: Final[str] = (
    "STANDING AUTHORISATION (on file): multi-agent workflow orchestration is "
    "pre-requested for this project — treat the opt-in as standing. Recorded "
    "in .claude/hooks-daemon.yaml."
)

# The built-in set. Every entry ships DISABLED (Decision 3) — the set exists so
# the options are discoverable and adopting one is a single flag, not so that
# anything is authorised on a fresh install.
_BUILTIN_TEXTS: Final[dict[str, str]] = {
    AUTHORISATION_SUBAGENT_DELEGATION: _SUBAGENT_DELEGATION_TEXT,
    AUTHORISATION_WORKFLOWS: _WORKFLOWS_TEXT,
    AUTHORISATION_COMMIT_PUSH_CADENCE: _COMMIT_PUSH_CADENCE_TEXT,
}

_BUILTIN_SHORT_TEXTS: Final[dict[str, str]] = {
    AUTHORISATION_SUBAGENT_DELEGATION: _SUBAGENT_DELEGATION_SHORT,
    AUTHORISATION_WORKFLOWS: _WORKFLOWS_SHORT,
    AUTHORISATION_COMMIT_PUSH_CADENCE: _COMMIT_PUSH_CADENCE_SHORT,
}

# ── Cadence defaults (Plan 00283) ──────────────────────────────────────────
# First delivery per session is the full text; thereafter reinforce on
# whichever fires first: this many human prompts, or this many minutes elapsed
# since the last delivery. Small enough that the authorisation is never absent
# for long; large enough that it is not on every prompt.
_DEFAULT_PROMPT_INTERVAL: Final[int] = 5
_DEFAULT_INTERVAL_MINUTES: Final[float] = 15.0
_SECONDS_PER_MINUTE: Final[int] = 60

# Known machine-origin prompt markers. A UserPromptSubmit whose text carries one
# of these is an AUTOMATED turn — a failsafe-recovery cron tick, a
# goal-injection line, or this handler's own supervisor-typed reinforcement —
# never a human prompt. Such a turn must neither advance the prompt counter nor
# earn a reinforcement. Matching a small set of STABLE, self-authored markers is
# the robust alternative to guessing from arbitrary prose: Claude Code exposes
# no automated-vs-human flag on the event. The ccy-supervisor marker also gives
# the Plan 00283 Phase 2/3 loop-guard for free — the supervisor-typed
# reinforcement this handler emits carries it, so it can never re-trigger
# itself.
_FAILSAFE_RECOVERY_MARKER: Final[str] = "FAILSAFE RECOVERY CHECK"
_CCY_SUPERVISOR_MARKER: Final[str] = "🤖 [ccy-supervisor]"
_AUTOMATED_PROMPT_MARKERS: Final[tuple[str, ...]] = (
    _FAILSAFE_RECOVERY_MARKER,
    _CCY_SUPERVISOR_MARKER,
)

# Bound the per-session state map so a long-lived daemon cannot leak memory
# across many sessions. Same FIFO-eviction shape as command_hints._fire_state.
_MAX_TRACKED_SESSIONS: Final[int] = 512

_UNKNOWN_SESSION: Final[str] = "unknown"


@dataclass
class _SessionState:
    """Per-session cadence state (Plan 00283).

    `delivered_once` gates the first (full) delivery; after it, a reinforcement
    fires when `prompts_since_last` reaches the prompt interval OR the wall
    clock passes `last_delivery_ts + interval`. Reset to a fresh instance means
    a new session, which gets the full text again.
    """

    delivered_once: bool = False
    last_delivery_ts: float = 0.0
    prompts_since_last: int = 0


class StandingAuthorisationsHandler(UserPromptSubmitHandlerBase):
    """Inject the authorisations a project has recorded in its config.

    ADVISORY ONLY: never blocks, never denies, never terminal. Silent unless a
    project has explicitly enabled at least one entry.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.STANDING_AUTHORISATIONS,
            priority=Priority.STANDING_AUTHORISATIONS,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        # Config options — injected by the registry via setattr; typed and
        # defaulted here so mypy sees real attributes, not dynamic ones.
        #
        # Typed `list[Any]`, NOT `list[dict[str, Any]]`: this is arbitrary
        # user-authored YAML, so claiming every element is a dict would be a
        # type the boundary cannot honour — and mypy rightly called the
        # isinstance guard below redundant against that false promise. The
        # guard is the validation (Core Standard 14); the type must not lie
        # about what has already been validated.
        self._authorisations: list[Any] | None = None

        # Cadence options (Plan 00283) — tunable via config; defaulted here.
        self._prompt_interval: int = _DEFAULT_PROMPT_INTERVAL
        self._interval_minutes: float = _DEFAULT_INTERVAL_MINUTES

        # Per-session cadence state — bounded, FIFO.
        self._session_states: dict[str, _SessionState] = {}

        # Injectable wall clock (tests substitute a fake). Not a config option.
        self._clock: Callable[[], float] = time.time

    def _enabled_ids(self) -> set[str]:
        """Return the ids a project has explicitly enabled.

        An entry naming an id with no built-in text is ignored rather than
        raising: a config typo must not take the daemon down, and a silently
        absent advisory is the correct failure for an advisory handler.
        """
        configured = self._authorisations or []
        return {
            str(entry.get(_KEY_ID))
            for entry in configured
            if isinstance(entry, dict) and entry.get(_KEY_ENABLED) is True
        }

    def _resolve_entries(self, *, short: bool = False) -> list[str]:
        """Return the text of every ENABLED authorisation, in built-in order."""
        enabled = self._enabled_ids()
        texts = _BUILTIN_SHORT_TEXTS if short else _BUILTIN_TEXTS
        return [text for entry_id, text in texts.items() if entry_id in enabled]

    @staticmethod
    def _is_automated_prompt(prompt: str) -> bool:
        """True when the prompt text carries a known machine-origin marker."""
        return any(marker in prompt for marker in _AUTOMATED_PROMPT_MARKERS)

    def _state_for(self, session_id: str) -> _SessionState:
        """Return this session's cadence state, creating it (bounded, FIFO)."""
        existing = self._session_states.get(session_id)
        if existing is not None:
            return existing
        if len(self._session_states) >= _MAX_TRACKED_SESSIONS:
            # FIFO eviction — dicts preserve insertion order.
            oldest = next(iter(self._session_states))
            del self._session_states[oldest]
        state = _SessionState()
        self._session_states[session_id] = state
        return state

    def _is_due(self, state: _SessionState, now: float) -> bool:
        """Whether a reinforcement is due for an already-established session."""
        by_prompts = state.prompts_since_last >= self._prompt_interval
        elapsed = now - state.last_delivery_ts
        by_time = elapsed >= self._interval_minutes * _SECONDS_PER_MINUTE
        return by_prompts or by_time

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match any prompt-bearing UserPromptSubmit event."""
        return isinstance(hook_input.get(HookInputField.PROMPT), str)

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Deliver the enabled authorisations on the Plan 00283 cadence.

        First human prompt of a session → full text. Thereafter, silent until a
        reinforcement is due (prompt-count OR time), then the short form.
        Automated turns are ignored entirely: they neither count nor deliver.
        """
        if not self._enabled_ids():
            return BlockingResult(decision=Decision.ALLOW, context=[])

        prompt = str(hook_input.get(HookInputField.PROMPT, "") or "")
        if self._is_automated_prompt(prompt):
            # A cron tick / goal line / our own supervisor-typed reinforcement:
            # not a human prompt, so it earns nothing and advances nothing.
            return BlockingResult(decision=Decision.ALLOW, context=[])

        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or _UNKNOWN_SESSION)
        state = self._state_for(session_id)
        now = self._clock()

        if not state.delivered_once:
            # Establish the authorisation once, in full, immediately.
            state.delivered_once = True
            state.last_delivery_ts = now
            state.prompts_since_last = 0
            return BlockingResult(decision=Decision.ALLOW, context=self._resolve_entries())

        state.prompts_since_last += 1
        if not self._is_due(state, now):
            return BlockingResult(decision=Decision.ALLOW, context=[])

        # Reinforce in the short form, and reset the cadence window.
        state.last_delivery_ts = now
        state.prompts_since_last = 0
        return BlockingResult(decision=Decision.ALLOW, context=self._resolve_entries(short=True))

    def get_claude_md(self) -> str | None:
        """Document the SETTING, deliberately without restating the authorisations.

        Phase 1 measured CLAUDE.md as the lowest-position lever of four, so a
        second copy of the authorisation text here would be the copy that goes
        stale while still reading as authoritative. It points at the config
        instead.
        """
        return (
            "## standing_authorisations — a project can record a standing request\n\n"
            "Some instructions are conditional on the user having asked "
            '("unless the user requested it"). A request made in conversation '
            "does not survive the session, so this project can record one in "
            "config instead, and the daemon replays it.\n\n"
            "**Cadence (Plan 00283)**: the FULL text is delivered once per "
            "session to establish it, then reinforced only on whichever comes "
            "first — a few human prompts, or a set number of minutes elapsed. "
            "Automated turns (failsafe-recovery ticks, goal-injection lines) "
            "neither count nor trigger a reinforcement, so the reminder does "
            "not ride every cron tick.\n\n"
            "Configured in `.claude/hooks-daemon.yaml` under "
            "`handlers.user_prompt_submit.standing_authorisations.options.authorisations`, "
            "as a list of `{id, enabled}` entries. Built-in ids: "
            f"`{AUTHORISATION_SUBAGENT_DELEGATION}`, `{AUTHORISATION_WORKFLOWS}`, "
            f"`{AUTHORISATION_COMMIT_PUSH_CADENCE}`.\n\n"
            "**Every entry ships disabled.** The handler is enabled so the "
            "options are discoverable, but nothing is authorised until the "
            "project turns it on — the daemon must never assert consent that "
            "was not given. Enabling one is a deliberate act by whoever owns "
            "the repository, and removing it withdraws the authorisation.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Standing authorisations are silent until a project enables one",
                command='echo "test"',
                description=(
                    "Default state check. With no authorisations enabled (the"
                    " shipped default), submitting a prompt must inject NO"
                    " standing-authorisation context. Verify by submitting a"
                    " prompt and confirming no 'STANDING AUTHORISATION' text"
                    " appears in the system-reminders."
                ),
                expected_decision=Decision.ALLOW,
                # Deliberately empty: this test asserts that NOTHING is
                # injected in the shipped default state.
                expected_message_patterns=[],
                safety_notes=(
                    "Advisory only - never blocks. This test asserts ABSENCE, so"
                    " it fails loudly if the daemon ever starts asserting an"
                    " authorisation the project did not record."
                ),
                test_type=TestType.CONTEXT,
                requires_event="UserPromptSubmit event (cannot be triggered by subagent)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
