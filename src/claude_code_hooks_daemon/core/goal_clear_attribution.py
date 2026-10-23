"""Who cleared the goal: the ccy supervisor or a human (Plan 00501 Task 8.2).

A typed ``/goal clear`` (or an alias) starts no turn and fires no
``UserPromptSubmit`` (Task 8.1); it leaves a ``system``/``local_command``
record pair in the transcript, so the daemon reads it at the next Stop.

Before the supervisor types a clearing ``/goal`` it writes a
``<session>.goal-clear-injected`` record beside its other signal files
(``.claude/ccy/claude-supervise.py``, ``write_goal_clear_record``). A clear is
then attributed:

* a fresh, matching record: the supervisor cleared it (the record is consumed);
* no record, or one that is stale or names another command or session: a human;
* a record that cannot be read: the supervisor, logged at WARNING, with one line
  telling the human to repeat the clear if it was theirs. This leans the safe
  way: a spurious "human" would silently switch automated goals off, while a
  missed human clear costs them one retyped command.

The attribution is one ``goal-clear`` transition in the session-mode log, its
``detail`` the :class:`Attribution`, for Task 8.3's ``manual-goals`` mode.
:class:`AttributedClears` keeps each clear attributed at most once across
daemon restarts, independent of how long the bounded log keeps its record.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.core.session_mode_log import ModeTransition, TransitionAction
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.session_modes import ModeLabel
from claude_code_hooks_daemon.utils.session_signal_paths import session_stem
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

#: The supervisor's record, beside the ``<session>.goal-clear`` trigger it consumes.
#: It must not end in ``.goal-clear``, or the supervisor would read it as a trigger.
GOAL_CLEAR_RECORD_SUFFIX: Final[str] = ".goal-clear-injected"

#: The arguments that make ``/goal`` clear, matched on the whole trimmed argument,
#: ignoring case (read out of the shipped Claude Code binary; any other text sets a goal).
CLEARING_TOKENS: Final[frozenset[str]] = frozenset(
    {"clear", "stop", "off", "reset", "none", "cancel"}
)

#: How long after the record a clear still counts as the supervisor's. The supervisor
#: writes the record in the same tick it types the command, and an idle Claude Code
#: records the command at once, so the gap is normally under a second. Two minutes
#: absorbs a slow PTY write or a loaded host, and is still short enough that a human
#: clear typed later is not taken for an older supervisor clear that never landed.
FRESH_WINDOW_SECONDS: Final[float] = 120.0

#: How far a record may post-date the clear it attributes. The supervisor stamps the
#: record at the start of the tick that types the clear, so its own clear is never
#: earlier; the only slack needed is the transcript flooring to whole milliseconds
#: (both clocks are this host's). Anything wider takes a human clear typed just
#: before the supervisor's tick for the supervisor's (Plan 00474 N534).
CLOCK_TOLERANCE_SECONDS: Final[float] = 0.001

_COMMAND_PREFIX: Final[str] = "/goal "
_RECORD_TYPE_SYSTEM: Final[str] = "system"
_SUBTYPE_LOCAL_COMMAND: Final[str] = "local_command"
_COMMAND_NAME_RE: Final[re.Pattern[str]] = re.compile(r"<command-name>/goal</command-name>")
_COMMAND_ARGS_RE: Final[re.Pattern[str]] = re.compile(
    r"<command-args>(.*?)</command-args>", re.DOTALL
)
_FIELD_SESSION_ID: Final[str] = "session_id"
_FIELD_TS: Final[str] = "ts"
_FIELD_COMMAND: Final[str] = "command"
_EVIDENCE_KEY_PREFIX: Final[str] = "clear="

#: The daemon-owned store of clears already attributed, in the daemon untracked dir.
ATTRIBUTED_CLEARS_FILENAME: Final[str] = "goal-clear-attributed.json"

#: Sessions whose attributed-clears mark is kept; the one with the oldest mark is dropped.
MAX_ATTRIBUTED_SESSIONS: Final[int] = 1024

_STORE_VERSION: Final[int] = 1
_FIELD_VERSION: Final[str] = "version"
_FIELD_SESSIONS: Final[str] = "sessions"
_FIELD_AT: Final[str] = "at"
_FIELD_KEYS: Final[str] = "keys"
_CORRUPT_SUFFIX: Final[str] = ".corrupt"


class Attribution(StrEnum):
    """Who a typed clear is attributed to."""

    SUPERVISOR = "supervisor"
    HUMAN = "human"
    #: The record could not be read, so the supervisor is assumed.
    SUPERVISOR_ASSUMED = "supervisor-assumed"


class GoalClearAttributionError(Exception):
    """A clear cannot be attributed: its input is not what attribution needs."""


class ClearRecordUnreadableError(GoalClearAttributionError):
    """The supervisor's record exists but cannot be read as a record."""


