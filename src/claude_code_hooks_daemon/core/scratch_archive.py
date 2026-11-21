"""The scratch archive store (Plan 00627 Task 3.1, DESIGN.md section 5.1).

One flat directory, mode 0700, owned by the running user: archive files named
``<id>.tar``, one ``index.jsonl`` and one ``lock`` file. Every file is reached
through the store's directory descriptor with ``O_NOFOLLOW``, so a link planted
in the store is refused rather than followed. A store that is a link, is
foreign-owned or has any mode but 0700 is refused and never repaired: whoever
changed it should be asked, not overridden.

The index is append-only JSON lines, fsynced with the directory. A crash can
leave one torn final line; it is reported, its archive counts as unrecorded,
and the next append truncates it away under the lock. Any other malformed line
refuses the whole store, since a partial index cannot say what is safe.

Nothing here decides a verdict or removes an entry: the store records what the
caller proved. Its one deletion is :meth:`ArchiveStore.discard_unrecorded`, of
an archive file it created and no record names.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import secrets
import stat
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

_LOG = logging.getLogger(__name__)

#: The append-only record of every archive the store holds.
INDEX_NAME = "index.jsonl"

#: The append-only record of keeps and expiries. It is a separate file because
#: the index reader refuses the whole store on any line that is not a record.
EVENTS_NAME = "events.jsonl"

#: The file whose ``flock`` serialises every sweep that uses the store.
LOCK_NAME = "lock"

#: The suffix of every archive file.
ARCHIVE_SUFFIX = ".tar"

#: The only mode a store directory may have.
STORE_MODE = 0o700

_FILE_MODE = 0o600
_STRING_FIELDS = (
    "archive_id",
    "original_path",
    "checkout",
    "verdict",
    "packed_at",
    "sha256",
    "restore_command",
)
_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class StoreRefused(Exception):
    """The store cannot be used safely; nothing was changed."""


class StoreBusy(Exception):
    """Another sweep holds the store's lock."""


def new_archive_id() -> str:
    """Return a fresh archive id: a UTC stamp and 48 random bits, safe as a file name."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{stamp}-{secrets.token_hex(6)}"


def check_archive_id(archive_id: str) -> str:
    """Return ``archive_id`` if it has the store's shape; raise ``ValueError`` otherwise."""
    if not _ID_PATTERN.fullmatch(archive_id):
        raise ValueError(f"not an archive id: {archive_id!r}")
    return archive_id


def archive_file_name(archive_id: str) -> str:
    """Return the store-relative file name of ``archive_id``'s archive."""
    return check_archive_id(archive_id) + ARCHIVE_SUFFIX


