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
text alone (no file read); a manual-goals entry is renewed by every prompt.

A file that cannot be read back as a valid record is logged at WARNING and
renamed ``*.corrupt``: it is never silently treated as "no modes". A file that
cannot be read at all (``OSError``) is logged at ERROR and skipped, so one bad
file never stops the other sessions loading.
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

from claude_code_hooks_daemon.core.session_mode_log import (
    ModeTransition,
    TransitionAction,
    TransitionLog,
)
from claude_code_hooks_daemon.utils.blockage_marker import read_marker
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.session_modes import (
    FOCUS_TTL_SECONDS,
    BlockReason,
    Lifetime,
    ModeLabel,
    ModeSource,
    SessionMode,
    SessionModeEntry,
    SessionPolicy,
    declared_blocked_entry,
    describe_entry,
    is_genuine_human_prompt,
)
from claude_code_hooks_daemon.utils.session_signal_paths import session_stem
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path
from claude_code_hooks_daemon.utils.usage_pause import MAX_PAUSE_SPAN_SECONDS, PAUSE_GRACE_SECONDS

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

#: How long after :meth:`SessionModeRegistry.load` a first-prompt claim can
#: matter: the claim gates the one check for a usage pause recorded before the
#: load, and no such record can still be live past its longest span plus grace.
FIRST_PROMPT_WINDOW_SECONDS: Final[float] = MAX_PAUSE_SPAN_SECONDS + PAUSE_GRACE_SECONDS

#: The transition log's evidence for a mode whose expiry passed.
_EXPIRY_EVIDENCE: Final[str] = "its expiry time passed"


class NoticeKind(StrEnum):
    """What a one-time statement to the agent reports."""

    EXPIRED = "expired"
    SURVIVED_RESTART = "survived-restart"
    CLEARED_BY_RESTART = "cleared-by-restart"
    GOAL_LOOP_ENTERED = "goal-loop-entered"


