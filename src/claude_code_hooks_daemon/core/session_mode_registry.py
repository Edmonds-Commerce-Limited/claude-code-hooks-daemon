"""The session-modes registry: per-session focus/blocked entries (Plan 00501).

Thread-safe, in memory, and written through to one file per session in the
directory the ccy supervisor watches, so a daemon restart can tell what
survives: ``session``-lifetime entries are re-stated once, ``daemon``-lifetime
entries are cleared with a one-time note. Every write happens BEFORE memory
changes, so a failed write (``OSError`` propagates) never leaves the two
disagreeing. A session with no entries left has no file.

Entries expire lazily on every read and in :meth:`SessionModeRegistry.reap`;
each expiry queues exactly one notice for :meth:`SessionModeRegistry.take_notices`.
A focus entry is renewed by a genuine human prompt, classified from the prompt
text alone (no file read).

A file that cannot be read back as a valid record is logged at WARNING and
renamed ``*.corrupt``: it is never silently treated as "no modes".
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.session_modes import (
    FOCUS_TTL_SECONDS,
    BlockReason,
    Lifetime,
    ModeLabel,
    ModeSource,
    SessionMode,
    SessionModeEntry,
    SessionPolicy,
    describe_entry,
    is_genuine_human_prompt,
)
from claude_code_hooks_daemon.utils.session_signal_paths import session_stem
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

#: Deliberately NOT ``.json``: the supervisor's sidecar reader globs that extension.
SESSION_MODES_SUFFIX: Final[str] = ".session-modes"

#: Appended to a file that could not be read back as a valid record.
CORRUPT_SUFFIX: Final[str] = ".corrupt"

SCHEMA_VERSION: Final[int] = 1

FIELD_VERSION: Final[str] = "version"
FIELD_SESSION_ID: Final[str] = "session_id"
FIELD_MODES: Final[str] = "modes"
FIELD_MODE: Final[str] = "mode"
FIELD_REASON: Final[str] = "reason"
FIELD_SOURCE: Final[str] = "source"
FIELD_LIFETIME: Final[str] = "lifetime"
FIELD_ENTERED_AT: Final[str] = "entered_at"
FIELD_EXPIRES_AT: Final[str] = "expires_at"
FIELD_DETAIL: Final[str] = "detail"

_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        FIELD_MODE,
        FIELD_REASON,
        FIELD_SOURCE,
        FIELD_LIFETIME,
        FIELD_ENTERED_AT,
        FIELD_EXPIRES_AT,
        FIELD_DETAIL,
    }
)

_SECONDS_PER_HOUR: Final[int] = 3600


class NoticeKind(StrEnum):
    """What a one-time statement to the agent reports."""

    EXPIRED = "expired"
    SURVIVED_RESTART = "survived-restart"
    CLEARED_BY_RESTART = "cleared-by-restart"


@dataclass(frozen=True, slots=True)
class ModeNotice:
    """A one-time statement about one entry, taken once by the session it belongs to."""

    kind: NoticeKind
    entry: SessionModeEntry

    def text(self) -> str:
        """The sentence stated to the agent."""
        if self.kind is NoticeKind.EXPIRED:
            if self.entry.mode is SessionMode.FOCUS:
                hours = FOCUS_TTL_SECONDS // _SECONDS_PER_HOUR
                return (
                    f"focus expired after {hours} h (task: '{self.entry.detail}'); "
                    "type `hooks-daemon focus <task>` to renew"
                )
            return f"{describe_entry(self.entry)} expired"
        if self.kind is NoticeKind.SURVIVED_RESTART:
            return f"{describe_entry(self.entry)} survived a daemon restart and still applies"
        return f"{describe_entry(self.entry)} was cleared by a daemon restart"


class _CorruptRecordError(ValueError):
    """A session-modes file that cannot be read back as a valid record."""


_Entries = dict[ModeLabel, SessionModeEntry]


class SessionModeRegistry:
    """Per-session session-mode entries, written through to one file per session.

    Args:
        state_dir: The directory holding ``<stem>.session-modes`` files.
        clock: Epoch-seconds source (injectable for tests).
    """

    def __init__(self, state_dir: Path, *, clock: Callable[[], float] = time.time) -> None:
        self._state_dir = state_dir
        self._clock = clock
        self._lock = threading.RLock()
        self._entries: dict[str, _Entries] = {}
        self._notices: dict[str, list[ModeNotice]] = {}
        self._loaded = False

    def path_for(self, session_id: str) -> Path:
        """The file holding ``session_id``'s entries."""
        return self._state_dir / f"{session_stem(session_id)}{SESSION_MODES_SUFFIX}"

    def enter(self, entry: SessionModeEntry) -> None:
        """Store ``entry``, replacing any entry with the same label for its session.

        Raises:
            ValueError: the mode is not one this registry stores.
            OSError: the write failed; memory is unchanged.
        """
        if not entry.mode.registry_owned:
            raise ValueError(f"a {entry.mode} mode is not stored by the session-modes registry")
        with self._lock:
            live, expired = self._partition(entry.session_id)
            live[entry.label] = entry
            self._commit(entry.session_id, live, expired)

    def exit(self, session_id: str, label: ModeLabel) -> SessionModeEntry | None:
        """Remove ``label`` from ``session_id``; the removed entry, or None if it was not live.

        Raises:
            OSError: the write failed; memory is unchanged.
        """
        with self._lock:
            live, expired = self._partition(session_id)
            removed = live.pop(label, None)
            if removed is not None or expired:
                self._commit(session_id, live, expired)
            return removed

    def active(self, session_id: str) -> tuple[SessionModeEntry, ...]:
        """``session_id``'s live entries in precedence order (expired ones drop out here)."""
        return self.policy(session_id).entries

    def policy(self, session_id: str) -> SessionPolicy:
        """The composed policy of ``session_id``'s live entries."""
        with self._lock:
            live = self._refresh(session_id)
        return SessionPolicy.from_entries(live.values())

    def note_prompt(self, session_id: str, prompt: object) -> bool:
        """Renew ``session_id``'s renewable entries when ``prompt`` is a genuine human prompt.

        Returns:
            Whether the prompt was genuine. Machine traffic (ticks, supervisor
            lines, notifications) renews nothing.
        """
        if not is_genuine_human_prompt(prompt):
            return False
        with self._lock:
            live, expired = self._partition(session_id)
            now = self._clock()
            renewed: _Entries = {
                label: entry.renewed(now) if entry.renewal_ttl is not None else entry
                for label, entry in live.items()
            }
            if renewed != live or expired:
                self._commit(session_id, renewed, expired)
        return True

    def reap(self) -> int:
        """Drop every expired entry across sessions; the number dropped."""
        dropped = 0
        with self._lock:
            for session_id in list(self._entries):
                live, expired = self._partition(session_id)
                if expired:
                    self._commit(session_id, live, expired)
                    dropped += len(expired)
        return dropped

    def take_notices(self, session_id: str) -> tuple[ModeNotice, ...]:
        """``session_id``'s pending one-time statements; each is returned once."""
        with self._lock:
            return tuple(self._notices.pop(session_id, []))

    def load(self) -> None:
        """Read every session file once, applying the restart rules.

        ``daemon``-lifetime entries are cleared, expired ones dropped, and
        surviving ones kept, each with one notice; the file is rewritten (or
        deleted) to match. A malformed file is logged at WARNING and renamed
        ``*.corrupt``.

        Raises:
            RuntimeError: ``load`` already ran on this registry.
            OSError: a file could not be read or rewritten.
        """
        with self._lock:
            if self._loaded:
                raise RuntimeError("SessionModeRegistry.load() runs once per registry")
            self._loaded = True
            if not self._state_dir.is_dir():
                return
            for path in sorted(self._state_dir.glob(f"*{SESSION_MODES_SUFFIX}")):
                self._load_file(path)

    def _load_file(self, path: Path) -> None:
        """Apply the restart rules to one file, or quarantine it as corrupt."""
        try:
            session_id, entries = _parse_file(path)
        except _CorruptRecordError as error:
            _quarantine(path, str(error))
            return
        now = self._clock()
        kept: _Entries = {}
        notices: list[ModeNotice] = []
        for entry in entries:
            if entry.lifetime is Lifetime.DAEMON:
                notices.append(ModeNotice(NoticeKind.CLEARED_BY_RESTART, entry))
            elif not entry.is_live(now):
                notices.append(ModeNotice(NoticeKind.EXPIRED, entry))
            else:
                notices.append(ModeNotice(NoticeKind.SURVIVED_RESTART, entry))
                kept[entry.label] = entry
        if len(kept) != len(entries):
            self._write(session_id, kept)
        self._set(session_id, kept, notices)

    def _partition(self, session_id: str) -> tuple[_Entries, list[SessionModeEntry]]:
        """A copy of ``session_id``'s live entries, and the expired ones."""
        now = self._clock()
        live: _Entries = {}
        expired: list[SessionModeEntry] = []
        for label, entry in self._entries.get(session_id, {}).items():
            if entry.is_live(now):
                live[label] = entry
            else:
                expired.append(entry)
        return live, expired

    def _refresh(self, session_id: str) -> _Entries:
        """``session_id``'s live entries, committing any expiry first."""
        live, expired = self._partition(session_id)
        if expired:
            self._commit(session_id, live, expired)
        return live

    def _commit(
        self, session_id: str, entries: _Entries, expired: Iterable[SessionModeEntry]
    ) -> None:
        """Write ``entries`` through, then adopt them and queue an expiry notice per entry."""
        self._write(session_id, entries)
        self._set(session_id, entries, [ModeNotice(NoticeKind.EXPIRED, entry) for entry in expired])

    def _set(self, session_id: str, entries: _Entries, notices: list[ModeNotice]) -> None:
        """Adopt ``entries`` in memory and queue ``notices``."""
        if entries:
            self._entries[session_id] = dict(entries)
        else:
            self._entries.pop(session_id, None)
        if notices:
            self._notices.setdefault(session_id, []).extend(notices)

    def _write(self, session_id: str, entries: Mapping[ModeLabel, SessionModeEntry]) -> None:
        """Atomically write ``entries`` to the session's file, or delete it when empty."""
        final_path = self.path_for(session_id)
        if not entries:
            final_path.unlink(missing_ok=True)
            return
        ordered = SessionPolicy.from_entries(entries.values()).entries
        payload: dict[str, object] = {
            FIELD_VERSION: SCHEMA_VERSION,
            FIELD_SESSION_ID: session_id,
            FIELD_MODES: [_record(entry) for entry in ordered],
        }
        final_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = unique_temp_path(final_path)
        try:
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            tmp_path.replace(final_path)
        except OSError:
            tmp_path.unlink(missing_ok=True)
            raise


