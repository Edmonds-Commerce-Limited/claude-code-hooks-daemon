"""Session modes: the pure model (Plan 00501).

A session mode is a named, per-session condition that turns off some of the
daemon's work-DRIVING machinery: ``focus`` (the human pointed the session at one
task), ``blocked`` (the agent declared it is waiting on the human, or the
goal-loop detector found a ``/goal`` loop), ``usage-paused`` (read from its own
record, never stored here) and the daemon-wide ``unattended`` mode (shown, never
suppressing). Guards are never part of any mode.

Modes compose. :class:`SessionPolicy` is the union of the active entries'
suppressions, with one precedence rule for the only conflict: a mode that HALTS
work (usage-paused, blocked) beats the one that DRIVES it (the unattended
stop-block). The status line shows the top label by
:meth:`ModeLabel.by_precedence` plus a ``+N`` count.

This module does no I/O. The registry that stores entries and writes them
through to the per-session file is ``core.session_mode_registry``.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from claude_code_hooks_daemon.skill_scan.constants import EXCLUDE_CONTENT_MARKERS
from claude_code_hooks_daemon.skill_scan.extraction import is_genuine_text
from claude_code_hooks_daemon.utils.cron_tick import DaemonTick, TickKind

_SECONDS_PER_HOUR: Final[int] = 3600

#: Focus lasts this long after it is set or last renewed by a genuine human
#: prompt (ruling 02).
FOCUS_TTL_SECONDS: Final[int] = 12 * _SECONDS_PER_HOUR

#: A declared BLOCKED entry (awaiting-human) ends this long after it is
#: entered, so a forgotten declaration costs at most a day of ticks.
DECLARED_BLOCKED_TTL_SECONDS: Final[int] = 24 * _SECONDS_PER_HOUR


class SessionMode(StrEnum):
    """The closed set of session modes."""

    FOCUS = "focus"
    BLOCKED = "blocked"
    USAGE_PAUSED = "usage-paused"
    UNATTENDED = "unattended"

    @property
    def registry_owned(self) -> bool:
        """Whether the session-modes registry stores this mode.

        ``usage-paused`` keeps its own record and ``unattended`` is daemon-wide
        state; both are shown, neither is migrated (plan Non-Goals).
        """
        return self in _REGISTRY_OWNED


_REGISTRY_OWNED: Final[frozenset[SessionMode]] = frozenset({SessionMode.FOCUS, SessionMode.BLOCKED})


class BlockReason(StrEnum):
    """Why a session is BLOCKED (ruling 03: one family, two reasons)."""

    DECLARED = "declared"
    GOAL_LOOP = "goal-loop"


class ModeSource(StrEnum):
    """Who entered the mode."""

    HUMAN = "human"
    AGENT = "agent"
    DETECTOR = "detector"
    DAEMON = "daemon"


class Lifetime(StrEnum):
    """What survives a daemon restart.

    ``daemon`` entries are dropped when the registry loads (each leaves a
    "cleared by restart" notice); ``session`` entries survive a restart and end
    with their expiry, since a new session has a new id.
    """

    DAEMON = "daemon"
    SESSION = "session"


class ModeLabel(StrEnum):
    """What the status line shows for an entry, declared in precedence order."""

    USAGE_PAUSED = "usage-paused"
    GOAL_BLOCKED = "goal-blocked"
    AWAITING_HUMAN = "awaiting-human"
    # Plan 00501 Task 8.2 logs goal-clear attributions under it; Task 8.3 builds the mode.
    MANUAL_GOALS = "manual-goals"
    FOCUS = "focus"
    UNATTENDED = "unattended"

    @classmethod
    def by_precedence(cls) -> Iterator[ModeLabel]:
        """Every label, the one that wins the badge first."""
        return iter(cls)

    @property
    def rank(self) -> int:
        """Position in the precedence order; 0 wins."""
        return list(ModeLabel).index(self)


#: The labels whose mode halts the work-driving machinery.
_WORK_HALTING: Final[frozenset[ModeLabel]] = frozenset(
    {ModeLabel.USAGE_PAUSED, ModeLabel.GOAL_BLOCKED, ModeLabel.AWAITING_HUMAN, ModeLabel.FOCUS}
)

#: How each work-halting mode ends, as the explanation tells the session.
_EXIT_HINTS: Final[dict[ModeLabel, str]] = {
    ModeLabel.USAGE_PAUSED: "usage-paused lifts by itself when the usage window resets",
    ModeLabel.GOAL_BLOCKED: "the next message the human types clears it",
    ModeLabel.AWAITING_HUMAN: "the next message the human types clears it",
    ModeLabel.FOCUS: "type `hooks-daemon focus off` to end focus",
}

#: The BLOCKED family's labels: a session holding either is blocked.
BLOCKED_LABELS: Final[frozenset[ModeLabel]] = frozenset(
    {ModeLabel.AWAITING_HUMAN, ModeLabel.GOAL_BLOCKED}
)

#: The labels that halt work outright, beating the unattended stop-block.
_HALTS_STOP_BLOCK: Final[frozenset[ModeLabel]] = frozenset(
    {ModeLabel.USAGE_PAUSED, ModeLabel.GOAL_BLOCKED, ModeLabel.AWAITING_HUMAN}
)


@dataclass(frozen=True, slots=True)
class SessionModeEntry:
    """One active mode of one session.

    Attributes:
        mode: Which mode.
        session_id: The session it applies to.
        entered_at: Epoch seconds it was entered.
        expires_at: Epoch seconds it stops applying; every mode is bounded.
        source: Who entered it.
        detail: The focus task (required for focus), else free text for logs.
        reason: Required for ``blocked``, refused for every other mode.
        lifetime: Whether it survives a daemon restart.
    """

    mode: SessionMode
    session_id: str
    entered_at: float
    expires_at: float
    source: ModeSource
    detail: str = ""
    reason: BlockReason | None = None
    lifetime: Lifetime = Lifetime.SESSION

    def __post_init__(self) -> None:
        """Refuse an entry no reader could act on. Raises ``ValueError``."""
        if not self.session_id.strip():
            raise ValueError("a session mode needs a session id")
        if self.expires_at <= self.entered_at:
            raise ValueError(
                f"expires_at ({self.expires_at}) must be after entered_at ({self.entered_at})"
            )
        if self.mode is SessionMode.BLOCKED and self.reason is None:
            raise ValueError("a blocked mode needs a reason (declared or goal-loop)")
        if self.mode is not SessionMode.BLOCKED and self.reason is not None:
            raise ValueError(f"only a blocked mode takes a reason, not {self.mode}")
        if self.mode is SessionMode.FOCUS and not self.detail.strip():
            raise ValueError("a focus mode needs its task")

    @property
    def label(self) -> ModeLabel:
        """The status-line label (a blocked entry shows its reason)."""
        if self.mode is SessionMode.BLOCKED:
            if self.reason is BlockReason.GOAL_LOOP:
                return ModeLabel.GOAL_BLOCKED
            return ModeLabel.AWAITING_HUMAN
        return ModeLabel(self.mode.value)

    @property
    def renewal_ttl(self) -> int | None:
        """How far a genuine human prompt pushes the expiry, or None if it does not."""
        return FOCUS_TTL_SECONDS if self.mode is SessionMode.FOCUS else None

    def is_live(self, now: float) -> bool:
        """Whether the entry still applies at ``now``."""
        return now < self.expires_at

    def renewed(self, now: float) -> SessionModeEntry:
        """This entry with its expiry moved to ``now`` plus its renewal TTL.

        Raises:
            ValueError: the mode is not renewed by a prompt.
        """
        ttl = self.renewal_ttl
        if ttl is None:
            raise ValueError(f"a {self.label} mode is not renewed by a prompt")
        return replace(self, expires_at=now + ttl)


def declared_blocked_entry(session_id: str, *, entered_at: float) -> SessionModeEntry:
    """The awaiting-human entry an agent's own stop declares, expiring a day later.

    The stop writer and the legacy-marker import both build the entry here, so
    the two can never disagree on its source, lifetime or expiry.

    Raises:
        ValueError: ``session_id`` is blank.
    """
    return SessionModeEntry(
        mode=SessionMode.BLOCKED,
        session_id=session_id,
        entered_at=entered_at,
        expires_at=entered_at + DECLARED_BLOCKED_TTL_SECONDS,
        source=ModeSource.AGENT,
        reason=BlockReason.DECLARED,
        lifetime=Lifetime.SESSION,
    )


def goal_loop_blocked_entry(
    session_id: str, *, entered_at: float, ttl_seconds: float
) -> SessionModeEntry:
    """The goal-blocked entry the goal-loop detector enters in act mode.

    Raises:
        ValueError: ``session_id`` is blank or ``ttl_seconds`` is not positive.
    """
    return SessionModeEntry(
        mode=SessionMode.BLOCKED,
        session_id=session_id,
        entered_at=entered_at,
        expires_at=entered_at + ttl_seconds,
        source=ModeSource.DETECTOR,
        reason=BlockReason.GOAL_LOOP,
        lifetime=Lifetime.SESSION,
    )


def _clock_text(epoch: float) -> str:
    """``HH:MM UTC`` for an epoch time."""
    return time.strftime("%H:%M UTC", time.gmtime(epoch))


def describe_entry(entry: SessionModeEntry) -> str:
    """A short phrase naming the entry, for explanations and notices."""
    if entry.mode is SessionMode.FOCUS:
        return f"focus mode on '{entry.detail}'"
    return f"{entry.label} since {_clock_text(entry.entered_at)}"


class TickAction(StrEnum):
    """What the active modes do to a daemon cron tick, least suppressive first.

    ``deliver`` means no mode intervenes: the suppressor's own cadence rules
    still apply. ``thin`` is the backoff a blocked session with live ledgered
    work gets (the suppressor's row 2).
    """

    DELIVER = "deliver"
    DELIVER_NAMING_FOCUS = "deliver-naming-focus"
    THIN = "thin"
    DROP = "drop"

    @property
    def rank(self) -> int:
        """Suppression strength; the highest rank among the modes wins."""
        return list(TickAction).index(self)


def _tick_action_for(
    label: ModeLabel, tick: DaemonTick, *, runs_while_blocked: bool, work_owed: bool | None
) -> TickAction:
    """What one mode does to one tick (the truth table, one row per label)."""
    if label is ModeLabel.USAGE_PAUSED:
        return TickAction.DELIVER if tick.kind is TickKind.USAGE_RESUME else TickAction.DROP
    if label in (ModeLabel.AWAITING_HUMAN, ModeLabel.GOAL_BLOCKED):
        if tick.kind is TickKind.DECLARED:
            return TickAction.DELIVER if runs_while_blocked else TickAction.DROP
        if tick.kind is TickKind.FAILSAFE:
            return TickAction.THIN if work_owed is True else TickAction.DROP
        return TickAction.DELIVER
    if label is ModeLabel.FOCUS:
        if tick.kind is TickKind.DECLARED:
            return TickAction.DROP
        if tick.kind is TickKind.FAILSAFE:
            return TickAction.DELIVER_NAMING_FOCUS
        return TickAction.DELIVER
    return TickAction.DELIVER


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    """The composed effect of one session's active modes.

    Build it with :meth:`from_entries`; ``entries`` are held in precedence order.
    """

    entries: tuple[SessionModeEntry, ...]

    @classmethod
    def from_entries(cls, entries: Iterable[SessionModeEntry]) -> SessionPolicy:
        """Compose ``entries`` of one session.

        Raises:
            ValueError: the entries name two sessions, or one label twice.
        """
        held = tuple(entries)
        if len({entry.session_id for entry in held}) > 1:
            raise ValueError("a policy composes the modes of one session only")
        labels = [entry.label for entry in held]
        if len(set(labels)) != len(labels):
            raise ValueError("each mode label may be active once per session")
        return cls(entries=tuple(sorted(held, key=lambda entry: entry.label.rank)))

    @property
    def labels(self) -> tuple[ModeLabel, ...]:
        """The active labels, the badge's first."""
        return tuple(entry.label for entry in self.entries)

    @property
    def drives_work(self) -> bool:
        """Whether the work-driving machinery may run for this session."""
        return not any(label in _WORK_HALTING for label in self.labels)

    @property
    def unattended_block_applies(self) -> bool:
        """Whether the daemon ``unattended`` stop-block may still apply (halting beats driving)."""
        return not any(label in _HALTS_STOP_BLOCK for label in self.labels)

    @property
    def is_blocked(self) -> bool:
        """Whether a BLOCKED-family mode (awaiting-human or goal-blocked) is active."""
        return any(label in BLOCKED_LABELS for label in self.labels)

    @property
    def focus_task(self) -> str | None:
        """The focus task, when focus is on."""
        for entry in self.entries:
            if entry.mode is SessionMode.FOCUS:
                return entry.detail
        return None

    def badge(self) -> str:
        """The status-line text: the top label plus ``+N``; empty with no mode."""
        if not self.entries:
            return ""
        top = str(self.labels[0])
        extra = len(self.labels) - 1
        return f"{top} +{extra}" if extra else top

    def explain_clause(self) -> str:
        """The work-halting modes as one phrase, empty when none halts work."""
        return "; ".join(
            describe_entry(entry) for entry in self.entries if entry.label in _WORK_HALTING
        )

    def exit_clause(self) -> str:
        """How the work-halting modes end, each way stated once; empty when none halts work."""
        hints = (_EXIT_HINTS[entry.label] for entry in self.entries if entry.label in _EXIT_HINTS)
        return "; ".join(dict.fromkeys(hints))

    def tick_action(
        self, tick: DaemonTick, *, runs_while_blocked: bool, work_owed: bool | None
    ) -> TickAction:
        """What the active modes do to ``tick``: the most suppressive action wins.

        Args:
            tick: The recognised daemon tick.
            runs_while_blocked: A declared job's ``runs_while_awaiting_human``.
            work_owed: Whether the goal ledger holds live work (None: unknown).
        """
        actions = [
            _tick_action_for(
                label, tick, runs_while_blocked=runs_while_blocked, work_owed=work_owed
            )
            for label in self.labels
        ]
        return max(actions, key=lambda action: action.rank, default=TickAction.DELIVER)


#: How long a shown-only ``unattended`` entry claims to last. It is built for one
#: render and never stored, so it needs a valid interval and nothing more.
_SHOWN_ONLY_SECONDS: Final[float] = 1.0


@dataclass(frozen=True, slots=True)
class UsagePauseView:
    """The part of a live usage-pause record the session-mode display needs."""

    paused_at: float
    until: float
    reason: str


def displayed_policy(
    session_id: str,
    registry_entries: Iterable[SessionModeEntry],
    *,
    usage_pause: UsagePauseView | None,
    unattended: bool,
    now: float,
) -> SessionPolicy:
    """Every mode a session shows: the registry's, plus usage-paused and unattended.

    ``usage-paused`` keeps its own record and ``unattended`` is daemon-wide
    state; neither is stored in the registry (plan Non-Goals), so both are
    composed here for display. ``unattended`` never halts work.

    Raises:
        ValueError: the entries are not all ``session_id``'s, or a label repeats.
    """
    entries = list(registry_entries)
    if usage_pause is not None:
        entries.append(
            SessionModeEntry(
                mode=SessionMode.USAGE_PAUSED,
                session_id=session_id,
                entered_at=usage_pause.paused_at,
                expires_at=usage_pause.until,
                source=ModeSource.DAEMON,
                detail=usage_pause.reason,
            )
        )
    if unattended:
        entries.append(
            SessionModeEntry(
                mode=SessionMode.UNATTENDED,
                session_id=session_id,
                entered_at=now,
                expires_at=now + _SHOWN_ONLY_SECONDS,
                source=ModeSource.DAEMON,
                lifetime=Lifetime.DAEMON,
            )
        )
    return SessionPolicy.from_entries(entries)


def is_genuine_human_prompt(prompt: object) -> bool:
    """Whether a UserPromptSubmit prompt was typed by a human.

    Classified from the prompt text alone (no transcript read): non-empty and
    carrying no machine-traffic marker (tick sentinels, the ccy supervisor's
    prefix, task notifications, ...).
    """
    return isinstance(prompt, str) and is_genuine_text(prompt, EXCLUDE_CONTENT_MARKERS)