@dataclass(frozen=True, slots=True)
class TypedClear:
    """One clearing ``/goal`` the transcript recorded.

    Attributes:
        key: The transcript record's uuid (else its timestamp), so a clear read
            twice, after a daemon restart, is attributed once.
        at: Epoch seconds of the record.
        argument: The clearing token, trimmed and lower-cased.
    """

    key: str
    at: float
    argument: str


@dataclass(frozen=True, slots=True)
class ClearRecord:
    """The supervisor's record of a clear it is about to type."""

    session: str
    ts: float
    command: str


def record_path(directory: Path, session_id: str) -> Path:
    """Where the supervisor's record for ``session_id`` lives in ``directory``."""
    return directory / f"{session_stem(session_id)}{GOAL_CLEAR_RECORD_SUFFIX}"


def _clear_in(record: dict[str, object]) -> TypedClear | None:
    """The clear one transcript record carries, else None. Raises on a clear with no timestamp."""
    if record.get("type") != _RECORD_TYPE_SYSTEM or record.get("subtype") != _SUBTYPE_LOCAL_COMMAND:
        return None
    content = record.get("content")
    if not isinstance(content, str) or not _COMMAND_NAME_RE.search(content):
        return None
    found = _COMMAND_ARGS_RE.search(content)
    argument = found.group(1).strip().lower() if found else ""
    if argument not in CLEARING_TOKENS:
        return None
    stamp = record.get("timestamp")
    try:
        if not isinstance(stamp, str):
            raise ValueError(f"not a string: {stamp!r}")
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError as error:
        raise GoalClearAttributionError(
            f"a /goal {argument} record has no usable timestamp: {error}"
        ) from error
    uuid = record.get("uuid")
    key = uuid if isinstance(uuid, str) and uuid else f"ts={stamp}"
    return TypedClear(key=key, at=at, argument=argument)


def find_typed_clears(lines: Iterable[str]) -> tuple[TypedClear, ...]:
    """Every clearing ``/goal`` in transcript ``lines``, in order.

    Lines that are not JSON objects are not clears; the goal-loop reader counts them.

    Raises:
        GoalClearAttributionError: a clear record carries no usable timestamp.
    """
    clears: list[TypedClear] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as error:
            log_and_continue(
                logger,
                error,
                reason="goal-clear attribution: a transcript line that is not JSON holds no clear",
                level=logging.DEBUG,
            )
            continue
        if isinstance(record, dict):
            clear = _clear_in(record)
            if clear is not None:
                clears.append(clear)
    return tuple(clears)


def read_clear_record(path: Path) -> ClearRecord | None:
    """The record at ``path``; None when there is none.

    Raises:
        ClearRecordUnreadableError: it exists but cannot be read or is malformed.
    """
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ClearRecordUnreadableError(f"{path}: {error}") from error
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ClearRecordUnreadableError(f"{path}: not JSON: {error}") from error
    if not isinstance(data, dict):
        raise ClearRecordUnreadableError(f"{path}: not a JSON object")
    session, ts, command = (
        data.get(_FIELD_SESSION_ID),
        data.get(_FIELD_TS),
        data.get(_FIELD_COMMAND),
    )
    if not isinstance(session, str) or not isinstance(command, str):
        raise ClearRecordUnreadableError(f"{path}: session_id and command must be strings")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts):
        raise ClearRecordUnreadableError(f"{path}: ts is not a finite number: {ts!r}")
    return ClearRecord(session=session, ts=float(ts), command=command)