@dataclass(frozen=True)
class ArchiveRecord:
    """One index line: what was packed, why, and how to get it back."""

    archive_id: str
    original_path: str
    checkout: str
    verdict: str
    proof_ids: tuple[str, ...]
    packed_at: str
    expires_at: str | None
    counts: Mapping[str, int]
    archive_size: int
    sha256: str
    skipped: tuple[str, ...]
    restore_command: str

    def to_json(self) -> dict[str, Any]:
        """Return the record as a JSON-ready mapping."""
        return {
            "archive_id": self.archive_id,
            "original_path": self.original_path,
            "checkout": self.checkout,
            "verdict": self.verdict,
            "proof_ids": list(self.proof_ids),
            "packed_at": self.packed_at,
            "expires_at": self.expires_at,
            "counts": dict(self.counts),
            "archive_size": self.archive_size,
            "sha256": self.sha256,
            "skipped": list(self.skipped),
            "restore_command": self.restore_command,
        }

    @classmethod
    def from_json(cls, data: object) -> ArchiveRecord:
        """Parse one index line's object; raise ``ValueError`` on any wrong shape."""
        if not isinstance(data, dict):
            raise ValueError("record is not an object")
        expected = set(cls.__dataclass_fields__)
        if set(data) != expected:
            raise ValueError(f"record keys differ: {sorted(set(data) ^ expected)}")
        for key in _STRING_FIELDS:
            if not isinstance(data[key], str):
                raise ValueError(f"{key} is not a string")
        expires = data["expires_at"]
        if expires is not None and not isinstance(expires, str):
            raise ValueError("expires_at is not a string or null")
        size = data["archive_size"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError("archive_size is not a size")
        counts = data["counts"]
        if not isinstance(counts, dict) or not all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
            for k, v in counts.items()
        ):
            raise ValueError("counts is not a mapping of names to integers")
        lists = {}
        for key in ("proof_ids", "skipped"):
            value = data[key]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"{key} is not a list of strings")
            lists[key] = tuple(value)
        return cls(
            archive_id=check_archive_id(data["archive_id"]),
            original_path=data["original_path"],
            checkout=data["checkout"],
            verdict=data["verdict"],
            proof_ids=lists["proof_ids"],
            packed_at=data["packed_at"],
            expires_at=expires,
            counts=dict(counts),
            archive_size=size,
            sha256=data["sha256"],
            skipped=lists["skipped"],
            restore_command=data["restore_command"],
        )


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant that carries a zone; raise ``ValueError`` otherwise."""
    if not value:
        raise ValueError("an instant must be a non-empty string")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"instant {value!r} has no zone")
    return parsed


def _event_strings(data: dict[str, Any], keys: tuple[str, ...]) -> dict[str, str]:
    expected = {"kind", *keys}
    if set(data) != expected:
        raise ValueError(f"event keys differ: {sorted(set(data) ^ expected)}")
    for key in keys:
        if not isinstance(data[key], str):
            raise ValueError(f"{key} is not a string")
    check_archive_id(data["archive_id"])
    return {key: data[key] for key in keys}


_KEEP_KEYS = ("archive_id", "original_path", "reason", "kept_at", "until")
_EXPIRED_KEYS = ("archive_id", "at")
_ADOPT_KEYS = ("archive_id", "original_path", "tarball", "at")
_CLAIM_KEYS = ("archive_id", "original_path", "checkout", "root_dev", "root_ino", "at")


@dataclass(frozen=True)
class KeepEvent:
    """An agent's bounded pause of one record's expiry, with its reason."""

    archive_id: str
    original_path: str
    reason: str
    kept_at: str
    until: str

    def to_json(self) -> dict[str, Any]:
        """Return the event as a JSON-ready mapping."""
        return {"kind": "keep", **{key: getattr(self, key) for key in _KEEP_KEYS}}


@dataclass(frozen=True)
class ExpiredEvent:
    """An archive the expiry pass decided to delete; written before the unlink."""

    archive_id: str
    at: str

    def to_json(self) -> dict[str, Any]:
        """Return the event as a JSON-ready mapping."""
        return {"kind": "expired", "archive_id": self.archive_id, "at": self.at}


@dataclass(frozen=True)
class AdoptEvent:
    """A tarball about to be moved into the store as ``archive_id`` (proof P6).

    Written before the move, so a crash between the move and the index append
    leaves a named, user-owned archive rather than an anonymous unrecorded one.
    """

    archive_id: str
    original_path: str
    tarball: str
    at: str

    def to_json(self) -> dict[str, Any]:
        """Return the event as a JSON-ready mapping."""
        return {"kind": "adopt", **{key: getattr(self, key) for key in _ADOPT_KEYS}}


@dataclass(frozen=True)
class ClaimEvent:
    """An entry about to be renamed to its claim name; written BEFORE the rename.

    ``root_dev``/``root_ino`` are the entry's own (a rename keeps both). A
    leftover claim name no such event covers was not made by a sweep, so a
    resume leaves it alone (D-PATH F1). ``archive_id`` is the id the pack uses.
    """

    archive_id: str
    original_path: str
    checkout: str
    root_dev: str
    root_ino: str
    at: str

    def to_json(self) -> dict[str, Any]:
        """Return the event as a JSON-ready mapping."""
        return {"kind": "claim", **{key: getattr(self, key) for key in _CLAIM_KEYS}}


ArchiveEvent = KeepEvent | ExpiredEvent | AdoptEvent | ClaimEvent


def parse_event(data: object) -> ArchiveEvent:
    """Parse one events line's object strictly; raise ``ValueError`` on any wrong shape.

    Every instant must parse with a zone, so a bad keep can never read as no keep.
    """
    if not isinstance(data, dict):
        raise ValueError("event is not an object")
    kind = data.get("kind")
    if kind == "keep":
        fields = _event_strings(data, _KEEP_KEYS)
        parse_instant(fields["kept_at"])
        parse_instant(fields["until"])
        return KeepEvent(**fields)
    if kind == "expired":
        fields = _event_strings(data, _EXPIRED_KEYS)
        parse_instant(fields["at"])
        return ExpiredEvent(**fields)
    if kind == "adopt":
        fields = _event_strings(data, _ADOPT_KEYS)
        parse_instant(fields["at"])
        return AdoptEvent(**fields)
    if kind == "claim":
        fields = _event_strings(data, _CLAIM_KEYS)
        parse_instant(fields["at"])
        if not (fields["root_dev"].isdigit() and fields["root_ino"].isdigit()):
            raise ValueError("claim root_dev/root_ino are not decimal numbers")
        return ClaimEvent(**fields)
    raise ValueError(f"unknown event kind {kind!r}")


@dataclass(frozen=True)
class EventsRead:
    """The events file as read: its complete events, and whether a torn final line was dropped."""

    events: tuple[ArchiveEvent, ...]
    torn_tail: bool


@dataclass(frozen=True)
class IndexRead:
    """The index as read: its complete records, and whether a torn final line was dropped."""

    records: tuple[ArchiveRecord, ...]
    torn_tail: bool

    def by_id(self, archive_id: str) -> ArchiveRecord | None:
        """Return the record of ``archive_id``, or ``None``."""
        for record in self.records:
            if record.archive_id == archive_id:
                return record
        return None


#: The prefix of a restore's staging directory in the store.
STAGING_PREFIX = ".restoring-"


@dataclass(frozen=True)
class StoreAudit:
    """Archives no record names, records whose archive is gone, and leftover staging."""

    unrecorded_archives: tuple[str, ...]
    records_without_archive: tuple[str, ...]
    staging_dirs: tuple[str, ...] = ()


def list_names(dir_fd: int) -> list[str]:
    """List a directory's names through a fresh descriptor of it.

    ``os.scandir`` on a descriptor shares that descriptor's stream offset, so a
    second listing through the same descriptor can come back empty. A fresh
    descriptor of ``.`` (opened ``O_NOFOLLOW`` relative to ``dir_fd``) avoids that.
    """
    fresh = os.open(".", _DIR_FLAGS, dir_fd=dir_fd)
    try:
        with os.scandir(fresh) as listing:
            return [item.name for item in listing]
    finally:
        os.close(fresh)


def fsync_dir(dir_fd: int) -> None:
    """Flush a directory's entries to disk."""
    os.fsync(dir_fd)


