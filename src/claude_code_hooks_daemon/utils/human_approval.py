"""HUMAN-approval check before a destructive act (Plan 00634; umbrella 00630 DESIGN.md s16).

A destructive act (push, delete, permission change, merge to main) by a team
coordinator needs a cited questions-room line: the team T and the line's event
id. The daemon asks ``$TEAMCHAT_KIT/bin/teamchat verify`` about that one line,
with the session's ``TEAMCHAT_RUNTIME``, and passes only if the line sits in
T's questions room, its sender is a declared human of T, and this seat is the
coordinator in T. Every other outcome is a refusal with a reason, never a pass.

Invariants (DESIGN.md s16):

1. A pass never relaxes another guard; it only lifts THIS check.
2. A peer's line, or a role, is never a human's approval.
3. An answer that cannot be read is a refusal.
4. The line's text is never kept, logged or echoed.
5. Nothing under teamchat's seat store or run directory is opened; the only
   route to teamchat is its CLI.

The ``verify`` answer shape (fedora-desktop issue 369) is UNVERIFIED HERE, so
:data:`DEFAULT_VERIFIER` refuses every cite until the contract is confirmed.
:class:`TeamchatVerifyCli` is the provisional client for that contract.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.handler_scope import acts_as_main_thread
from claude_code_hooks_daemon.utils.team_role_gate import GateVerdict, role_gate
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ROLE_COORDINATOR,
    CommandRunner,
    CommandStatus,
    ProbeReason,
    RoleKind,
    SeatContext,
    SeatState,
    SessionSignals,
    decode_json_document,
    default_command_runner,
    normalise_name,
    run_kit_command,
)

#: The room a human's approval must be posted in.
QUESTIONS_ROOM: Final[str] = "questions"
#: The only ``verify`` answer version this module reads.
VERIFY_ANSWER_VERSION: Final[int] = 1
#: How long a verified approval is reused for the same cite and act class.
DEFAULT_RECORD_TTL_SECONDS: Final[float] = 300.0

#: A teamchat event id. The leading ``$`` means it can never be read as an option.
#: No ``/``, ``.`` or ``~``, so an id can never be read as a path. Provisional:
#: the real alphabet awaits the verify contract (fedora-desktop issue 369), and
#: over-rejecting only refuses a cite.
_EVENT_ID: Final[re.Pattern[str]] = re.compile(r"\$[A-Za-z0-9_+=-]{1,255}")
#: The attached question tag (``Q7``). Anything else is dropped, never kept.
_QUESTION_TAG: Final[re.Pattern[str]] = re.compile(r"Q[0-9]{1,9}")


class ActClass(StrEnum):
    PUSH = "push"
    DELETE = "delete"
    PERMISSION = "permission"
    MERGE_MAIN = "merge_main"


class Refusal(StrEnum):
    NO_TEAM_SEAT = "no_team_seat"
    SUBAGENT = "subagent"
    NO_ACTS = "no_acts"
    NO_CITE = "no_cite"
    ROLE_UNKNOWN = "role_unknown"
    NOT_COORDINATOR = "not_coordinator"
    CONTRACT_UNCONFIRMED = "contract_unconfirmed"
    VERIFY_UNAVAILABLE = "verify_unavailable"
    VERIFY_REFUSED = "verify_refused"
    ANSWER_UNREADABLE = "answer_unreadable"
    ANSWER_MISMATCH = "answer_mismatch"
    NOT_QUESTIONS_ROOM = "not_questions_room"
    NOT_HUMAN = "not_human"


#: One fixed text per refusal. Never built from answer content (invariant 4).
_REASONS: Final[Mapping[Refusal, str]] = {
    Refusal.NO_TEAM_SEAT: "this session holds no team seat",
    Refusal.SUBAGENT: "a sub-agent cannot carry a human's approval; the coordinator acts",
    Refusal.NO_ACTS: "no destructive act was named, so there is nothing to approve",
    Refusal.NO_CITE: "no well-formed cite (team and a $-prefixed questions-room event id)",
    Refusal.ROLE_UNKNOWN: "this seat's role in the cited team cannot be read",
    Refusal.NOT_COORDINATOR: "this seat is not the coordinator in the cited team",
    Refusal.CONTRACT_UNCONFIRMED: (
        "the teamchat verify answer for a questions-room line is unverified here "
        "(fedora-desktop issue 369), so no cite can be confirmed yet"
    ),
    Refusal.VERIFY_UNAVAILABLE: "teamchat verify could not be run (missing, untrusted or timed out)",
    Refusal.VERIFY_REFUSED: "teamchat verify refused the cited line",
    Refusal.ANSWER_UNREADABLE: "the teamchat verify answer could not be read",
    Refusal.ANSWER_MISMATCH: "the teamchat verify answer names another team or line",
    Refusal.NOT_QUESTIONS_ROOM: "the cited line is not in the team's questions room",
    Refusal.NOT_HUMAN: "the cited line was not sent by a declared human of the team",
}


@dataclass(frozen=True)
class ApprovalCite:
    """A cited questions-room line: the team and the line's event id."""

    team: str
    event_id: str


