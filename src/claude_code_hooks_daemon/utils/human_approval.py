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

The ``verify`` contract (fedora-desktop issue 369) is the one its peer seat
relayed (plan 00634 subagent-reports/261124-fedora-desktop-contract-reply.md);
it has not been checked against a live teamchat from this repository, so
:func:`parse_verify_answer` refuses anything off that contract.

The binding switches in :class:`BindingPolicy` (a ``Q<n>`` answer, a maximum
line age, single use per cite and act class) are owner question O4 and are
all OFF by default.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.handler_scope import acts_as_main_thread
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
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

logger = logging.getLogger(__name__)

#: The room a human's approval must be posted in.
QUESTIONS_ROOM: Final[str] = "questions"
#: The only ``verify`` record kind and version this module reads.
VERIFY_ANSWER_KIND: Final[str] = "verified"
VERIFY_ANSWER_VERSION: Final[int] = 1
#: Exactly the keys of one ``verify`` record; a missing or extra key refuses.
VERIFY_ANSWER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "kind",
        "v",
        "team",
        "id",
        "item",
        "from",
        "room",
        "text",
        "body_sha256",
        "sent_ms",
        "human",
        "question",
        "headline",
    }
)
_STRING_KEYS: Final[tuple[str, ...]] = (
    "kind",
    "team",
    "id",
    "item",
    "from",
    "room",
    "text",
    "body_sha256",
)
#: ``question`` when the line answers no question.
QUESTION_NONE: Final[str] = "none"
#: ``verify`` exit codes (issue 369). Any other non-zero exit refuses as off contract.
EXIT_NOT_FOUND: Final[int] = 23
EXIT_UNTRUSTED: Final[int] = 22
EXIT_UNREACHABLE: Final[int] = 20
EXIT_RATE_LIMITED: Final[int] = 14
#: How long a verified approval is reused for the same cite and act class.
DEFAULT_RECORD_TTL_SECONDS: Final[float] = 300.0
#: How far in the future a line's ``sent_ms`` may sit before it is refused.
FUTURE_SKEW_MS: Final[int] = 60_000
#: Largest single-use ledger read; a larger file refuses every cite.
MAX_LEDGER_BYTES: Final[int] = 256 * 1024
LEDGER_VERSION: Final[int] = 1

#: A teamchat event id (issue 369): ``$`` and exactly 43 of ``[A-Za-z0-9_-]``.
#: The leading ``$`` means it can never be read as an option; no ``/``, ``.``
#: or ``~``, so it can never be read as a path.
_EVENT_ID: Final[re.Pattern[str]] = re.compile(r"\$[A-Za-z0-9_-]{43}")
#: The attached question tag (``Q7``). Anything else is dropped, never kept.
_QUESTION_TAG: Final[re.Pattern[str]] = re.compile(r"Q[0-9]{1,9}")

#: What a failed runner or parse may raise; each is a refusal, never a raise.
_VERIFY_ERRORS: Final[tuple[type[BaseException], ...]] = (
    OSError,
    subprocess.TimeoutExpired,
    ValueError,
    RecursionError,
    UnicodeDecodeError,
)


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
    VERIFY_UNAVAILABLE = "verify_unavailable"
    VERIFY_REFUSED = "verify_refused"
    LINE_NOT_FOUND = "line_not_found"
    VERIFY_UNTRUSTED = "verify_untrusted"
    VERIFY_UNREACHABLE = "verify_unreachable"
    VERIFY_RATE_LIMITED = "verify_rate_limited"
    ANSWER_UNREADABLE = "answer_unreadable"
    ANSWER_MISMATCH = "answer_mismatch"
    NOT_QUESTIONS_ROOM = "not_questions_room"
    NOT_HUMAN = "not_human"
    NO_QUESTION = "no_question"
    LINE_OUT_OF_WINDOW = "line_out_of_window"
    CITE_ALREADY_USED = "cite_already_used"
    LEDGER_UNAVAILABLE = "ledger_unavailable"