def _record(entry: SessionModeEntry) -> dict[str, object]:
    """One entry as its file record (the session id lives once, at the top)."""
    return {
        FIELD_MODE: str(entry.mode),
        FIELD_REASON: None if entry.reason is None else str(entry.reason),
        FIELD_SOURCE: str(entry.source),
        FIELD_LIFETIME: str(entry.lifetime),
        FIELD_ENTERED_AT: entry.entered_at,
        FIELD_EXPIRES_AT: entry.expires_at,
        FIELD_DETAIL: entry.detail,
    }


def _quarantine(path: Path, reason: str) -> None:
    """Log a malformed file at WARNING and rename it ``*.corrupt`` (ERROR if that fails)."""
    corrupt = path.with_name(path.name + CORRUPT_SUFFIX)
    logger.warning("Malformed session-modes file %s (%s); renaming to %s", path, reason, corrupt)
    try:
        path.rename(corrupt)
    except OSError as error:
        logger.error("Could not rename malformed session-modes file %s: %s", path, error)


def _parse_file(path: Path) -> tuple[str, list[SessionModeEntry]]:
    """The session id and entries a file holds.

    Raises:
        _CorruptRecordError: the file is not a valid record for its own name.
        OSError: the file could not be read.
    """
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise _CorruptRecordError(f"not JSON: {error}") from error
    if not isinstance(data, dict):
        raise _CorruptRecordError("the top level is not an object")
    if data.get(FIELD_VERSION) != SCHEMA_VERSION:
        raise _CorruptRecordError(f"unsupported {FIELD_VERSION} {data.get(FIELD_VERSION)!r}")
    session_id = data.get(FIELD_SESSION_ID)
    if not isinstance(session_id, str):
        raise _CorruptRecordError(f"{FIELD_SESSION_ID} is not a string")
    if f"{session_stem(session_id)}{SESSION_MODES_SUFFIX}" != path.name:
        raise _CorruptRecordError(f"{FIELD_SESSION_ID} {session_id!r} does not match the file name")
    records = data.get(FIELD_MODES)
    if not isinstance(records, list):
        raise _CorruptRecordError(f"{FIELD_MODES} is not a list")
    entries = [_parse_record(session_id, record) for record in records]
    try:
        SessionPolicy.from_entries(entries)
    except ValueError as error:
        raise _CorruptRecordError(str(error)) from error
    return session_id, entries


