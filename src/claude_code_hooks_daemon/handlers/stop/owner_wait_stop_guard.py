"""OwnerWaitStopGuardHandler - a coordinator waiting on a human must have told them on the bus.

Plan 00636 Task 2.1a; design in 00630 DESIGN.md section 20.1 (owner HARD
requirement). The team chat is the only human surface: a ``STOPPING
BECAUSE: waiting on ...`` that reaches only the Claude Code terminal is never
seen. So a coordinator seat's waiting stop is refused unless every open
owner-facing thread the seat asked or owns got a NOTIFYING post from this seat,
with a non-boilerplate body, within ``options.window_minutes``. The decision is
:func:`utils.owner_wait_check.stale_threads` (ids, timestamps, notify flag; no
judgement); every bus read and command goes through
:mod:`utils.owner_wait_bus`.

**Who it applies to.** A Stop on the main thread whose session carries a
teamchat runtime, whose text (anywhere after ``STOPPING BECAUSE:``, outside
fences and quotes, ordinary wordings such as "blocked on the owner", "need
Joseph to pick", "the owner must answer"; a negated match like "not waiting on
any user input" does not count) waits on a human or whose session is in the
awaiting-human mode, and
per held team only where the 00631 probe declares this seat ``coordinator``
(:func:`role_gate` verdict APPLIES). A declared worker (any other role), no
team or a sub-agent leaves the stop untouched and reads nothing. An unknown
role or an unresolved probe stays ARMED (00631 ``guards_armed``: an unreadable
state never disarms a seat): it is an unconfirmed wait under
``options.on_unreadable_bus``, without a bus read. A stop whose
message cannot be read is treated as an unconfirmed wait for each coordinator
team, under ``options.on_unreadable_bus`` (the bus is not read).

**An unreadable bus** (the adapter reports it, or raises) is governed by
``options.on_unreadable_bus``. ``refuse`` fails CLOSED, because an
unconfirmable wait is exactly the silent wait this guard exists to stop; the
refusal tells the coordinator to post a notifying reply in each thread and stop
again, and says why nothing could be confirmed. ``allow`` fails open with a
WARNING log. ``auto`` (default) is ``refuse`` where the adapter's
``flags_readable()`` is True, and otherwise (pingbus v1, where no post could
ever be confirmed) fails open by design with an ADVISORY in the stop's context
naming the team and the thread classes left unchecked. The WARNING is always
written.

**A fault fails closed.** Any exception while checking (seat probe, wait
detection, stale check, rendering) denies an armed coordinator's stop once,
whatever ``on_unreadable_bus`` says, with static text; a seat provably not
armed (a declared worker) is allowed. Faults in ``matches()`` are passed to
``handle()`` for that decision; only the re-entry check stands down on a fault.

**Never a trap.** A stop that re-enters after THIS guard's deny (its rule id in
a recent Stop-hook block) is allowed: one refusal per stop chain. Another
handler's deny, or a spurious ``stop_hook_active`` with no block marker, is
evaluated like a fresh stop, as auto_continue_stop does; a re-entry whose
transcript cannot be read stands down (N411), and a re-entered stop never
repeats the ``auto`` advisory. It also stands aside while the session is
usage-paused.

**Ordering.** Priority 3, ahead of ``idle_workable_issue_stop_gate`` (4) and the
terminal ``auto_continue_stop`` (15 by default, 10 in this project's config);
non-terminal, so those still run. Because
it runs before ``auto_continue_stop`` enters the awaiting-human mode, it reads
the current message for the declaration as well as the mode. The chain shows
only the first deny, so on an ``[awaiting-human]`` stop this deny also carries
auto_continue_stop's stand-in requirement (one shared gate,
:func:`utils.stand_in_cron.stand_in_requirement`).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, TeamSeatConfig
from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import StopHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.daemon.synthetic_traffic import event_synthetic_source
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
    _declares_human_blocked,
    _declaring_lines,
    _quoted_spans,
)
from claude_code_hooks_daemon.utils.autonomy import session_policy
from claude_code_hooks_daemon.utils.config_cache import default_config, load_config_cached
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.owner_wait_bus import (
    NOTIFY_PROGRAM,
    TEAM_PLACEHOLDER,
    BusUnreadable,
    OwnerWaitBus,
    TeamchatOwnerWaitBus,
)
from claude_code_hooks_daemon.utils.owner_wait_check import (
    BusSnapshot,
    printable_thread_id,
    stale_threads,
)
from claude_code_hooks_daemon.utils.stand_in_cron import (
    configured_delay_hours,
    stand_in_requirement,
)
from claude_code_hooks_daemon.utils.stop_hook_helpers import (
    get_transcript_reader,
    is_stop_hook_active,
    recent_stop_hook_block_texts,
    transcript_is_readable,
)
from claude_code_hooks_daemon.utils.team_role_gate import GateVerdict, role_gate
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ROLE_COORDINATOR,
    SeatContext,
    SeatContextResolver,
    SeatState,
    SessionSignals,
)
from claude_code_hooks_daemon.utils.usage_pause_gate import hook_is_usage_paused

logger = logging.getLogger(__name__)

#: How recent a notifying post must be. Provisional until Plan 00636 Task 1.1 settles N.
DEFAULT_WINDOW_MINUTES: Final[int] = 30
MAX_WINDOW_MINUTES: Final[int] = 24 * 60
ON_UNREADABLE_AUTO: Final[str] = "auto"
ON_UNREADABLE_REFUSE: Final[str] = "refuse"
ON_UNREADABLE_ALLOW: Final[str] = "allow"
DEFAULT_ON_UNREADABLE_BUS: Final[str] = ON_UNREADABLE_AUTO
_ON_UNREADABLE_VALUES: Final[frozenset[str]] = frozenset(
    {ON_UNREADABLE_AUTO, ON_UNREADABLE_REFUSE, ON_UNREADABLE_ALLOW}
)
_SECONDS_PER_MINUTE: Final[int] = 60
_STOP_PREFIX: Final[str] = "STOPPING BECAUSE:"
#: How far back a re-entered stop looks for this guard's own refusal: wide enough
#: for the bump turn between the deny and the re-stop (the helper's own default is 20).
_REENTRY_LOOKBACK_LINES: Final[int] = 200
#: What a wait is ON: a human, or a human's answer. Object slots stay inside one clause.
_HUMAN: Final[str] = (
    r"(?:owner|human|user|answers?|repl(?:y|ies)|decision|input|approval|sign[- ]?off"
    r"|ruling|go-ahead|choice|confirmation|response)"
)
#: A named person: an ``@handle`` or a capitalised name (``Joseph``, not ``CI`` or ``GitHub``).
_PERSON: Final[str] = r"(?:@\w+|(?-i:[A-Z][a-z]+)\b)"
_WHO: Final[str] = rf"(?:(?:the\s+)?(?:owner|human|user)|{_PERSON})"
_ACTS: Final[str] = r"(?:answer|decide|choose|pick|confirm|approve|reply|respond|rule|review|sign)"
_CLAUSE: Final[str] = r"[^.;:!?\n]*?"
#: Ordinary waiting wordings (Plan 00636 F2), searched across the whole declaring
#: text after ``STOPPING BECAUSE:``. ``[awaiting-human]`` and the frozen prose
#: are matched by auto_continue_stop's own test first.
_WAITING_RE: Final[re.Pattern[str]] = re.compile(
    "|".join(
        [
            rf"\b(?:wait(?:ing)?\s+(?:on|for)|awaiting|blocked\s+(?:on|by)|pending)\b"
            rf"(?:{_CLAUSE}\b{_HUMAN}\b|\s+{_PERSON})",
            rf"\bneeds?\s+(?:{_WHO}\s+to\b|(?:an?\s+|the\s+|their\s+|your\s+)?{_HUMAN}\b)",
            rf"\b{_WHO}\s+(?:must|has\s+to|needs\s+to|should|to)\s+{_ACTS}",
            rf"\buntil\s+{_WHO}\s+{_ACTS}",
        ]
    ),
    re.IGNORECASE,
)
#: A negation that governs the match: adjacent to it, at the end of its clause prefix.
_NEGATED_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:\b(?:not|no|never|nothing)|n't)"
    r"(?:\s+(?:longer|really|currently|actually|even|yet|anymore|any\s+more))?\s*$",
    re.IGNORECASE,
)
#: Clause breaks: sentence punctuation, a spaced dash (ASCII, en or em), or "but".
_CLAUSE_BREAK_RE: Final[re.Pattern[str]] = re.compile(
    "[.;:!?\\n]|\\s[-\\u2013\\u2014]+\\s|\\bbut\\b", re.IGNORECASE
)

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.STOP_OWNER_WAIT_UNBUMPED,
    blocked=(
        "a coordinator-seat stop that waits on a human while an open owner-facing thread "
        "has no recent notifying post from this seat, or while the bus cannot confirm one"
    ),
    why=(
        "The team chat is the only human surface: a wait stated only in the terminal is never "
        "seen, and a post that does not notify lands silently"
    ),
    fix=(
        "Run the one bump command the deny prints (or post a notifying `pingbus thread ... --ask` "
        "reply in each thread), then stop again"
    ),
    verbose=(
        "Applies per team where the teamchat probe declares this seat coordinator, on a\n"
        "main-thread stop that waits on a human (reason text or awaiting-human mode). Every\n"
        "open question the seat asked or owns, and every owner-started thread, needs a\n"
        "NOTIFYING post from this seat with a real body within options.window_minutes;\n"
        "an unreadable notify flag or thread relation counts as not notifying. An\n"
        "unreadable bus, stop message or seat role (or an unresolved seat probe)\n"
        "follows options.on_unreadable_bus: 'auto' (default) refuses where\n"
        "the adapter reads notify flags and otherwise allows with an advisory; 'refuse'\n"
        "always refuses; 'allow' fails open with a log line. The deny names thread ids\n"
        "only, never the waits.\n"
        "One deny per stop chain: the re-stop after this rule's own deny is allowed;\n"
        "a re-stop after another handler's deny is checked again."
    ),
)


class _Waiting(Enum):
    """Whether a stop waits on a human. UNREADABLE: the stop message could not be read."""

    YES = "yes"
    NO = "no"
    UNREADABLE = "unreadable"


#: The ``_Unconfirmed`` reason when the stop message itself could not be read.
_UNREADABLE_STOP_REASON: Final[str] = (
    "the stop message could not be read, so whether it waits on a human is unknown"
)

#: ``_Unconfirmed`` reasons when this seat's role cannot be read (F4: these stay armed).
_UNKNOWN_ROLE_REASON: Final[str] = (
    "this seat's role in the team is unreadable, so it may be the coordinator"
)
_UNRESOLVED_PROBE_REASON: Final[str] = (
    "the team seat probe gave no answer, so neither the team nor this seat's role is known"
)
#: The F5 deny, static so nothing that may itself be faulting renders it.
_FAIL_CLOSED_REASON: Final[str] = (
    "You may be stopping to wait on a human, as a team coordinator, and the owner-wait check "
    "failed before it could confirm the owner was told on the team chat, so the stop fails "
    "closed. Post a notifying reply in each owner-started thread "
    f"(`{NOTIFY_PROGRAM} --team {TEAM_PLACEHOLDER} --re <event id> --ask`) and on each open "
    f"question this seat asked (`{NOTIFY_PROGRAM} --team {TEAM_PLACEHOLDER} Q<n> --ask`), "
    "naming what is awaited. Then stop again; this refusal is not repeated."
)
#: Unconfirmed reasons that are not about the bus history, so the deny omits the bus note.
_NOT_BUS_REASONS: Final[frozenset[str]] = frozenset(
    {_UNKNOWN_ROLE_REASON, _UNRESOLVED_PROBE_REASON, _UNREADABLE_STOP_REASON}
)


@dataclass(frozen=True)
class _Unconfirmed:
    """A coordinator team whose bus could not be read. ``reason`` is a category, never bus text."""

    team: str
    reason: str


@dataclass(frozen=True)
class _Stale:
    """A coordinator team with open threads that lack a recent notifying post."""

    team: str
    thread_ids: tuple[str, ...]


class OwnerWaitStopGuardHandler(StopHandlerBase):
    """Refuse a coordinator's waiting stop until the owner was told, notifying, on the bus."""

    def __init__(self) -> None:
        """Initialise as a non-terminal blocking Stop handler (see the module docstring)."""
        super().__init__(
            handler_id=HandlerID.OWNER_WAIT_STOP_GUARD,
            priority=Priority.OWNER_WAIT_STOP_GUARD,
            terminal=False,
            scope=HandlerScope.MAIN,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.NON_TERMINAL],
        )
        # Options, injected by the registry from ``options.<name>``; validated at use.
        self._window_minutes: object = DEFAULT_WINDOW_MINUTES
        self._on_unreadable_bus: object = DEFAULT_ON_UNREADABLE_BUS
        # Seams, not config options.
        self._bus: OwnerWaitBus = TeamchatOwnerWaitBus()
        self._clock: Callable[[], float] = time.time
        self._resolver: SeatContextResolver | None = None
        self._config_loader: Callable[[], Config] = self._default_config_loader

    def get_default_enabled(self) -> bool:
        """On by default; inert outside a teamchat coordinator seat."""
        return True

    # -- options -----------------------------------------------------------------

    def _window_seconds(self) -> float:
        value = self._window_minutes
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            or value > MAX_WINDOW_MINUTES
        ):
            logger.warning(
                "owner_wait_stop_guard: options.window_minutes=%r is not an integer in 1..%d; "
                "using the default %d",
                value,
                MAX_WINDOW_MINUTES,
                DEFAULT_WINDOW_MINUTES,
            )
            value = DEFAULT_WINDOW_MINUTES
        return float(value * _SECONDS_PER_MINUTE)

    def _unreadable_policy(self) -> str:
        value = self._on_unreadable_bus
        if isinstance(value, str) and value in _ON_UNREADABLE_VALUES:
            return value
        logger.warning(
            "owner_wait_stop_guard: options.on_unreadable_bus=%r is not 'auto', 'refuse' or "
            "'allow'; using the default %r",
            value,
            DEFAULT_ON_UNREADABLE_BUS,
        )
        return DEFAULT_ON_UNREADABLE_BUS

    def _refuses_unreadable(self, policy: str) -> bool:
        """Whether an unreadable team is refused: ``auto`` refuses only where flags are readable.

        A raising probe counts as unreadable flags, so ``auto`` allows with the
        advisory rather than refusing a wait no post could ever satisfy.
        """
        if policy != ON_UNREADABLE_AUTO:
            return policy == ON_UNREADABLE_REFUSE
        try:
            return self._bus.flags_readable() is True
        except Exception as exc:  # the adapter is a boundary; any fault is "cannot read flags"
            log_and_continue(
                logger,
                exc,
                reason="a raising flags_readable probe means the flags cannot be read, so auto allows with an advisory",
            )
            return False

    # -- seams -------------------------------------------------------------------

    def _default_config_loader(self) -> Config:
        root = getattr(self, "_workspace_root", None)
        try:
            project_root = Path(root) if root is not None else ProjectContext.project_root()
            return load_config_cached(project_root / ".claude" / "hooks-daemon.yaml")
        except (ValidationError, OSError, ValueError, RuntimeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="an unlocatable or unloadable project config falls back to the defaults: the team_seat block still probes a session carrying a teamchat runtime, and no stand-in cron is asked for",
            )
            return default_config()

    def _team_seat_config(self) -> TeamSeatConfig:
        return self._config_loader().team_seat

    def _stand_in_reason(self, hook_input: dict[str, Any]) -> str | None:
        """auto_continue_stop's stand-in requirement for this stop, which this deny would hide.

        The chain shows only the first restrictive reason and the re-stop is a
        confirmed re-entry, so unless this deny carries it the stand-in cron is
        never asked for (Plan 00636 F1). Same gate as auto_continue_stop: the
        current message declares ``[awaiting-human]`` and the event is real.
        """
        if event_synthetic_source(hook_input) is not None:
            return None
        reader = get_transcript_reader(hook_input)
        text = reader.get_last_assistant_text() if reader is not None else ""
        if not text or not _declares_human_blocked(text):
            return None
        config = self._config_loader()
        requirement = stand_in_requirement(
            hook_input, config=config, delay_hours=configured_delay_hours(config)
        )
        return None if requirement is None else requirement.reason

    def _resolve_seats(self, signals: SessionSignals) -> SeatContext:
        """The 00631 seat context for this session (TTL-cached by the resolver)."""
        if self._resolver is None:
            self._resolver = SeatContextResolver.from_config(self._team_seat_config())
        return self._resolver.resolve(signals)

    # -- matching ----------------------------------------------------------------

    @staticmethod
    def _text_declares_waiting(text: str) -> bool:
        """Whether the declaring text after ``STOPPING BECAUSE:`` waits on a human.

        Searches every declaring line after the first prefix (a wait on the next
        line counts), with quoted spans blanked so a cited phrase does not
        declare, and skips a match negated at the end of its own clause
        (``not waiting on any user input``).
        """
        declaring = _declaring_lines(text)
        if _declares_human_blocked(declaring):
            return True
        _, prefix, body = declaring.partition(_STOP_PREFIX)
        if not prefix:
            return False
        for start, end in _quoted_spans(body):
            body = body[:start] + " " * (end - start) + body[end:]
        for match in _WAITING_RE.finditer(body):
            before = body[: match.start()]
            breaks = list(_CLAUSE_BREAK_RE.finditer(before))
            clause = before[breaks[-1].end() :] if breaks else before
            if not _NEGATED_PREFIX_RE.search(clause):
                return True
        return False

    def _waiting(self, hook_input: dict[str, Any]) -> _Waiting:
        """Whether this stop waits on a human: the mode, else the stop text, else unknown."""
        try:
            if session_policy(hook_input).is_blocked:
                return _Waiting.YES
        except (RuntimeError, OSError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="the session-modes registry is unreadable, so only the stop text can show a wait on a human",
            )
        reader = get_transcript_reader(hook_input)
        if reader is None:
            return _Waiting.UNREADABLE
        text = reader.get_last_assistant_text()
        return _Waiting.YES if text and self._text_declares_waiting(text) else _Waiting.NO

    @staticmethod
    def _reenters_own_refusal(hook_input: dict[str, Any]) -> bool:
        """Whether a ``stop_hook_active`` stop is the re-stop after THIS guard's refusal.

        Mirrors auto_continue_stop's discrimination (Plan 00636 F3): another
        handler's deny, or Claude Code's spurious flag with no marker at all, is
        evaluated like a fresh stop. Only this guard's rule id in a recent block
        earns the pass, anywhere in the window, so a later deny by another
        handler or a long bump turn does not cost a second refusal. A transcript
        that cannot be read, or a raising read, stands down (N411): a
        re-entry nothing can verify must never be refused again.
        """
        path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if not transcript_is_readable(path):
            return True
        try:
            texts = recent_stop_hook_block_texts(path, lookback=_REENTRY_LOOKBACK_LINES)
        except Exception as exc:  # an unverifiable re-entry stands down, whatever the fault
            log_and_continue(
                logger,
                exc,
                reason="a re-entry this guard cannot verify stands down rather than refuse again (N411)",
            )
            return True
        return any(RuleID.STOP_OWNER_WAIT_UNBUMPED in text for text in texts)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A waiting, unpaused stop in a team session that is not the re-stop after our deny."""
        if hook_is_usage_paused(hook_input):
            return False
        if not SessionSignals.from_hook_input(hook_input).runtime:
            return False
        if is_stop_hook_active(hook_input) and self._reenters_own_refusal(hook_input):
            return False
        try:
            return self._waiting(hook_input) is not _Waiting.NO
        except Exception as exc:  # handle() decides: it fails closed for an armed seat (F5)
            log_and_continue(
                logger,
                exc,
                reason="a fault detecting the wait is passed to handle(), which fails closed for an armed seat",
            )
            return True

    # -- handling ----------------------------------------------------------------

    def _read(self, team: str, signals: SessionSignals) -> BusSnapshot | BusUnreadable:
        try:
            return self._bus.read(team, signals)
        except Exception as exc:  # the adapter is a boundary; any fault is "unreadable"
            log_and_continue(
                logger,
                exc,
                reason="a raising bus adapter is an unreadable bus; options.on_unreadable_bus decides",
            )
            return BusUnreadable(f"the bus adapter raised {type(exc).__name__}")

    @staticmethod
    def _armed_teams(
        hook_input: dict[str, Any], context: SeatContext
    ) -> list[tuple[str, str | None]]:
        """Each team this guard is armed for, with why its role is unknown (None: coordinator).

        00631 ``guards_armed``: a declared coordinator is checked on the bus; an
        unreadable role, or a probe that resolved no seats at all, is an
        unconfirmed wait under ``options.on_unreadable_bus`` (the bus is not
        read, the seat may be a worker). A declared other role, no team and a
        sub-agent are untouched: :func:`role_gate` says NOT_APPLICABLE.
        """
        if context.state is SeatState.UNRESOLVED:
            gate = role_gate(hook_input, context, team="", role=ROLE_COORDINATOR)
            if gate.verdict is GateVerdict.ROLE_UNKNOWN:
                return [(TEAM_PLACEHOLDER, _UNRESOLVED_PROBE_REASON)]
            return []
        armed: list[tuple[str, str | None]] = []
        for team in context.teams_held():
            gate = role_gate(hook_input, context, team=team, role=ROLE_COORDINATOR)
            if gate.verdict is GateVerdict.APPLIES:
                armed.append((gate.team, None))
            elif gate.verdict is GateVerdict.ROLE_UNKNOWN:
                armed.append((gate.team, _UNKNOWN_ROLE_REASON))
        return armed

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Run the check; any fault for an armed seat FAILS CLOSED, whatever the policy (F5).

        ``on_unreadable_bus`` governs a bus (or stop message, or role) the guard
        could not read; a fault in the guard itself is not a reading it could
        weigh, so an armed coordinator's stop is denied once with static text
        (the re-stop is this rule's own re-entry, so it never loops). A seat
        that is provably not armed (a declared worker) is allowed.
        """
        try:
            return self._check(hook_input)
        except Exception as exc:  # fail closed for an armed seat; the reason carries no fault text
            log_and_continue(
                logger,
                exc,
                reason="a fault while checking a waiting stop fails closed for an armed coordinator seat",
                level=logging.WARNING,
            )
            if not self._armed_or_unknown(hook_input):
                return BlockingResult(decision=Decision.ALLOW)
            return BlockingResult.deny(_FAIL_CLOSED_REASON).under_rule(_RULE)

    def _armed_or_unknown(self, hook_input: dict[str, Any]) -> bool:
        """Whether any team arms this guard; a fault deciding that counts as armed."""
        try:
            context = self._resolve_seats(SessionSignals.from_hook_input(hook_input))
            return bool(self._armed_teams(hook_input, context))
        except Exception as exc:  # an unreadable seat state never disarms (00631 guards_armed)
            log_and_continue(
                logger,
                exc,
                reason="the seat state could not be read after a fault, so the seat counts as armed",
            )
            return True

    def _check(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Deny on stale threads or a refused unconfirmed team; ``auto`` on v1 adds an advisory."""
        waiting = self._waiting(hook_input)
        if waiting is _Waiting.NO:
            return BlockingResult(decision=Decision.ALLOW)
        signals = SessionSignals.from_hook_input(hook_input)
        context = self._resolve_seats(signals)
        policy = self._unreadable_policy()
        window = self._window_seconds()
        stale: list[_Stale] = []
        unconfirmed: list[_Unconfirmed] = []
        unchecked: list[_Unconfirmed] = []
        for team, role_unread in self._armed_teams(hook_input, context):
            if role_unread is not None:
                snapshot: BusSnapshot | BusUnreadable = BusUnreadable(role_unread)
            elif waiting is _Waiting.UNREADABLE:
                snapshot = BusUnreadable(_UNREADABLE_STOP_REASON)
            else:
                snapshot = self._read(team, signals)
            if isinstance(snapshot, BusUnreadable):
                refused = self._refuses_unreadable(policy)
                logger.warning(
                    "owner_wait_stop_guard: team %s unconfirmed (%s); on_unreadable_bus=%s, "
                    "so the waiting stop is %s",
                    team,
                    snapshot.reason,
                    policy,
                    "refused" if refused else "allowed unverified",
                )
                if refused:
                    unconfirmed.append(_Unconfirmed(team, snapshot.reason))
                elif policy == ON_UNREADABLE_AUTO:
                    unchecked.append(_Unconfirmed(team, snapshot.reason))
                continue
            ids = stale_threads(snapshot, now=self._clock(), window_seconds=window)
            if ids:
                stale.append(_Stale(team, ids))
        # A re-entered stop never repeats the advisory: an ALLOW with context
        # continues the session one turn, and re-emitting it would loop.
        advisory = (
            []
            if is_stop_hook_active(hook_input)
            else [self._render_unchecked(gap) for gap in unchecked]
        )
        if not stale and not unconfirmed:
            return BlockingResult(decision=Decision.ALLOW, context=advisory)
        reason = "\n\n".join([self._render(stale, unconfirmed, window), *advisory])
        stand_in = self._stand_in_reason(hook_input)
        if stand_in:
            reason = f"{reason}\n\nALSO REQUIRED BEFORE STOPPING AGAIN:\n\n{stand_in}"
        return BlockingResult.deny(reason).under_rule(_RULE)

    def _render(self, stale: list[_Stale], unconfirmed: list[_Unconfirmed], window: float) -> str:
        minutes = int(window // _SECONDS_PER_MINUTE)
        parts = [
            "You are stopping to wait on a human, as a team coordinator. The team chat is the "
            "only human surface: the owner must be told there, by a post that NOTIFIES."
        ]
        for item in stale:
            shown = [pid for pid in (printable_thread_id(t) for t in item.thread_ids) if pid]
            hidden = len(item.thread_ids) - len(shown)
            names = ", ".join(shown) + (f" (+{hidden} more)" if hidden else "")
            parts.append(
                f"Team {item.team}: no notifying post from this seat in the last {minutes} "
                f"minutes on {names}. Run ONE command: "
                f"`{self._bus.bump_command(item.team, item.thread_ids)}`. A post counts only if "
                "it notifies; a post whose notify flag or thread relation cannot be read does "
                "not count."
            )
        for gap in unconfirmed:
            question, owner_message = self._bus.notify_commands(gap.team)
            bus_note = (
                ""
                if gap.reason in _NOT_BUS_REASONS
                else "The bus history exposes no notify flag or m.thread relation this guard "
                "can read (unverified here). "
            )
            parts.append(
                f"Team {gap.team}: the guard could not machine-confirm that the owner was told "
                f"({gap.reason}). {bus_note}So the wait is unconfirmed and the stop "
                "fails closed. Post a notifying reply in each owner-started thread "
                f"(`{owner_message}`) and on each open question this seat asked "
                f"(`{question}`), naming what is awaited."
            )
        parts.append(
            "Then stop again. Do not restate the waits in the stop message; point at the threads."
        )
        return "\n\n".join(parts)

    def _render_unchecked(self, gap: _Unconfirmed) -> str:
        """The ``auto`` advisory for a team whose bus this adapter cannot read (no thread ids)."""
        question, owner_message = self._bus.notify_commands(gap.team)
        return (
            f"owner_wait_stop_guard ADVISORY -- team {gap.team}: this stop waits on a human, "
            f"and the guard could not check ({gap.reason}) whether the owner was told. "
            "Unchecked: every owner-started thread and every open question this seat asked "
            "(this bus adapter cannot list their ids or read the notify flag). Make sure each "
            f"has a notifying reply from this seat (`{owner_message}`, `{question}`), "
            "naming what is awaited."
        )

    def get_rules(self) -> list[Rule]:
        """The single rule behind this handler's deny."""
        return [_RULE]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## owner_wait_stop_guard — a coordinator's wait must reach the owner on the bus\n\n"
            "On a teamchat COORDINATOR seat (Plan 00631 probe), a main-thread stop that waits on "
            "a human (`STOPPING BECAUSE: waiting on ...`, `[awaiting-human]`, or the "
            "awaiting-human mode) is denied unless every open question the seat asked or owns, "
            "and every owner-started thread, has a NOTIFYING post from this seat with a real "
            "body within `options.window_minutes` (default 30). A post whose notify flag or "
            "thread relation cannot be read does not count. The deny prints ONE bump command; "
            "run it, then stop again.\n\n"
            "**Unreadable bus**: `options.on_unreadable_bus` is `auto` by default. Where the bus "
            "adapter can read notify flags, a wait the guard cannot confirm is refused once; on "
            "pingbus v1 (no notify flag) it is allowed with an ADVISORY naming the team and the "
            "thread classes it could not check. Either way: post a notifying reply in each "
            "thread (`pingbus thread --team <t> Q<n> --ask`, or `--re <event id> --ask` for an "
            "owner-started message). `refuse` always refuses it once; `allow` lets it through "
            "with a log line only.\n\n"
            "An unreadable role or an unresolved seat probe stays armed and is treated like an "
            "unreadable bus.\n\n"
            "**Stands aside** for a declared worker, no team, a sub-agent, a usage pause "
            "and the re-stop after its own deny (a re-stop after another handler's deny is "
            "checked again). The stop text should point at thread "
            "ids, never restate the waits."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One undrivable deny case and one near-miss allow case."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="owner wait stop guard - a coordinator's unbumped wait is refused",
                command="echo 'coordinator stop waiting on the owner'",
                description=(
                    "On a teamchat coordinator seat, a main-thread stop waiting on the owner "
                    "while an open question has no recent notifying post (or the bus cannot "
                    "confirm one, under on_unreadable_bus: refuse, or auto with a flag-reading "
                    "adapter) is denied and "
                    "names the notifying command."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"notif"],
                safety_notes="Blocks once per stop chain; the re-stop after its own deny is allowed.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="Stop",
                requires_main_thread=True,
                harness_cannot_produce=(
                    "The deny needs a teamchat session whose whoami declares a coordinator "
                    "seat; a probe cannot stand up a team. Verified by unit tests."
                ),
            ),
            AcceptanceTest(
                title="owner wait stop guard - a stop outside any team",
                command="echo 'ordinary stop'",
                description="Near-miss: with no teamchat runtime on the payload the guard stands aside.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Negative case: no team is no behaviour change.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="Stop",
                requires_main_thread=False,
                hook_input={"hook_event_name": "Stop", "stop_hook_active": False},
            ),
        ]