@dataclass(frozen=True, slots=True)
class ModeNotice:
    """A one-time statement about one entry, taken once by the session it belongs to.

    Attributes:
        kind: What the statement reports.
        entry: The entry it is about.
        goal_cleared: For a goal-loop entry, whether the goal clear was
            signalled; None for every other kind.
    """

    kind: NoticeKind
    entry: SessionModeEntry
    goal_cleared: bool | None = None

    def _goal_loop_text(self) -> str:
        hours = (self.entry.expires_at - self.entry.entered_at) / _SECONDS_PER_HOUR
        if self.goal_cleared:
            goal = (
                " The goal is being cleared: the ccy supervisor types `/goal clear` at its "
                "next idle; without the supervisor, a human must type `/goal clear`."
            )
        else:
            goal = (
                " The daemon could not signal the goal clear (see its log), so the goal is "
                "still set: a human must type `/goal clear`."
            )
        return (
            "GOAL-LOOP BLOCKED: this session is goal-blocked by the goal-loop detector, "
            f"which saw it stop repeatedly on a goal that stayed unmet.{goal} The block ends "
            f"after {hours:g} h, at the next message the human types, on a repository "
            "change, or with `hooks-daemon session-mode unblock`."
        )

    def text(self) -> str:
        """The sentence stated to the agent."""
        if self.kind is NoticeKind.GOAL_LOOP_ENTERED:
            return self._goal_loop_text()
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

    def __init__(
        self,
        state_dir: Path,
        *,
        clock: Callable[[], float] = time.time,
        transition_log: TransitionLog | None = None,
    ) -> None:
        self._state_dir = state_dir
        self._clock = clock
        self._transition_log = transition_log
        self._lock = threading.RLock()
        self._entries: dict[str, _Entries] = {}
        self._notices: dict[str, list[ModeNotice]] = {}
        self._lines: dict[str, list[str]] = {}
        self._first_prompt_claimed: set[str] = set()
        self._loaded_at: float | None = None

    def now(self) -> float:
        """The registry's clock reading, the time its entries are judged against."""
        return self._clock()

    @property
    def transition_log(self) -> TransitionLog | None:
        """The log every enter, exit, expiry and restart clear is appended to, if any."""
        return self._transition_log

    @property
    def loaded_at(self) -> float:
        """When :meth:`load` ran: the start of this daemon process's view of the sessions.

        Raises:
            RuntimeError: ``load`` has not run.
        """
        if self._loaded_at is None:
            raise RuntimeError("SessionModeRegistry.loaded_at is unknown until load() runs")
        return self._loaded_at

    def claim_first_prompt(self, session_id: str) -> bool:
        """True exactly once per session: its first prompt since load, within the window.

        Past :data:`FIRST_PROMPT_WINDOW_SECONDS` after load nothing from before
        the load can still apply, so no session claims and :meth:`reap` drops
        every claim: the set never outlives the window.
        """
        with self._lock:
            if self._first_prompt_window_closed():
                return False
            if session_id in self._first_prompt_claimed:
                return False
            self._first_prompt_claimed.add(session_id)
            return True

    def _first_prompt_window_closed(self) -> bool:
        """Whether the first-prompt window after load has passed (False before load)."""
        if self._loaded_at is None:
            return False
        return self._clock() > self._loaded_at + FIRST_PROMPT_WINDOW_SECONDS

    def snapshot(self) -> dict[str, tuple[SessionModeEntry, ...]]:
        """Every session holding a live mode, with its entries in precedence order."""
        with self._lock:
            sessions = list(self._entries)
        snapshot: dict[str, tuple[SessionModeEntry, ...]] = {}
        for session_id in sessions:
            entries = self.active(session_id)
            if entries:
                snapshot[session_id] = entries
        return snapshot

    def path_for(self, session_id: str) -> Path:
        """The file holding ``session_id``'s entries."""
        return self._state_dir / f"{session_stem(session_id)}{SESSION_MODES_SUFFIX}"

    def enter(self, entry: SessionModeEntry, *, evidence: str | None = None) -> None:
        """Store ``entry``, replacing any entry with the same label for its session.

        Args:
            entry: The mode to enter.
            evidence: What triggered it, for the transition log; without it
                the log names the entry's source.

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
            self._record(
                entry,
                TransitionAction.ENTER,
                evidence or f"entered by the {entry.source}",
                at=self._clock(),
            )

    def exit(
        self, session_id: str, label: ModeLabel, *, evidence: str | None = None
    ) -> SessionModeEntry | None:
        """Remove ``label`` from ``session_id``; the removed entry, or None if it was not live.

        Args:
            session_id: The session.
            label: The mode to end.
            evidence: What ended it, for the transition log.

        Raises:
            OSError: the write failed; memory is unchanged.
        """
        with self._lock:
            live, expired = self._partition(session_id)
            removed = live.pop(label, None)
            if removed is not None or expired:
                self._commit(session_id, live, expired)
            if removed is not None:
                self._record(
                    removed,
                    TransitionAction.EXIT,
                    evidence or "exited (no evidence given)",
                    at=self._clock(),
                )
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
        """Renew ``session_id``'s entries that ``prompt`` renews.

        A genuine human prompt renews every renewable entry. Machine traffic
        (ticks, supervisor lines, notifications) renews only the entries any
        prompt keeps alive (``manual-goals``), never focus.

        Returns:
            Whether the prompt was genuine.
        """
        genuine = is_genuine_human_prompt(prompt)
        with self._lock:
            live, expired = self._partition(session_id)
            now = self._clock()
            renewed: _Entries = {
                label: entry.renewed(now) if entry.renewed_by(genuine=genuine) else entry
                for label, entry in live.items()
            }
            if renewed != live or expired:
                self._commit(session_id, renewed, expired)
        return genuine

    def reap(self) -> int:
        """Drop every expired entry (and spent first-prompt claims); the entries dropped."""
        dropped = 0
        with self._lock:
            if self._first_prompt_window_closed():
                self._first_prompt_claimed.clear()
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

    def queue_notice(self, notice: ModeNotice) -> None:
        """Queue ``notice`` for its entry's session, after any already pending."""
        with self._lock:
            self._notices.setdefault(notice.entry.session_id, []).append(notice)

    def queue_line(self, session_id: str, text: str) -> None:
        """Queue a one-time line that has no mode entry behind it, such as a goal-clear attribution.

        Raises:
            ValueError: ``text`` is blank.
        """
        if not text.strip():
            raise ValueError("a queued session-mode line cannot be blank")
        with self._lock:
            self._lines.setdefault(session_id, []).append(text)

    def take_lines(self, session_id: str) -> tuple[str, ...]:
        """``session_id``'s pending one-time lines; each is returned once."""
        with self._lock:
            return tuple(self._lines.pop(session_id, []))

    def load(self) -> None:
        """Read every session file once, applying the restart rules.

        ``daemon``-lifetime entries are cleared, expired ones dropped, and
        surviving ones kept, each with one notice; the file is rewritten (or
        deleted) to match. A malformed file is logged at WARNING and renamed
        ``*.corrupt``; a file that cannot be read or rewritten is logged at
        ERROR. Either way one file affects only its own session.

        Raises:
            RuntimeError: ``load`` already ran on this registry.
            OSError: the state directory itself could not be listed.
        """
        with self._lock:
            if self._loaded_at is not None:
                raise RuntimeError("SessionModeRegistry.load() runs once per registry")
            self._loaded_at = self._clock()
            if not self._state_dir.is_dir():
                return
            for path in sorted(self._state_dir.glob(f"*{SESSION_MODES_SUFFIX}")):
                self._load_file(path)

    def _load_file(self, path: Path) -> None:
        """Apply the restart rules to one file, or quarantine it as corrupt.

        A file that cannot be READ is logged at ERROR and skipped, left where
        it is (a read failure says nothing about its content): only its own
        session loads without modes, and every other file still loads.
        """
        try:
            session_id, entries = _parse_file(path)
        except OSError as error:
            log_and_continue(
                logger,
                error,
                reason=f"Unreadable session-modes file {path}; its session loads with no modes",
                level=logging.ERROR,
            )
        except _CorruptRecordError as error:
            corrupt = path.with_name(path.name + CORRUPT_SUFFIX)
            log_and_continue(
                logger,
                error,
                reason=f"Malformed session-modes file {path}; renaming to {corrupt}",
            )
            _quarantine(path, corrupt)
        else:
            self._apply_restart_rules(session_id, entries)

    def _apply_restart_rules(self, session_id: str, entries: list[SessionModeEntry]) -> None:
        """Keep a loaded file's surviving live entries, with one notice per entry.

        A failed rewrite is logged at ERROR and the loaded state is still
        adopted: the file then holds a superset of memory (the dropped entries),
        which the session's next write replaces and a later restart drops again.
        """
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
            try:
                self._write(session_id, kept)
            except OSError as error:
                log_and_continue(
                    logger,
                    error,
                    reason=(
                        f"session-modes file for {session_id} could not be rewritten after "
                        "the restart rules; memory holds the result and the next write replaces it"
                    ),
                    level=logging.ERROR,
                )
        self._set(session_id, kept, notices)
        for notice in notices:
            if notice.kind is NoticeKind.CLEARED_BY_RESTART:
                self._record(
                    notice.entry,
                    TransitionAction.RESTART_CLEAR,
                    "daemon restart (the mode lasts only as long as the daemon)",
                    at=now,
                )
            elif notice.kind is NoticeKind.EXPIRED:
                self._record(notice.entry, TransitionAction.EXPIRE, _EXPIRY_EVIDENCE, at=now)

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
        ended = list(expired)
        self._set(session_id, entries, [ModeNotice(NoticeKind.EXPIRED, entry) for entry in ended])
        now = self._clock()
        for entry in ended:
            self._record(entry, TransitionAction.EXPIRE, _EXPIRY_EVIDENCE, at=now)

    def _record(
        self, entry: SessionModeEntry, action: TransitionAction, evidence: str, *, at: float
    ) -> None:
        """Append one transition; a failed append is logged at WARNING, never raised.

        The mode change it describes is already committed, so failing it now
        would leave the caller believing nothing changed.
        """
        if self._transition_log is None:
            return
        transition = ModeTransition(
            at=at,
            session_id=entry.session_id,
            label=entry.label,
            action=action,
            evidence=evidence,
            detail=entry.detail,
        )
        try:
            self._transition_log.append([transition])
        except OSError as error:
            log_and_continue(
                logger,
                error,
                reason=f"the session-mode transition '{action} {entry.label}' could not be logged; the mode change itself stands",
            )

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


