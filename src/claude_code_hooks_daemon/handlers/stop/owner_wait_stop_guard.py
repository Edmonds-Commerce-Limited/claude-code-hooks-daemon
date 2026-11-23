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
teamchat runtime, whose text (after ``STOPPING BECAUSE:``, outside fences and
quotes) waits on a human or whose session is in the awaiting-human mode, and
per held team only where the 00631 probe declares this seat ``coordinator``
(:func:`role_gate` verdict APPLIES). A worker, an unknown role, an unresolved
probe or no team leaves the stop untouched and reads nothing.

**An unreadable bus** (the adapter reports it, or raises) is governed by
``options.on_unreadable_bus``: ``refuse`` (default) fails CLOSED, because an
unconfirmable wait is exactly the silent wait this guard exists to stop; the
refusal tells the coordinator to post a notifying reply in each thread and stop
again, and says why nothing could be confirmed. ``allow`` fails open with a
WARNING log. Either way the WARNING is written.

**Never a trap.** A stop that re-enters after the deny (``stop_hook_active``)
is allowed: one refusal per stop chain, the convention of every one-shot Stop
block. It also stands aside while the session is usage-paused.

**Ordering.** Priority 3, ahead of ``idle_workable_issue_stop_gate`` (4) and the
terminal ``auto_continue_stop`` (15 by default, 10 in this project's config);
non-terminal, so those still run. Because
it runs before ``auto_continue_stop`` enters the awaiting-human mode, it reads
the current message for the declaration as well as the mode.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import TeamSeatConfig
from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import StopHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
    _declares_human_blocked,
    _declaring_lines,
)
from claude_code_hooks_daemon.utils.autonomy import session_policy
from claude_code_hooks_daemon.utils.config_cache import default_config, load_config_cached
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.owner_wait_bus import (
    BusUnreadable,
    OwnerWaitBus,
    TeamchatOwnerWaitBus,
)
from claude_code_hooks_daemon.utils.owner_wait_check import (
    BusSnapshot,
    printable_thread_id,
    stale_threads,
)
from claude_code_hooks_daemon.utils.stop_hook_helpers import (
    get_transcript_reader,
    is_stop_hook_active,
)
from claude_code_hooks_daemon.utils.team_role_gate import GateVerdict, role_gate
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ROLE_COORDINATOR,
    SeatContext,
    SeatContextResolver,
    SessionSignals,
)
from claude_code_hooks_daemon.utils.usage_pause_gate import hook_is_usage_paused

logger = logging.getLogger(__name__)