#: One fixed text per refusal. Never built from answer content (invariant 4).
_REASONS: Final[Mapping[Refusal, str]] = {
    Refusal.NO_TEAM_SEAT: "this session holds no team seat",
    Refusal.SUBAGENT: "a sub-agent is not judged here; the coordinator acts",
    Refusal.NO_ACTS: "no destructive act was named, so there is nothing to approve",
    Refusal.NO_CITE: "no well-formed cite (team and a $-prefixed questions-room event id)",
    Refusal.ROLE_UNKNOWN: "this seat's role in the cited team cannot be read",
    Refusal.NOT_COORDINATOR: "this seat is not the coordinator in the cited team",
    Refusal.VERIFY_UNAVAILABLE: "teamchat verify could not be run (missing, untrusted or timed out)",
    Refusal.VERIFY_REFUSED: "teamchat verify exited with a code outside its contract",
    Refusal.LINE_NOT_FOUND: "teamchat verify found no such line",
    Refusal.VERIFY_UNTRUSTED: "teamchat verify could not trust the cited line",
    Refusal.VERIFY_UNREACHABLE: "teamchat verify could not reach the team's server",
    Refusal.VERIFY_RATE_LIMITED: "teamchat verify was rate limited; retry shortly",
    Refusal.ANSWER_UNREADABLE: "the teamchat verify answer could not be read",
    Refusal.ANSWER_MISMATCH: "the teamchat verify answer names another team or line",
    Refusal.NOT_QUESTIONS_ROOM: "the cited line is not in the team's questions room",
    Refusal.NOT_HUMAN: "the cited line was not sent by a declared human of the team",
    Refusal.NO_QUESTION: "the cited line answers no Q<n> question",
    Refusal.LINE_OUT_OF_WINDOW: "the cited line is older than the allowed age, or future-dated",
    Refusal.CITE_ALREADY_USED: "this cite was already used for this act",
    Refusal.LEDGER_UNAVAILABLE: "the single-use cite ledger could not be read or written",
}

_EXIT_REFUSALS: Final[Mapping[int, Refusal]] = {
    EXIT_NOT_FOUND: Refusal.LINE_NOT_FOUND,
    EXIT_UNTRUSTED: Refusal.VERIFY_UNTRUSTED,
    EXIT_UNREACHABLE: Refusal.VERIFY_UNREACHABLE,
    EXIT_RATE_LIMITED: Refusal.VERIFY_RATE_LIMITED,
}


@dataclass(frozen=True)
class ApprovalCite:
    """A cited questions-room line: the team and the line's event id."""

    team: str
    event_id: str


@dataclass(frozen=True)
class VerifiedLine:
    """What ``verify`` said about one line. The text and headline are deliberately absent.

    ``question`` is the ``Q<n>`` tag, or ``""`` when the line answers none.
    """

    team: str
    event_id: str
    room: str
    declared_human: bool
    question: str
    sent_ms: int


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
class BindingPolicy:
    """What a verified line must also satisfy (owner question O4). All OFF by default."""

    require_question: bool = False
    max_line_age_seconds: int | None = None
    single_use: bool = False

    @property
    def any_on(self) -> bool:
        return self != BindingPolicy()


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


# --- the verify answer (issue 369 contract) ----------------------------------------


def _question_field(value: object) -> str | None:
    """The ``Q<n>`` tag, ``""`` for ``none`` or null, None when off contract."""
    if value is None or value == QUESTION_NONE:
        return ""
    if isinstance(value, str) and _QUESTION_TAG.fullmatch(value):
        return value
    return None


def _well_typed(document: Mapping[str, Any]) -> bool:
    if not all(type(document[key]) is str for key in _STRING_KEYS):
        return False
    # bool is an int subclass, so ints are checked by exact type.
    version, sent_ms = document["v"], document["sent_ms"]
    if type(version) is not int or version != VERIFY_ANSWER_VERSION:
        return False
    if type(sent_ms) is not int or sent_ms < 0:
        return False
    if type(document["human"]) is not bool:
        return False
    headline = document["headline"]
    return headline is None or type(headline) is str