def _parse_record(session_id: str, record: object) -> SessionModeEntry:
    """One file record as an entry. Raises ``_CorruptRecordError``."""
    if not isinstance(record, dict):
        raise _CorruptRecordError("a mode record is not an object")
    if set(record) != _RECORD_FIELDS:
        raise _CorruptRecordError(f"a mode record has fields {sorted(record)}")
    detail = record[FIELD_DETAIL]
    if not isinstance(detail, str):
        raise _CorruptRecordError(f"{FIELD_DETAIL} is not a string")
    raw_reason = record[FIELD_REASON]
    try:
        mode = SessionMode(record[FIELD_MODE])
        reason = None if raw_reason is None else BlockReason(raw_reason)
        source = ModeSource(record[FIELD_SOURCE])
        lifetime = Lifetime(record[FIELD_LIFETIME])
    except ValueError as error:
        raise _CorruptRecordError(str(error)) from error
    if not mode.registry_owned:
        raise _CorruptRecordError(f"a {mode} mode is not stored by the session-modes registry")
    try:
        return SessionModeEntry(
            mode=mode,
            session_id=session_id,
            entered_at=_finite(record[FIELD_ENTERED_AT], FIELD_ENTERED_AT),
            expires_at=_finite(record[FIELD_EXPIRES_AT], FIELD_EXPIRES_AT),
            source=source,
            detail=detail,
            reason=reason,
            lifetime=lifetime,
        )
    except ValueError as error:
        raise _CorruptRecordError(str(error)) from error


def _finite(value: object, name: str) -> float:
    """``value`` as a finite float (never a bool). Raises ``_CorruptRecordError``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _CorruptRecordError(f"{name} is not a number")
    number = float(value)
    if not math.isfinite(number):
        raise _CorruptRecordError(f"{name} is not finite")
    return number
