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
import os
import re
import secrets
import stat
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

#: The append-only record of every archive the store holds.
INDEX_NAME = "index.jsonl"

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


@dataclass(frozen=True)
class StoreAudit:
    """Archives no record names, and records whose archive is gone."""

    unrecorded_archives: tuple[str, ...]
    records_without_archive: tuple[str, ...]


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
            except FileExistsError:
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

    def read_index(self) -> IndexRead:
        """Read every complete record; raise :class:`StoreRefused` on an interior bad line."""
        try:
            fd = self._open_file(INDEX_NAME, os.O_RDONLY)
        except StoreRefused:
            if not self._exists(INDEX_NAME):
                return IndexRead(records=(), torn_tail=False)
            raise
        with os.fdopen(fd, "rb") as handle:
            data = handle.read()
        lines = data.split(b"\n")
        tail = lines.pop()
        records = []
        for number, line in enumerate(lines, start=1):
            try:
                records.append(ArchiveRecord.from_json(json.loads(line)))
            except ValueError as exc:
                raise StoreRefused(f"{INDEX_NAME} line {number} is malformed: {exc}") from exc
        return IndexRead(records=tuple(records), torn_tail=bool(tail))

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
        line = json.dumps(record.to_json(), sort_keys=True).encode() + b"\n"
        fd = self._open_file(INDEX_NAME, os.O_RDWR | os.O_CREAT)
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
        try:
            os.unlink(archive_file_name(archive_id), dir_fd=self._dir_fd)
        except FileNotFoundError:
            return
        fsync_dir(self._dir_fd)

    def audit(self) -> StoreAudit:
        """Name unrecorded archive files and records whose archive is missing."""
        index = self.read_index()
        recorded = {r.archive_id for r in index.records}
        present: set[str] = set()
        unrecorded: list[str] = []
        for name in sorted(list_names(self._dir_fd)):
            if not name.endswith(ARCHIVE_SUFFIX):
                continue
            archive_id = name[: -len(ARCHIVE_SUFFIX)]
            if archive_id in recorded:
                present.add(archive_id)
            else:
                unrecorded.append(name)
        missing = tuple(r.archive_id for r in index.records if r.archive_id not in present)
        return StoreAudit(unrecorded_archives=tuple(unrecorded), records_without_archive=missing)