def parse_verify_answer(text: str, cite: ApprovalCite) -> VerifiedLine | VerifyFailure:
    """Read one ``verify`` record line about ``cite``. Never raises.

    Exactly one line, kind ``verified``, exactly :data:`VERIFY_ANSWER_KEYS`,
    each of its contract type. A line about another team or event is a
    mismatch; a sender who is not a declared human is refused here.
    """
    line = text[:-1] if text.endswith("\n") else text
    if not line or "\n" in line or "\r" in line:
        return VerifyFailure(Refusal.ANSWER_UNREADABLE)
    document: object = decode_json_document(line)
    if not isinstance(document, dict) or set(document) != VERIFY_ANSWER_KEYS:
        return VerifyFailure(Refusal.ANSWER_UNREADABLE)
    if not _well_typed(document) or document["kind"] != VERIFY_ANSWER_KIND:
        return VerifyFailure(Refusal.ANSWER_UNREADABLE)
    question = _question_field(document["question"])
    if question is None:
        return VerifyFailure(Refusal.ANSWER_UNREADABLE)
    answered_team = normalise_name(document["team"])
    if (
        document["id"] != cite.event_id
        or not answered_team
        or answered_team != normalise_name(cite.team)
    ):
        return VerifyFailure(Refusal.ANSWER_MISMATCH)
    if document["human"] is not True:
        return VerifyFailure(Refusal.NOT_HUMAN)
    return VerifiedLine(
        team=answered_team,
        event_id=cite.event_id,
        room=normalise_name(document["room"]),
        declared_human=True,
        question=question,
        sent_ms=document["sent_ms"],
    )


class TeamchatVerifyCli:
    """``teamchat verify <event-id> --room questions``, through the runner seam only.

    The runner bounds the output (``MAX_OUTPUT_BYTES``) and the time
    (``timeout``); anything it or the parse raises is a refusal.
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
        try:
            outcome = run_kit_command(
                signals,
                ("verify", checked.event_id, "--room", QUESTIONS_ROOM),
                runner=self._runner,
                timeout=self._timeout,
            )
        except _VERIFY_ERRORS as exc:
            # Only the type is logged: no answer content can reach the log.
            logger.warning("teamchat verify could not run (%s)", type(exc).__name__)
            return VerifyFailure(Refusal.VERIFY_UNAVAILABLE)
        if isinstance(outcome, ProbeReason):
            return VerifyFailure(Refusal.VERIFY_UNAVAILABLE)
        if outcome.status is CommandStatus.OK:
            if outcome.exit_code != 0 or not isinstance(outcome.stdout, str):
                return VerifyFailure(Refusal.ANSWER_UNREADABLE)
            try:
                return parse_verify_answer(outcome.stdout, checked)
            except _VERIFY_ERRORS as exc:
                logger.warning("teamchat verify answer unreadable (%s)", type(exc).__name__)
                return VerifyFailure(Refusal.ANSWER_UNREADABLE)
        if outcome.status is CommandStatus.TOO_LARGE:
            return VerifyFailure(Refusal.ANSWER_UNREADABLE)
        if outcome.status is CommandStatus.EXITED:
            code = outcome.exit_code
            return VerifyFailure(
                _EXIT_REFUSALS.get(code, Refusal.VERIFY_REFUSED)
                if isinstance(code, int)
                else Refusal.VERIFY_REFUSED
            )
        return VerifyFailure(Refusal.VERIFY_UNAVAILABLE)


DEFAULT_VERIFIER: Final[Verifier] = TeamchatVerifyCli()


# --- the approval record -----------------------------------------------------------


_RecordKey = tuple[SessionSignals, ApprovalCite, ActClass]


class ApprovalRecords:
    """Verified approvals, in daemon memory only, so no file write can mint one.

    Keyed by (session signals, cite, act class). Only passes are recorded. A
    record lapses at ``stamp + ttl_seconds`` (exclusive), and expired records
    are pruned on every write. Unused while any binding switch is on.
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


# --- the single-use ledger (BindingPolicy.single_use, OFF by default) ---------------


class LedgerOutcome(StrEnum):
    UNUSED = "unused"
    ALREADY_USED = "already_used"
    CONSUMED = "consumed"
    UNAVAILABLE = "unavailable"


_LedgerEntry = tuple[str, str, str]
_LEDGER_LOCK: Final[threading.Lock] = threading.Lock()