@dataclass(frozen=True)
class VerifiedLine:
    """What ``verify`` said about one line. The line's text is deliberately absent."""

    team: str
    event_id: str
    room: str
    declared_human: bool
    question: str


@dataclass(frozen=True)
class VerifyFailure:
    refusal: Refusal

    @property
    def reason(self) -> str:
        return _REASONS[self.refusal]


#: ``(signals, cite) -> answer``. Must never raise.
Verifier = Callable[[SessionSignals, ApprovalCite], "VerifiedLine | VerifyFailure"]


@dataclass(frozen=True)
class GoGrant:
    """A verified readiness GO (Plan 00632): the classes it authorised, until ``window_end``."""

    team: str
    classes: frozenset[ActClass]
    window_end: float


@dataclass(frozen=True)
class ApprovalVerdict:
    passed: bool
    refusal: Refusal | None
    reason: str


def _refused(refusal: Refusal) -> ApprovalVerdict:
    return ApprovalVerdict(False, refusal, _REASONS[refusal])


# --- the cite ----------------------------------------------------------------------


def parse_cite(team: object, event_id: object) -> ApprovalCite | None:
    """A well-formed cite with the team in :func:`normalise_name` form, or None."""
    if not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id):
        return None
    name = normalise_name(team)
    if not name:
        return None
    return ApprovalCite(name, event_id)


# --- the verify answer (provisional contract) ----------------------------------------


def _question_tag(value: object) -> str:
    if isinstance(value, str) and _QUESTION_TAG.fullmatch(value):
        return value
    return ""


def parse_verify_answer(text: str, cite: ApprovalCite) -> VerifiedLine | VerifyFailure:
    """Read one ``verify --json`` answer about ``cite``. Never raises.

    The provisional shape is ``{"v": 1, "id", "team", "room", "kind", "q", ...}``.
    Anything else is a failure; an answer about another team or line is a mismatch.
    """
    document: object = decode_json_document(text)
    if not isinstance(document, dict):
        return VerifyFailure(Refusal.ANSWER_UNREADABLE)
    version: Any = document.get("v")
    # bool is an int subclass: ``True == 1``, so the type is checked exactly.
    if type(version) is not int or version != VERIFY_ANSWER_VERSION:
        return VerifyFailure(Refusal.ANSWER_UNREADABLE)
    fields = [document.get(key) for key in ("id", "team", "room", "kind")]
    if not all(isinstance(field, str) for field in fields):
        return VerifyFailure(Refusal.ANSWER_UNREADABLE)
    event_id, team, room, kind = (str(field) for field in fields)
    answered_team = normalise_name(team)
    if event_id != cite.event_id or not answered_team or answered_team != normalise_name(cite.team):
        return VerifyFailure(Refusal.ANSWER_MISMATCH)
    return VerifiedLine(
        team=answered_team,
        event_id=event_id,
        room=normalise_name(room),
        declared_human=kind == "human",
        question=_question_tag(document.get("q")),
    )


def contract_unconfirmed_verifier(
    _signals: SessionSignals, _cite: ApprovalCite
) -> VerifiedLine | VerifyFailure:
    """The production default: refuses every cite and runs nothing (it takes the
    :data:`Verifier` arguments positionally and reads neither).

    The questions-room ``verify`` contract is unverified here, so no cite can
    be confirmed; failing closed is the only safe answer until it is.
    """
    return VerifyFailure(Refusal.CONTRACT_UNCONFIRMED)


DEFAULT_VERIFIER: Final[Verifier] = contract_unconfirmed_verifier


class TeamchatVerifyCli:
    """The provisional ``teamchat verify --json --team <T> <id>`` client.

    The ``--json`` flag and the answer shape are UNVERIFIED HERE (issue 369).
    """

    def __init__(
        self,
        *,
        runner: CommandRunner = default_command_runner,
        timeout: float = float(Timeout.TEAMCHAT_VERIFY),
    ) -> None:
        self._runner = runner
        self._timeout = timeout

    def __call__(self, signals: SessionSignals, cite: ApprovalCite) -> VerifiedLine | VerifyFailure:
        # Re-checked here: a cite built without parse_cite must still never reach argv.
        checked = parse_cite(cite.team, cite.event_id)
        if checked is None:
            return VerifyFailure(Refusal.NO_CITE)
        outcome = run_kit_command(
            signals,
            ("verify", "--json", "--team", checked.team, checked.event_id),
            runner=self._runner,
            timeout=self._timeout,
        )
        if isinstance(outcome, ProbeReason):
            return VerifyFailure(Refusal.VERIFY_UNAVAILABLE)
        if outcome.status is CommandStatus.OK:
            return parse_verify_answer(outcome.stdout, checked)
        if outcome.status is CommandStatus.TOO_LARGE:
            return VerifyFailure(Refusal.ANSWER_UNREADABLE)
        if outcome.status is CommandStatus.EXITED:
            return VerifyFailure(Refusal.VERIFY_REFUSED)
        return VerifyFailure(Refusal.VERIFY_UNAVAILABLE)