class ArchiveStore:
    """An open store: a directory descriptor, and the lock while it is held."""

    def __init__(self, path: Path, dir_fd: int) -> None:
        self.path = path
        self._dir_fd = dir_fd
        self._lock_fd: int | None = None

    @classmethod
    def open(cls, path: Path) -> ArchiveStore:
        """Open (creating if absent) the store at ``path``; raise :class:`StoreRefused`."""
        try:
            parent_fd = os.open(path.parent, _DIR_FLAGS)
        except OSError as exc:
            raise StoreRefused(f"store parent {path.parent} cannot be opened: {exc}") from exc
        try:
            created = False
            try:
                os.mkdir(path.name, STORE_MODE, dir_fd=parent_fd)
                created = True
            except FileExistsError as exc:
                log_and_continue(
                    _LOG,
                    exc,
                    reason="an existing store directory is the normal reopen case",
                    level=logging.DEBUG,
                )
                created = False
            except OSError as exc:
                raise StoreRefused(f"store {path} cannot be created: {exc}") from exc
            try:
                dir_fd = os.open(path.name, _DIR_FLAGS, dir_fd=parent_fd)
            except OSError as exc:
                raise StoreRefused(f"store {path} is not a plain directory: {exc}") from exc
        finally:
            os.close(parent_fd)
        try:
            info = os.fstat(dir_fd)
            if info.st_uid != os.geteuid():
                raise StoreRefused(f"store {path} is owned by uid {info.st_uid}, not this user")
            if created:
                os.fchmod(dir_fd, STORE_MODE)
                info = os.fstat(dir_fd)
            if stat.S_IMODE(info.st_mode) != STORE_MODE:
                raise StoreRefused(
                    f"store {path} has mode {stat.S_IMODE(info.st_mode):o}, not "
                    f"{STORE_MODE:o}; it is not changed, ask whoever set it"
                )
        except BaseException:
            os.close(dir_fd)
            raise
        return cls(path, dir_fd)

    @property
    def dir_fd(self) -> int:
        """The store's directory descriptor."""
        return self._dir_fd

    def close(self) -> None:
        """Release the lock if held, and close the store."""
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        if self._dir_fd >= 0:
            os.close(self._dir_fd)
            self._dir_fd = -1

    def __enter__(self) -> ArchiveStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Hold the store's exclusive ``flock``; raise :class:`StoreBusy` if another holds it."""
        fd = self._open_file(LOCK_NAME, os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise StoreBusy(f"store {self.path} is locked by another sweep") from exc
        self._lock_fd = fd
        try:
            yield
        finally:
            self._lock_fd = None
            os.close(fd)

    @property
    def locked(self) -> bool:
        """Whether this store object holds the lock."""
        return self._lock_fd is not None

    def require_lock(self, action: str) -> None:
        """Raise :class:`StoreRefused` unless the lock is held."""
        if not self.locked:
            raise StoreRefused(f"{action} needs the store lock")

    def _open_file(self, name: str, flags: int, mode: int = _FILE_MODE) -> int:
        try:
            fd = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=self._dir_fd)
        except OSError as exc:
            raise StoreRefused(f"store file {name} cannot be opened: {exc}") from exc
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise StoreRefused(f"store file {name} is not a regular file")
        return fd

    def _read_lines(self, name: str) -> tuple[list[bytes], bool]:
        """Return a JSON-lines file's complete lines and whether a torn tail was dropped."""
        try:
            fd = self._open_file(name, os.O_RDONLY)
        except StoreRefused:
            if not self._exists(name):
                return [], False
            raise
        with os.fdopen(fd, "rb") as handle:
            data = handle.read()
        lines = data.split(b"\n")
        tail = lines.pop()
        return lines, bool(tail)

    def read_index(self) -> IndexRead:
        """Read every complete record; raise :class:`StoreRefused` on an interior bad line."""
        lines, torn = self._read_lines(INDEX_NAME)
        records = []
        for number, line in enumerate(lines, start=1):
            try:
                records.append(ArchiveRecord.from_json(json.loads(line)))
            except ValueError as exc:
                raise StoreRefused(f"{INDEX_NAME} line {number} is malformed: {exc}") from exc
        return IndexRead(records=tuple(records), torn_tail=torn)

    def read_events(self) -> EventsRead:
        """Read every complete event; raise :class:`StoreRefused` on an interior bad line."""
        lines, torn = self._read_lines(EVENTS_NAME)
        events = []
        for number, line in enumerate(lines, start=1):
            try:
                events.append(parse_event(json.loads(line)))
            except ValueError as exc:
                raise StoreRefused(f"{EVENTS_NAME} line {number} is malformed: {exc}") from exc
        return EventsRead(events=tuple(events), torn_tail=torn)

    def _exists(self, name: str) -> bool:
        try:
            os.lstat(name, dir_fd=self._dir_fd)
        except FileNotFoundError:
            return False
        return True

    def append(self, record: ArchiveRecord) -> None:
        """Append ``record`` and fsync it with the directory; a torn tail is cut first."""
        self.require_lock("append")
        check_archive_id(record.archive_id)
        self._append_line(INDEX_NAME, record.to_json())

    def append_event(self, event: ArchiveEvent) -> None:
        """Append ``event`` to the events file and fsync it; a torn tail is cut first."""
        self.require_lock("append_event")
        check_archive_id(event.archive_id)
        self._append_line(EVENTS_NAME, event.to_json())

    def _append_line(self, name: str, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, sort_keys=True).encode() + b"\n"
        fd = self._open_file(name, os.O_RDWR | os.O_CREAT)
        try:
            size = os.fstat(fd).st_size
            if size:
                os.lseek(fd, 0, os.SEEK_SET)
                data = b""
                while len(data) < size:
                    chunk = os.read(fd, size - len(data))
                    if not chunk:
                        break
                    data += chunk
                keep = data.rfind(b"\n") + 1
                if keep != size:
                    os.ftruncate(fd, keep)
                    size = keep
            os.lseek(fd, size, os.SEEK_SET)
            written = 0
            while written < len(line):
                written += os.write(fd, line[written:])
            os.fsync(fd)
        finally:
            os.close(fd)
        fsync_dir(self._dir_fd)

    def create_archive(self, archive_id: str) -> int:
        """Create ``<id>.tar`` exclusively (0600) and return a write descriptor."""
        self.require_lock("create_archive")
        return self._open_file(archive_file_name(archive_id), os.O_WRONLY | os.O_CREAT | os.O_EXCL)

    def open_archive(self, archive_id: str) -> int:
        """Open ``<id>.tar`` for reading, refusing a link or a non-regular file."""
        return self._open_file(archive_file_name(archive_id), os.O_RDONLY)

    def discard_unrecorded(self, archive_id: str) -> None:
        """Remove an archive file no record names (a pack that failed before recording)."""
        self.require_lock("discard_unrecorded")
        if self.read_index().by_id(archive_id) is not None:
            raise StoreRefused(f"archive {archive_id} is recorded; it is never discarded here")
        adopted = {e.archive_id for e in self.read_events().events if isinstance(e, AdoptEvent)}
        if archive_id in adopted:
            raise StoreRefused(f"archive {archive_id} is an adopted tarball; it is never discarded")
        try:
            os.unlink(archive_file_name(archive_id), dir_fd=self._dir_fd)
        except FileNotFoundError as exc:
            log_and_continue(
                _LOG,
                exc,
                reason="an archive file that is already gone needs no discard",
                level=logging.DEBUG,
            )
        else:
            fsync_dir(self._dir_fd)

    def audit(self) -> StoreAudit:
        """Name unrecorded archive files, records whose archive is missing, and staging dirs.

        An id an ``expired`` event names is not missing: its archive was deleted on purpose.
        Every ``.restoring-`` name is listed, whether or not a reclaim would accept it.
        """
        index = self.read_index()
        expired = {e.archive_id for e in self.read_events().events if isinstance(e, ExpiredEvent)}
        recorded = {r.archive_id for r in index.records}
        present: set[str] = set()
        unrecorded: list[str] = []
        staging: list[str] = []
        for name in sorted(list_names(self._dir_fd)):
            if name.startswith(STAGING_PREFIX):
                staging.append(name)
                continue
            if not name.endswith(ARCHIVE_SUFFIX):
                continue
            archive_id = name[: -len(ARCHIVE_SUFFIX)]
            if archive_id in recorded:
                present.add(archive_id)
            else:
                unrecorded.append(name)
        missing = tuple(
            dict.fromkeys(
                r.archive_id
                for r in index.records
                if r.archive_id not in present and r.archive_id not in expired
            )
        )
        return StoreAudit(
            unrecorded_archives=tuple(unrecorded),
            records_without_archive=missing,
            staging_dirs=tuple(staging),
        )