class CiteLedger:
    """Which (team, event id, act class) a cite has been used for, in one JSON file.

    The path is resolved only when the ledger is used, so with single use OFF
    nothing is resolved or opened. The file holds ids and act classes only,
    never line text. An unreadable, oversized or unwritable file is
    UNAVAILABLE, which refuses (fail closed). Deleting the file re-allows
    every cite it recorded.
    """

    def __init__(self, path: Callable[[], Path]) -> None:
        self._path = path

    def used(self, cite: ApprovalCite, acts: frozenset[ActClass]) -> LedgerOutcome:
        with _LEDGER_LOCK:
            entries = self._load()
        if entries is None:
            return LedgerOutcome.UNAVAILABLE
        return LedgerOutcome.ALREADY_USED if _keys(cite, acts) & entries else LedgerOutcome.UNUSED

    def consume(self, cite: ApprovalCite, acts: frozenset[ActClass]) -> LedgerOutcome:
        """Check and record in one locked step."""
        with _LEDGER_LOCK:
            entries = self._load()
            if entries is None:
                return LedgerOutcome.UNAVAILABLE
            wanted = _keys(cite, acts)
            if wanted & entries:
                return LedgerOutcome.ALREADY_USED
            return (
                LedgerOutcome.CONSUMED
                if self._save(entries | wanted)
                else (LedgerOutcome.UNAVAILABLE)
            )

    def _resolve(self) -> Path | None:
        try:
            return self._path()
        except Exception as exc:
            log_and_continue(
                logger,
                exc,
                reason="the single-use ledger path cannot be resolved, so the cite is refused",
            )
            return None

    def _load(self) -> set[_LedgerEntry] | None:
        path = self._resolve()
        if path is None:
            return None
        try:
            with path.open("rb") as handle:
                raw = handle.read(MAX_LEDGER_BYTES + 1)
        except FileNotFoundError:
            return set()
        except OSError as exc:
            log_and_continue(
                logger, exc, reason="the single-use ledger cannot be read, so the cite is refused"
            )
            return None
        if len(raw) > MAX_LEDGER_BYTES:
            return None
        document: object = decode_json_document(raw.decode("utf-8", errors="replace"))
        return _ledger_entries(document)

    def _save(self, entries: set[_LedgerEntry]) -> bool:
        path = self._resolve()
        if path is None:
            return False
        body = json.dumps({"v": LEDGER_VERSION, "used": sorted(list(e) for e in entries)})
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(body, encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            log_and_continue(
                logger,
                exc,
                reason="the single-use ledger cannot be written, so the cite is refused",
            )
            return False
        return True


def _keys(cite: ApprovalCite, acts: frozenset[ActClass]) -> set[_LedgerEntry]:
    return {(cite.team, cite.event_id, act.value) for act in acts}


def _ledger_entries(document: object) -> set[_LedgerEntry] | None:
    if not isinstance(document, dict) or set(document) != {"v", "used"}:
        return None
    if type(document["v"]) is not int or document["v"] != LEDGER_VERSION:
        return None
    used = document["used"]
    if not isinstance(used, list):
        return None
    entries: set[_LedgerEntry] = set()
    for row in used:
        if not (isinstance(row, list) and len(row) == 3 and all(type(f) is str for f in row)):
            return None
        entries.add((row[0], row[1], row[2]))
    return entries


# --- arming and the decision ---------------------------------------------------------


def _declared_coordinator(context: SeatContext) -> bool:
    return any(
        seat.role_kind is RoleKind.DECLARED and seat.role.casefold() == ROLE_COORDINATOR
        for seat in context.seats
    )


def is_armed(
    hook_input: Mapping[str, Any],
    context: SeatContext,
    *,
    coordinator_seats_only: bool = True,
    include_subagents: bool = False,
) -> bool:
    """Whether the check applies to this event at all.

    Never on an absent team. On the main thread, with ``coordinator_seats_only``
    (Q5, proposed) it arms a seat that is coordinator in some held team, or
    whose role cannot be read; without it, every main-thread seat. A
    sub-agent is armed only with ``include_subagents`` (Plan 00634 P2) and
    only when a held seat is DECLARED coordinator: nothing is assumed for a
    sub-agent. Arming never makes a pass easier.
    """
    if context.state is SeatState.ABSENT:
        return False
    if not acts_as_main_thread(hook_input):
        return include_subagents and _declared_coordinator(context)
    if context.state is SeatState.UNRESOLVED or not coordinator_seats_only:
        return True
    if any(seat.role_kind is RoleKind.UNKNOWN for seat in context.seats):
        return True
    return _declared_coordinator(context)


def _go_covers(
    hook_input: Mapping[str, Any],
    context: SeatContext,
    go: GoGrant | None,
    now: float,
    include_subagents: bool,
) -> frozenset[ActClass]:
    if go is None or now >= go.window_end:
        return frozenset()
    gate = role_gate(
        hook_input,
        context,
        team=go.team,
        role=ROLE_COORDINATOR,
        include_subagents=include_subagents,
    )
    if gate.verdict is not GateVerdict.APPLIES:
        return frozenset()
    return go.classes


def _binding_refusal(
    answer: VerifiedLine, policy: BindingPolicy, wall_clock: Callable[[], float]
) -> Refusal | None:
    # str(): a hand-built verifier's non-string question can never match.
    if policy.require_question and not _QUESTION_TAG.fullmatch(str(answer.question)):
        return Refusal.NO_QUESTION
    if policy.max_line_age_seconds is not None:
        age_ms = wall_clock() * 1000 - answer.sent_ms
        if age_ms < -FUTURE_SKEW_MS or age_ms > policy.max_line_age_seconds * 1000:
            return Refusal.LINE_OUT_OF_WINDOW
    return None


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
    policy: BindingPolicy = BindingPolicy(),
    ledger: CiteLedger | None = None,
    wall_clock: Callable[[], float] = time.time,
    include_subagents: bool = False,
) -> ApprovalVerdict:
    """Whether a human approved ``acts`` for this seat. Never raises.

    Order: no seat refuses, and so does a sub-agent unless
    ``include_subagents``; acts a live GO covers pass; the rest need a cite
    for a team where this seat is coordinator; a used cite (single use on)
    refuses; a live record skips the verifier (all binding switches off);
    otherwise the verified line must be the cited one, in the questions
    room, from a declared human, and meet every binding switch that is on.
    """
    if context.state is SeatState.ABSENT:
        return _refused(Refusal.NO_TEAM_SEAT)
    if not include_subagents and not acts_as_main_thread(hook_input):
        return _refused(Refusal.SUBAGENT)
    if not acts:
        return _refused(Refusal.NO_ACTS)
    remaining = acts - _go_covers(hook_input, context, go, clock(), include_subagents)
    if not remaining:
        return ApprovalVerdict(True, None, "covered by a live readiness GO for these act classes")
    checked = parse_cite(cite.team, cite.event_id) if cite is not None else None
    if checked is None:
        return _refused(Refusal.NO_CITE)
    gate = role_gate(
        hook_input,
        context,
        team=checked.team,
        role=ROLE_COORDINATOR,
        include_subagents=include_subagents,
    )
    if gate.verdict is GateVerdict.ROLE_UNKNOWN:
        return _refused(Refusal.ROLE_UNKNOWN)
    if gate.verdict is not GateVerdict.APPLIES:
        return _refused(Refusal.NOT_COORDINATOR)
    if policy.single_use:
        if ledger is None:
            return _refused(Refusal.LEDGER_UNAVAILABLE)
        prior = ledger.used(checked, remaining)
        if prior is LedgerOutcome.UNAVAILABLE:
            return _refused(Refusal.LEDGER_UNAVAILABLE)
        if prior is LedgerOutcome.ALREADY_USED:
            return _refused(Refusal.CITE_ALREADY_USED)
    elif not policy.any_on and all(records.live(signals, checked, act) for act in remaining):
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
    binding = _binding_refusal(answer, policy, wall_clock)
    if binding is not None:
        return _refused(binding)
    if policy.single_use and ledger is not None:
        consumed = ledger.consume(checked, remaining)
        if consumed is LedgerOutcome.ALREADY_USED:
            return _refused(Refusal.CITE_ALREADY_USED)
        if consumed is not LedgerOutcome.CONSUMED:
            return _refused(Refusal.LEDGER_UNAVAILABLE)
    records.record(signals, checked, remaining)
    return ApprovalVerdict(True, None, "a declared human approved this in the questions room")