# --- the approval record -----------------------------------------------------------


_RecordKey = tuple[SessionSignals, ApprovalCite, ActClass]


class ApprovalRecords:
    """Verified approvals, in daemon memory only, so no file write can mint one.

    Keyed by (session signals, cite, act class). Only passes are recorded. A
    record lapses at ``stamp + ttl_seconds`` (exclusive), and expired records
    are pruned on every write.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = DEFAULT_RECORD_TTL_SECONDS,
    ) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._stamps: dict[_RecordKey, float] = {}

    def live(self, signals: SessionSignals, cite: ApprovalCite, act: ActClass) -> bool:
        stamp = self._stamps.get((signals, cite, act))
        return stamp is not None and self._clock() < stamp + self._ttl

    def record(
        self, signals: SessionSignals, cite: ApprovalCite, acts: frozenset[ActClass]
    ) -> None:
        now = self._clock()
        self._stamps = {
            key: stamp for key, stamp in self._stamps.items() if now < stamp + self._ttl
        }
        for act in acts:
            self._stamps[(signals, cite, act)] = now


# --- arming and the decision ---------------------------------------------------------


def is_armed(
    hook_input: Mapping[str, Any],
    context: SeatContext,
    *,
    coordinator_seats_only: bool = True,
) -> bool:
    """Whether the check applies to this event at all.

    Never on an absent team or a sub-agent. With ``coordinator_seats_only``
    (Q5, proposed, owner ruling pending) it arms on a main thread whose seat is
    coordinator in some held team, or whose role cannot be read (unknown never
    disarms). Without it, every main-thread seat is armed. Arming never makes a
    pass easier: :func:`check_approval` still requires the coordinator role.
    """
    if context.state is SeatState.ABSENT or not acts_as_main_thread(hook_input):
        return False
    if context.state is SeatState.UNRESOLVED or not coordinator_seats_only:
        return True
    for seat in context.seats:
        if seat.role_kind is RoleKind.UNKNOWN:
            return True
        if seat.role_kind is RoleKind.DECLARED and seat.role.casefold() == ROLE_COORDINATOR:
            return True
    return False


def _go_covers(
    hook_input: Mapping[str, Any], context: SeatContext, go: GoGrant | None, now: float
) -> frozenset[ActClass]:
    if go is None or now >= go.window_end:
        return frozenset()
    gate = role_gate(hook_input, context, team=go.team, role=ROLE_COORDINATOR)
    if gate.verdict is not GateVerdict.APPLIES:
        return frozenset()
    return go.classes


def check_approval(
    hook_input: Mapping[str, Any],
    context: SeatContext,
    signals: SessionSignals,
    *,
    acts: frozenset[ActClass],
    cite: ApprovalCite | None,
    verifier: Verifier = DEFAULT_VERIFIER,
    go: GoGrant | None = None,
    records: ApprovalRecords,
    clock: Callable[[], float] = time.monotonic,
) -> ApprovalVerdict:
    """Whether a human approved ``acts`` for this seat. Never raises.

    Order: no seat or a sub-agent refuses; acts a live GO covers pass; the
    rest need a cite for a team where this seat is coordinator; a live record
    skips the verifier; otherwise the verified line must be the cited one, in
    the questions room, from a declared human.
    """
    if context.state is SeatState.ABSENT:
        return _refused(Refusal.NO_TEAM_SEAT)
    if not acts_as_main_thread(hook_input):
        return _refused(Refusal.SUBAGENT)
    if not acts:
        return _refused(Refusal.NO_ACTS)
    remaining = acts - _go_covers(hook_input, context, go, clock())
    if not remaining:
        return ApprovalVerdict(True, None, "covered by a live readiness GO for these act classes")
    checked = parse_cite(cite.team, cite.event_id) if cite is not None else None
    if checked is None:
        return _refused(Refusal.NO_CITE)
    gate = role_gate(hook_input, context, team=checked.team, role=ROLE_COORDINATOR)
    if gate.verdict is GateVerdict.ROLE_UNKNOWN:
        return _refused(Refusal.ROLE_UNKNOWN)
    if gate.verdict is not GateVerdict.APPLIES:
        return _refused(Refusal.NOT_COORDINATOR)
    if all(records.live(signals, checked, act) for act in remaining):
        return ApprovalVerdict(True, None, "a recent human approval for this cite is still live")
    answer: object = verifier(signals, checked)
    if isinstance(answer, VerifyFailure):
        return _refused(answer.refusal)
    if not isinstance(answer, VerifiedLine):
        return _refused(Refusal.ANSWER_UNREADABLE)
    if normalise_name(answer.team) != checked.team or answer.event_id != checked.event_id:
        return _refused(Refusal.ANSWER_MISMATCH)
    if answer.room != QUESTIONS_ROOM:
        return _refused(Refusal.NOT_QUESTIONS_ROOM)
    if answer.declared_human is not True:
        return _refused(Refusal.NOT_HUMAN)
    records.record(signals, checked, remaining)
    return ApprovalVerdict(True, None, "a declared human approved this in the questions room")