#: How recent a notifying post must be. Provisional until Plan 00636 Task 1.1 settles N.
DEFAULT_WINDOW_MINUTES: Final[int] = 30
MAX_WINDOW_MINUTES: Final[int] = 24 * 60
ON_UNREADABLE_REFUSE: Final[str] = "refuse"
ON_UNREADABLE_ALLOW: Final[str] = "allow"
DEFAULT_ON_UNREADABLE_BUS: Final[str] = ON_UNREADABLE_REFUSE
_ON_UNREADABLE_VALUES: Final[frozenset[str]] = frozenset(
    {ON_UNREADABLE_REFUSE, ON_UNREADABLE_ALLOW}
)
_SECONDS_PER_MINUTE: Final[int] = 60
_STOP_PREFIX: Final[str] = "STOPPING BECAUSE:"
#: A waiting declaration on the same line as the prefix: "waiting on/for ... the owner",
#: "awaiting the owner's decision". ``[awaiting-human]`` is matched by auto_continue_stop's own test.
_WAITING_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:waiting\s+(?:on|for)|awaiting)\b[^\n]*?"
    r"\b(?:owner|human|user|answers?|repl(?:y|ies)|decision|input)",
    re.IGNORECASE,
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
        "unreadable bus is refused by default (options.on_unreadable_bus: refuse; 'allow'\n"
        "fails open with a log line). The deny names thread ids only, never the waits.\n"
        "One deny per stop chain: a re-entered stop is allowed."
    ),
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
            "owner_wait_stop_guard: options.on_unreadable_bus=%r is not 'refuse' or 'allow'; "
            "using the fail-closed default %r",
            value,
            DEFAULT_ON_UNREADABLE_BUS,
        )
        return DEFAULT_ON_UNREADABLE_BUS

    # -- seams -------------------------------------------------------------------

    def _team_seat_config(self) -> TeamSeatConfig:
        root = getattr(self, "_workspace_root", None)
        project_root = Path(root) if root is not None else ProjectContext.project_root()
        config_path = project_root / ".claude" / "hooks-daemon.yaml"
        try:
            return load_config_cached(config_path).team_seat
        except (ValidationError, OSError, ValueError, RuntimeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason=f"an unloadable config {config_path} falls back to the default team_seat block, which still probes a session carrying a teamchat runtime",
            )
            return default_config().team_seat

    def _resolve_seats(self, signals: SessionSignals) -> SeatContext:
        """The 00631 seat context for this session (TTL-cached by the resolver)."""
        if self._resolver is None:
            self._resolver = SeatContextResolver.from_config(self._team_seat_config())
        return self._resolver.resolve(signals)

    # -- matching ----------------------------------------------------------------

    @staticmethod
    def _text_declares_waiting(text: str) -> bool:
        declaring = _declaring_lines(text)
        if _declares_human_blocked(declaring):
            return True
        for line in declaring.splitlines():
            _, prefix, reason = line.partition(_STOP_PREFIX)
            if prefix and _WAITING_RE.search(reason):
                return True
        return False

    def _waits_on_a_human(self, hook_input: dict[str, Any]) -> bool:
        try:
            if session_policy(hook_input).is_blocked:
                return True
        except (RuntimeError, OSError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="the session-modes registry is unreadable, so only the stop text can show a wait on a human",
            )
        reader = get_transcript_reader(hook_input)
        text = reader.get_last_assistant_text() if reader is not None else ""
        return bool(text) and self._text_declares_waiting(text)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A waiting, non-re-entered, unpaused stop in a session that carries a team runtime."""
        if is_stop_hook_active(hook_input) or hook_is_usage_paused(hook_input):
            return False
        if not SessionSignals.from_hook_input(hook_input).runtime:
            return False
        return self._waits_on_a_human(hook_input)

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

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Deny while a coordinator team has stale threads, or (refuse) an unreadable bus."""
        signals = SessionSignals.from_hook_input(hook_input)
        context = self._resolve_seats(signals)
        policy = self._unreadable_policy()
        window = self._window_seconds()
        stale: list[_Stale] = []
        unconfirmed: list[_Unconfirmed] = []
        for team in context.teams_held():
            gate = role_gate(hook_input, context, team=team, role=ROLE_COORDINATOR)
            if gate.verdict is not GateVerdict.APPLIES:
                continue
            snapshot = self._read(gate.team, signals)
            if isinstance(snapshot, BusUnreadable):
                logger.warning(
                    "owner_wait_stop_guard: team %s bus unreadable (%s); on_unreadable_bus=%s, "
                    "so the waiting stop is %s",
                    gate.team,
                    snapshot.reason,
                    policy,
                    "refused" if policy == ON_UNREADABLE_REFUSE else "allowed unverified",
                )
                if policy == ON_UNREADABLE_REFUSE:
                    unconfirmed.append(_Unconfirmed(gate.team, snapshot.reason))
                continue
            ids = stale_threads(snapshot, now=self._clock(), window_seconds=window)
            if ids:
                stale.append(_Stale(gate.team, ids))
        if not stale and not unconfirmed:
            return BlockingResult(decision=Decision.ALLOW)
        return BlockingResult.deny(self._render(stale, unconfirmed, window)).under_rule(_RULE)

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
            parts.append(
                f"Team {gap.team}: the guard could not machine-confirm that the owner was told "
                f"({gap.reason}). The bus history exposes no notify flag or m.thread relation "
                "this guard can read (unverified here), so the wait is unconfirmed and the stop "
                "fails closed. Post a notifying reply in each owner-started thread "
                f"(`{owner_message}`) and on each open question this seat asked "
                f"(`{question}`), naming what is awaited."
            )
        parts.append(
            "Then stop again. Do not restate the waits in the stop message; point at the threads."
        )
        return "\n\n".join(parts)

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
            "**Unreadable bus**: `options.on_unreadable_bus` is `refuse` by default, so a wait "
            "the guard cannot confirm is refused once: post a notifying reply in each thread "
            "(`pingbus thread --team <t> Q<n> --ask`, or `--re <event id> --ask` for an "
            "owner-started message), then stop again. `allow` lets it through with a log line. "
            "Until the bus history exposes the notify flag, every waiting coordinator stop "
            "is refused once.\n\n"
            "**Stands aside** for a worker or unknown role, no team, a sub-agent, a usage pause "
            "and a stop that re-enters after the deny. The stop text should point at thread "
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
                    "confirm one, under the default on_unreadable_bus: refuse) is denied and "
                    "names the notifying command."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"notif"],
                safety_notes="Blocks once per stop chain; a re-entered stop is allowed.",
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