@dataclass(frozen=True, slots=True)
class ClearVerdict:
    """A clear and who it is attributed to, with the evidence."""

    clear: TypedClear
    attribution: Attribution
    evidence: str

    def transition(self, session_id: str) -> ModeTransition:
        """The session-mode log record carrying this attribution."""
        return ModeTransition(
            at=self.clear.at,
            session_id=session_id,
            label=ModeLabel.MANUAL_GOALS,
            action=TransitionAction.GOAL_CLEAR,
            evidence=self.evidence,
            detail=str(self.attribution),
        )

    def line(self) -> str | None:
        """The one line for the agent when the record was unreadable, else None."""
        if self.attribution is not Attribution.SUPERVISOR_ASSUMED:
            return None
        return (
            f"a `/goal {self.clear.argument}` in this session was taken as the ccy "
            "supervisor's because its record of the clear could not be read, so automated "
            "goals stay on; if the human typed it, tell them to type `/goal clear` again"
        )


def attribute_clear(clear: TypedClear, *, session_id: str, directory: Path) -> ClearVerdict:
    """Attribute ``clear`` from the supervisor's record in ``directory``.

    A matching fresh record, or an unreadable one, is removed, so one record
    attributes one clear.

    Raises:
        GoalClearAttributionError: ``session_id`` is blank.
        OSError: a record could not be removed.
    """
    if not session_id.strip():
        raise GoalClearAttributionError("a clear needs a session id to be attributed")
    path = record_path(directory, session_id)
    prefix = f"{_EVIDENCE_KEY_PREFIX}{clear.key} args={clear.argument}"
    try:
        record = read_clear_record(path)
    except ClearRecordUnreadableError as error:
        logger.warning(
            "goal-clear attribution: record unreadable, clear taken as the supervisor's "
            "(session %s): %s",
            session_id,
            error,
        )
        path.unlink(missing_ok=True)
        return ClearVerdict(clear, Attribution.SUPERVISOR_ASSUMED, f"{prefix} record=unreadable")
    if record is None:
        return ClearVerdict(clear, Attribution.HUMAN, f"{prefix} record=none")
    expected = f"{_COMMAND_PREFIX}{clear.argument}"
    if record.session != session_stem(session_id) or record.command.lower() != expected:
        return ClearVerdict(clear, Attribution.HUMAN, f"{prefix} record=mismatch")
    gap = clear.at - record.ts
    if not -CLOCK_TOLERANCE_SECONDS <= gap <= FRESH_WINDOW_SECONDS:
        return ClearVerdict(clear, Attribution.HUMAN, f"{prefix} record=stale gap={gap:.1f}s")
    path.unlink(missing_ok=True)
    return ClearVerdict(clear, Attribution.SUPERVISOR, f"{prefix} record=fresh gap={gap:.1f}s")


class AttributedClearsError(GoalClearAttributionError):
    """The attributed-clears store was malformed; it has been quarantined."""


@dataclass(frozen=True, slots=True)
class _Mark:
    """A session's high-water mark: the latest clear time, and every key at exactly that time."""

    at: float
    keys: frozenset[str]

    def covers(self, clear: TypedClear) -> bool:
        return clear.at < self.at or (clear.at == self.at and clear.key in self.keys)


