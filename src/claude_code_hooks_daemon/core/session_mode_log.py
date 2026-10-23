"""The session-mode transition log (Plan 00501 Task 4.3).

Every time a session mode is entered or ends, the registry appends one record
naming what triggered it (its evidence), so ``hooks-daemon mode-history`` can
show why a session is, or was, in a mode. The log is a JSON-lines file under
the daemon's untracked directory, bounded to the newest ``max_records``
records, and rewritten atomically on each append (``unique_temp_path`` then a
rename), so a reader never sees half a record.

A log that cannot be read is a named :class:`TransitionLogReadError`, never an
empty history. An append over a log whose content does not parse renames it to
a unique ``*.<time>.<token>.corrupt`` name (logged at WARNING) and starts a
fresh one, so one bad line cannot stop every later transition being recorded;
an append over a log it cannot READ raises the ``OSError`` and moves nothing.
"""

from __future__ import annotations

import json
import logging
import math
import secrets
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.session_modes import ModeLabel
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

#: The log's file name, directly under the daemon's untracked directory.
TRANSITION_LOG_FILENAME: Final[str] = "session-mode-transitions.jsonl"

#: The newest records kept; older ones are dropped on the next append.
MAX_TRANSITIONS: Final[int] = 500

#: Appended to a log that could not be read back.
CORRUPT_SUFFIX: Final[str] = ".corrupt"

#: How many leading characters of a session id a printed line shows.
_SESSION_SHOWN: Final[int] = 8

FIELD_AT: Final[str] = "at"
FIELD_SESSION_ID: Final[str] = "session_id"
FIELD_LABEL: Final[str] = "label"
FIELD_ACTION: Final[str] = "action"
FIELD_EVIDENCE: Final[str] = "evidence"
FIELD_DETAIL: Final[str] = "detail"

_FIELDS: Final[frozenset[str]] = frozenset(
    {FIELD_AT, FIELD_SESSION_ID, FIELD_LABEL, FIELD_ACTION, FIELD_EVIDENCE, FIELD_DETAIL}
)


class TransitionLogError(Exception):
    """The transition log, or one of its records, cannot be read."""


class TransitionLogReadError(TransitionLogError):
    """The log file itself could not be read (permissions, I/O): its content is unknown."""


class TransitionAction(StrEnum):
    """What happened to a mode."""

    ENTER = "enter"
    EXIT = "exit"
    EXPIRE = "expire"
    RESTART_CLEAR = "restart-clear"
    # The goal-loop detector's observations (Plan 00501 Phase 6): a ring one cycle
    # short of its threshold, a ring at it, and a ring emptied by an exit cause.
    NEAR_MISS = "near-miss"
    WOULD_ENTER = "would-enter"
    LOOP_RESET = "loop-reset"
    # A typed `/goal clear` and who it is attributed to (Plan 00501 Task 8.2; detail).
    GOAL_CLEAR = "goal-clear"


@dataclass(frozen=True, slots=True)
class ModeTransition:
    """One mode entered or ended, with what triggered it.

    Attributes:
        at: Epoch seconds of the transition.
        session_id: The session concerned.
        label: The mode's status-line label.
        action: Entered, exited, expired or cleared by a restart.
        evidence: Who or what triggered it (a prompt command, a stop, a TTL).
        detail: The focus task or other entry detail, else empty.
    """

    at: float
    session_id: str
    label: ModeLabel
    action: TransitionAction
    evidence: str
    detail: str = ""

    def __post_init__(self) -> None:
        """Refuse a record that would not say whose mode or why. Raises ``ValueError``."""
        if not self.session_id.strip():
            raise ValueError("a transition needs a session id")
        if not self.evidence.strip():
            raise ValueError("a transition needs its evidence")

    def to_record(self) -> dict[str, object]:
        """The JSON record for one log line."""
        return {
            FIELD_AT: self.at,
            FIELD_SESSION_ID: self.session_id,
            FIELD_LABEL: str(self.label),
            FIELD_ACTION: str(self.action),
            FIELD_EVIDENCE: self.evidence,
            FIELD_DETAIL: self.detail,
        }

    @classmethod
    def from_record(cls, record: object) -> ModeTransition:
        """Parse one log record.

        Raises:
            TransitionLogError: the record is not a valid transition.
        """
        if not isinstance(record, dict) or set(record) != _FIELDS:
            raise TransitionLogError(f"not a transition record: {record!r}")
        at = record[FIELD_AT]
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at):
            raise TransitionLogError(f"{FIELD_AT} is not a finite number: {at!r}")
        texts = [record[name] for name in (FIELD_SESSION_ID, FIELD_EVIDENCE, FIELD_DETAIL)]
        if not all(isinstance(text, str) for text in texts):
            raise TransitionLogError(f"a text field is not a string: {record!r}")
        try:
            return cls(
                at=float(at),
                session_id=str(record[FIELD_SESSION_ID]),
                label=ModeLabel(record[FIELD_LABEL]),
                action=TransitionAction(record[FIELD_ACTION]),
                evidence=str(record[FIELD_EVIDENCE]),
                detail=str(record[FIELD_DETAIL]),
            )
        except ValueError as error:
            raise TransitionLogError(str(error)) from error

    def line(self) -> str:
        """One printable line: time, session, action and mode, evidence, detail."""
        stamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(self.at))
        detail = f" ({self.detail})" if self.detail else ""
        return (
            f"{stamp}  {self.session_id[:_SESSION_SHOWN]}  {self.action} {self.label}"
            f"{detail} -- {self.evidence}"
        )