def import_legacy_blockage_marker(registry: SessionModeRegistry, marker_path: Path) -> bool:
    """Move a pre-registry awaiting-human marker into ``registry``, then delete the file.

    A live marker becomes :func:`declared_blocked_entry` entered at its
    ``recorded_at``. An expired or future-dated one is logged at INFO, a corrupt
    one at WARNING, and neither is imported. The file is deleted once judged,
    so the import happens at most once.

    Returns:
        Whether an entry was imported.

    Raises:
        OSError: the registry write or the deletion failed; a marker whose
            entry could not be written is left in place.
    """
    if not marker_path.exists():
        return False
    marker = read_marker(marker_path)
    imported = False
    if marker is None:
        logger.warning("legacy awaiting-human marker %s is unreadable; deleting it", marker_path)
    else:
        now = registry.now()
        if not marker.session_id.strip() or marker.recorded_at > now:
            logger.info("legacy awaiting-human marker %s is not valid; deleting it", marker_path)
        else:
            entry = declared_blocked_entry(marker.session_id, entered_at=marker.recorded_at)
            if entry.is_live(now):
                registry.enter(
                    entry, evidence=f"imported from the legacy awaiting-human marker {marker_path}"
                )
                imported = True
            else:
                logger.info("legacy awaiting-human marker %s has expired; deleting it", marker_path)
    marker_path.unlink(missing_ok=True)
    return imported


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


def _quarantine(path: Path, corrupt: Path) -> None:
    """Rename a malformed file to ``corrupt``; a failed rename is logged at ERROR."""
    try:
        path.rename(corrupt)
    except OSError as error:
        log_and_continue(
            logger,
            error,
            reason=f"Could not rename malformed session-modes file {path}",
            level=logging.ERROR,
        )


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