class AttributedClears:
    """Which clears are already attributed, durable across restarts (at most once per clear).

    The transition log alone cannot say so: it is bounded and shared by every
    session, so a clear's record can rotate out, and re-reading the transcript
    after a restart would attribute it again, with the supervisor's record
    already consumed, as a human's. One small file holds, per session, a
    high-water mark: the latest attributed clear's time and the keys at that
    exact time. Transcript clears are chronological, so anything at or before
    the mark is already done. Only the ``max_sessions`` sessions with the most
    recent marks are kept.

    Args:
        path: The store file.
        max_sessions: How many sessions' marks are kept.

    Raises:
        ValueError: ``max_sessions`` is below one.
    """

    def __init__(self, path: Path, *, max_sessions: int = MAX_ATTRIBUTED_SESSIONS) -> None:
        if max_sessions < 1:
            raise ValueError(f"max_sessions must be at least 1, got {max_sessions}")
        self._path = path
        self._max_sessions = max_sessions
        self._lock = threading.Lock()

    def covers(self, session_id: str, clear: TypedClear) -> bool:
        """Whether ``clear`` in ``session_id`` is already attributed.

        Raises:
            AttributedClearsError: the store was malformed (now quarantined).
            OSError: the store could not be read.
        """
        with self._lock:
            mark = self._read().get(session_id)
        return mark is not None and mark.covers(clear)

    def mark(self, session_id: str, clear: TypedClear) -> None:
        """Record ``clear`` in ``session_id`` as attributed, atomically.

        Raises:
            AttributedClearsError: the store was malformed (now quarantined).
            OSError: the store could not be read or written.
        """
        with self._lock:
            marks = self._read()
            current = marks.get(session_id)
            if current is None or clear.at > current.at:
                marks[session_id] = _Mark(clear.at, frozenset({clear.key}))
            elif clear.at == current.at:
                marks[session_id] = _Mark(current.at, current.keys | {clear.key})
            else:
                return
            kept = sorted(marks.items(), key=lambda item: item[1].at)[-self._max_sessions :]
            self._write(dict(kept))

    def _read(self) -> dict[str, _Mark]:
        if not self._path.exists():
            return {}
        text = self._path.read_text(encoding="utf-8")
        try:
            return _parse_marks(text)
        except ValueError as error:
            corrupt = self._path.with_name(self._path.name + _CORRUPT_SUFFIX)
            logger.warning(
                "goal-clear attribution: store %s is malformed, renamed to %s: %s",
                self._path,
                corrupt,
                error,
            )
            self._path.replace(corrupt)
            raise AttributedClearsError(f"{self._path}: {error}") from error

    def _write(self, marks: dict[str, _Mark]) -> None:
        payload = {
            _FIELD_VERSION: _STORE_VERSION,
            _FIELD_SESSIONS: {
                session: {_FIELD_AT: mark.at, _FIELD_KEYS: sorted(mark.keys)}
                for session, mark in marks.items()
            },
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = unique_temp_path(self._path)
        try:
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            tmp_path.replace(self._path)
        except OSError:
            tmp_path.unlink(missing_ok=True)
            raise


def _parse_marks(text: str) -> dict[str, _Mark]:
    """The store's marks. Raises ``ValueError`` on anything but a valid store."""
    data = json.loads(text)
    if not isinstance(data, dict) or data.get(_FIELD_VERSION) != _STORE_VERSION:
        raise ValueError("not a version-1 attributed-clears store")
    sessions = data.get(_FIELD_SESSIONS)
    if not isinstance(sessions, dict):
        raise ValueError(f"{_FIELD_SESSIONS} is not an object")
    marks: dict[str, _Mark] = {}
    for session, raw in sessions.items():
        if not isinstance(raw, dict):
            raise ValueError(f"the mark for {session!r} is not an object")
        at, keys = raw.get(_FIELD_AT), raw.get(_FIELD_KEYS)
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at):
            raise ValueError(f"the mark for {session!r} has no finite {_FIELD_AT}")
        if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
            raise ValueError(f"the mark for {session!r} has {_FIELD_KEYS} that are not strings")
        marks[session] = _Mark(float(at), frozenset(keys))
    return marks


def attributed_keys(transitions: Iterable[ModeTransition]) -> frozenset[str]:
    """The keys of the clears ``transitions`` already attribute."""
    keys: set[str] = set()
    for transition in transitions:
        if transition.action is not TransitionAction.GOAL_CLEAR:
            continue
        head = transition.evidence.split(" ", 1)[0]
        if head.startswith(_EVIDENCE_KEY_PREFIX):
            keys.add(head.removeprefix(_EVIDENCE_KEY_PREFIX))
    return frozenset(keys)