class TransitionLog:
    """An append-only, bounded JSON-lines log of mode transitions.

    Args:
        path: The log file.
        max_records: The newest records kept.

    Raises:
        ValueError: ``max_records`` is not positive.
    """

    def __init__(self, path: Path, *, max_records: int = MAX_TRANSITIONS) -> None:
        if max_records < 1:
            raise ValueError(f"max_records must be positive, got {max_records}")
        self._path = path
        self._max_records = max_records
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        """The log file."""
        return self._path

    def append(self, transitions: Sequence[ModeTransition]) -> None:
        """Add ``transitions`` after the existing records, keeping the newest ``max_records``.

        Only a log whose content does not parse is quarantined; one that cannot
        be READ is left where it is, since nothing is known about its content.

        Raises:
            OSError: the log could not be read or written; no temporary file is left.
        """
        if not transitions:
            return
        with self._lock:
            text = self._read_text()
            try:
                existing = self._parse(text)
            except TransitionLogError as error:
                corrupt = _quarantine_path(self._path)
                logger.warning(
                    "session-mode transition log is corrupt (%s); renaming it to %s", error, corrupt
                )
                self._path.rename(corrupt)
                existing = []
            kept = [*existing, *transitions][-self._max_records :]
            text = "".join(json.dumps(t.to_record()) + "\n" for t in kept)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = unique_temp_path(self._path)
            try:
                tmp_path.write_text(text, encoding="utf-8")
                tmp_path.replace(self._path)
            except OSError:
                tmp_path.unlink(missing_ok=True)
                raise

    def recent(self, limit: int, *, session_id: str | None = None) -> list[ModeTransition]:
        """The newest ``limit`` transitions, oldest first, optionally for one session.

        A log that does not exist yet holds no transitions.

        Raises:
            ValueError: ``limit`` is not positive.
            TransitionLogReadError: the log file cannot be read.
            TransitionLogError: the log holds a malformed record.
        """
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")
        with self._lock:
            try:
                text = self._read_text()
            except OSError as error:
                raise TransitionLogReadError(f"cannot read {self._path}: {error}") from error
            records = self._parse(text)
        if session_id is not None:
            records = [t for t in records if t.session_id == session_id]
        return records[-limit:]

    def _read_text(self) -> str:
        """The log's text; empty when it does not exist yet. Any other ``OSError`` propagates."""
        try:
            return self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def _parse(self, text: str) -> list[ModeTransition]:
        """Every record in ``text``. Raises ``TransitionLogError``."""
        transitions: list[ModeTransition] = []
        for number, raw in enumerate(text.splitlines(), start=1):
            try:
                transitions.append(ModeTransition.from_record(json.loads(raw)))
            except (ValueError, TransitionLogError) as error:
                raise TransitionLogError(f"{self._path} line {number}: {error}") from error
        return transitions


def _quarantine_path(path: Path) -> Path:
    """A name beside ``path`` for a corrupt copy that no earlier quarantine holds.

    The UTC time and a random token make each name distinct, so a second
    quarantine never replaces the evidence of the first.
    """
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return path.with_name(f"{path.name}.{stamp}.{secrets.token_hex(4)}{CORRUPT_SUFFIX}")
