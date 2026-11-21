"""The per-session scratch directory and its manifest (Plan 00627 Tasks 4.1, 4.2).

DESIGN.md section 7: each session works in ``<scratch root>/s-<UTC>-<sid8>/``,
created by the daemon at SessionStart and holding ``.scratch-session.json``: the
session id, birth time, checkout, branch and an ``entries`` map that
``hooks-daemon scratch new`` fills. Owner and birth therefore come from the
daemon, not from the agent and not from mtime.

Everything here treats the scratch tree as agent-writable and so untrusted: the
session id (``CLAUDE_CODE_SESSION_ID`` can be set by anyone) is validated before
any path is built from it, directories are matched by a full regex over a
listing (never a glob with the id interpolated), no link is followed, a manifest
is read as a small regular file and anything that does not validate is "not a
session directory". A manifest is never rewritten by creation; entry updates are
serialised by an ``flock`` on the session directory and land by rename.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.utils.bounded_walk import Bounded, finished, stopped

MANIFEST_NAME = ".scratch-session.json"
SCHEMA_VERSION = 1
SESSION_PREFIX = "s-"

_SHORT_ID_LENGTH = 8
_SESSION_ID = re.compile(r"[A-Za-z0-9]{8}[A-Za-z0-9_-]{0,120}")
_DIR_NAME = re.compile(r"s-[0-9]{8}T[0-9]{6}Z-([A-Za-z0-9]{8})")
#: The reference search's class (DESIGN.md section 3.4), no leading ``.`` or ``-``:
#: rules out the manifest, ``.scratch-keep``, ``.sweeping-*`` and option-like names.
_ENTRY_NAME = re.compile(r"[A-Za-z0-9_+@~][A-Za-z0-9._+@~-]{0,99}")
_PLAN = re.compile(r"[0-9]{3,5}")
_STAMP = "%Y%m%dT%H%M%SZ"
_MAX_MANIFEST_BYTES = 1_048_576
_MAX_PURPOSE_CHARS = 500
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_MODE = 0o600
_DIR_MODE = 0o700


class SessionError(Exception):
    """A session directory or entry could not be made or read; the message says why."""


@dataclass(frozen=True)
class EntryRecord:
    """One entry's record in the manifest."""

    born: float
    purpose: str | None
    plan: str | None
    ttl_hours: int | None


@dataclass(frozen=True)
class Manifest:
    """A validated ``.scratch-session.json``."""

    session_id: str
    born: float
    checkout: str
    branch: str | None
    entries: dict[str, EntryRecord]


@dataclass(frozen=True)
class ManifestReading:
    """A manifest, or why there is none; ``problem`` is empty exactly when it was read."""

    manifest: Manifest | None
    problem: str


@dataclass(frozen=True)
class SessionDir:
    """Where the session directory is, and whether this call made it."""

    path: Path
    created: bool


def check_session_id(session_id: str) -> str:
    """The id's first 8 characters; raises SessionError for an id outside the strict charset."""
    if _SESSION_ID.fullmatch(session_id) is None:
        raise SessionError("the session id is missing or holds characters outside [A-Za-z0-9_-]")
    return session_id[:_SHORT_ID_LENGTH]


def session_dir_name(session_id: str, born: datetime) -> str:
    """``s-YYYYMMDDTHHMMSSZ-<sid8>`` for a validated id and a UTC birth."""
    return f"{SESSION_PREFIX}{born.astimezone(UTC).strftime(_STAMP)}-{check_session_id(session_id)}"


def is_session_dir_name(name: str) -> bool:
    """True when ``name`` has the session directory shape."""
    return _DIR_NAME.fullmatch(name) is not None


def check_entry_name(name: str) -> str:
    """``name`` if it is one safe path segment; raises SessionError otherwise."""
    if _ENTRY_NAME.fullmatch(name) is None or name in (".", ".."):
        raise SessionError(
            f"entry name {name!r} must be one segment of [A-Za-z0-9._+@~-], "
            "at most 100 characters, not starting with '.' or '-'"
        )
    return name


def bounded_ttl_hours(
    requested: int | None, *, max_ttl_hours: int, root_ttl_hours: int
) -> int | None:
    """``requested`` if within ``max(max_ttl_hours, root_ttl_hours)`` (DESIGN.md section 4)."""
    if requested is None:
        return None
    bound = max(max_ttl_hours, root_ttl_hours)
    if requested < 1 or requested > bound:
        raise SessionError(f"--ttl-hours must be between 1 and {bound} (scratch.max_ttl_hours)")
    return requested


def _instant(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_instant(value: object, field: str) -> float:
    """``value`` as a UTC instant; raises ValueError naming ``field`` when it is not one."""
    if not isinstance(value, str):
        raise ValueError(f"{field} is not a timestamp string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{field} {value!r} is not a YYYY-MM-DDTHH:MM:SSZ instant") from exc
    return parsed.replace(tzinfo=UTC).timestamp()


def _optional_str(value: object, field: str) -> str | None:
    """``value`` when it is a string or None; raises ValueError naming ``field`` otherwise."""
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"{field} is neither a string nor null")


def _entry_record(name: str, value: object) -> EntryRecord:
    """The record of entry ``name``; raises ValueError naming the entry and field."""
    field = f"entries[{name!r}]"
    if not isinstance(value, dict):
        raise ValueError(f"{field} is not an object")
    born = _parse_instant(value.get("born"), f"{field}.born")
    purpose = _optional_str(value.get("purpose"), f"{field}.purpose")
    plan = _optional_str(value.get("plan"), f"{field}.plan")
    ttl = value.get("ttl_hours")
    if not (ttl is None or (isinstance(ttl, int) and not isinstance(ttl, bool) and ttl >= 1)):
        raise ValueError(f"{field}.ttl_hours is not a positive integer or null")
    if plan is not None and _PLAN.fullmatch(plan) is None:
        raise ValueError(f"{field}.plan is not a plan number")
    return EntryRecord(born, purpose, plan, ttl if isinstance(ttl, int) else None)


def parse_manifest(data: object) -> Manifest:
    """A Manifest from decoded JSON; raises ValueError naming the first field that does not validate."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        raise ValueError(f"not a schema {SCHEMA_VERSION} manifest object")
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or _SESSION_ID.fullmatch(session_id) is None:
        raise ValueError("session_id is missing or outside [A-Za-z0-9_-]")
    born = _parse_instant(data.get("born"), "born")
    checkout = data.get("checkout")
    if not isinstance(checkout, str):
        raise ValueError("checkout is not a string")
    branch = _optional_str(data.get("branch"), "branch")
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, dict):
        raise ValueError("entries is not an object")
    entries: dict[str, EntryRecord] = {}
    for name, value in raw_entries.items():
        if not isinstance(name, str) or _ENTRY_NAME.fullmatch(name) is None:
            raise ValueError(f"entry name {name!r} is not a safe path segment")
        entries[name] = _entry_record(name, value)
    return Manifest(session_id, born, checkout, branch, entries)


def _manifest_json(manifest: Manifest) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "session_id": manifest.session_id,
        "born": _instant(manifest.born),
        "checkout": manifest.checkout,
        "branch": manifest.branch,
        "entries": {
            name: {
                "born": _instant(record.born),
                "purpose": record.purpose,
                "plan": record.plan,
                "ttl_hours": record.ttl_hours,
            }
            for name, record in sorted(manifest.entries.items())
        },
    }


def _manifest_problem(exc: Exception) -> ManifestReading:
    return ManifestReading(None, f"{type(exc).__name__}: {exc}")


def _read_manifest_at(dir_fd: int) -> ManifestReading:
    try:
        fd = os.open(MANIFEST_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
    except OSError as exc:
        return _manifest_problem(exc)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return ManifestReading(None, "the manifest is not a regular file")
        if info.st_size > _MAX_MANIFEST_BYTES:
            return ManifestReading(None, f"the manifest is over {_MAX_MANIFEST_BYTES} bytes")
        raw = os.read(fd, _MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        return _manifest_problem(exc)
    finally:
        os.close(fd)
    try:
        return ManifestReading(parse_manifest(json.loads(raw.decode("utf-8"))), "")
    except (UnicodeDecodeError, ValueError) as exc:
        return _manifest_problem(exc)


def read_manifest_reading(session_dir: Path) -> ManifestReading:
    """The validated manifest of ``session_dir``, or why there is none (absent, a link, unreadable, invalid)."""
    try:
        dir_fd = os.open(session_dir, _DIR_FLAGS)
    except OSError as exc:
        return _manifest_problem(exc)
    try:
        return _read_manifest_at(dir_fd)
    finally:
        os.close(dir_fd)


def read_manifest(session_dir: Path) -> Manifest | None:
    """The validated manifest of ``session_dir``, or None; :func:`read_manifest_reading` says why."""
    return read_manifest_reading(session_dir).manifest


def _list_session_names(root: Path) -> Bounded[tuple[str, ...]]:
    """Every real directory name in ``root``, newest-named first; a listing failure is carried."""
    try:
        with os.scandir(root) as listing:
            names = sorted(
                (item.name for item in listing if item.is_dir(follow_symlinks=False)),
                reverse=True,
            )
    except OSError as exc:
        return stopped((), f"{root} could not be listed: {type(exc).__name__}")
    return finished(tuple(names))


def find_session_dir(root: Path, session_id: str) -> Path | None:
    """The newest directory in ``root`` named for ``session_id`` whose manifest carries that id.

    None when there is none, including when ``root`` is absent or cannot be
    listed: the callers then make a directory, or report that nothing was found.
    """
    short = check_session_id(session_id)
    for name in _list_session_names(root).value:
        match = _DIR_NAME.fullmatch(name)
        if match is None or match.group(1) != short:
            continue
        manifest = read_manifest(root / name)
        if manifest is not None and manifest.session_id == session_id:
            return root / name
    return None


def _write_new_file(dir_fd: int, name: str, payload: bytes) -> None:
    """Write ``payload`` to ``name`` in ``dir_fd``; raises FileExistsError rather than replace it."""
    temp = f".{name}.tmp-{secrets.token_hex(6)}"
    fd = os.open(
        temp,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        _FILE_MODE,
        dir_fd=dir_fd,
    )
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(temp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    finally:
        os.unlink(temp, dir_fd=dir_fd)


def _replace_file(dir_fd: int, name: str, payload: bytes) -> None:
    temp = f".{name}.tmp-{secrets.token_hex(6)}"
    fd = os.open(
        temp,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        _FILE_MODE,
        dir_fd=dir_fd,
    )
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)


def _encode(manifest: Manifest) -> bytes:
    return (json.dumps(_manifest_json(manifest), indent=2) + "\n").encode("utf-8")


def ensure_session_dir(
    root: Path,
    session_id: str,
    *,
    now: datetime,
    checkout: str,
    branch: str | None,
    name: str | None = None,
) -> SessionDir:
    """Find or create this session's directory in ``root``; idempotent per session id.

    ``name`` mirrors a directory already made elsewhere (a sub-agent's checkout
    reuses its parent session's name); it must carry this session's short id.
    An existing manifest is never rewritten. Raises SessionError on any failure.
    """
    short = check_session_id(session_id)
    found = find_session_dir(root, session_id)
    if found is not None:
        return SessionDir(found, False)
    if name is None:
        name = session_dir_name(session_id, now)
    match = _DIR_NAME.fullmatch(name)
    if match is None or match.group(1) != short:
        raise SessionError(f"{name!r} is not a session directory name for this session")
    path = root / name
    try:
        root.mkdir(parents=True, exist_ok=True)
        path.mkdir(mode=_DIR_MODE)
    except FileExistsError as exc:
        raise SessionError(f"{path} already exists and is not this session's directory") from exc
    except OSError as exc:
        raise SessionError(f"could not create {path}: {type(exc).__name__}") from exc
    manifest = Manifest(session_id, now.timestamp(), checkout, branch, {})
    try:
        dir_fd = os.open(path, _DIR_FLAGS)
        try:
            _write_new_file(dir_fd, MANIFEST_NAME, _encode(manifest))
        finally:
            os.close(dir_fd)
    except OSError as exc:
        raise SessionError(f"could not write {path / MANIFEST_NAME}: {type(exc).__name__}") from exc
    return SessionDir(path, True)


def resolve_session_dir(
    own_root: Path,
    main_root: Path,
    session_id: str,
    *,
    now: datetime,
    checkout: str,
    branch: str | None,
) -> Path:
    """This checkout's session directory: its own, else a mirror of the main checkout's name, else new."""
    own = find_session_dir(own_root, session_id)
    if own is not None:
        return own
    parent = find_session_dir(main_root, session_id) if main_root != own_root else None
    name = parent.name if parent is not None else None
    return ensure_session_dir(
        own_root, session_id, now=now, checkout=checkout, branch=branch, name=name
    ).path


@contextmanager
def _locked(session_dir: Path) -> Iterator[int]:
    try:
        dir_fd = os.open(session_dir, _DIR_FLAGS)
    except OSError as exc:
        raise SessionError(f"could not open {session_dir}: {type(exc).__name__}") from exc
    try:
        fcntl.flock(dir_fd, fcntl.LOCK_EX)
        yield dir_fd
    finally:
        os.close(dir_fd)


def new_entry(
    session_dir: Path,
    name: str,
    *,
    now: datetime,
    purpose: str | None,
    plan: str | None,
    ttl_hours: int | None,
) -> Path:
    """Create ``session_dir/name`` and record its birth, purpose, plan and TTL.

    The TTL must already be bounded (:func:`bounded_ttl_hours`). An entry that
    exists, recorded or not, is refused, so a recorded birth is never rewritten.
    """
    check_entry_name(name)
    if plan is not None and _PLAN.fullmatch(plan) is None:
        raise SessionError(f"--plan {plan!r} must be a plan number (3 to 5 digits)")
    if purpose is not None:
        purpose = purpose[:_MAX_PURPOSE_CHARS]
    with _locked(session_dir) as dir_fd:
        reading = _read_manifest_at(dir_fd)
        manifest = reading.manifest
        if manifest is None:
            raise SessionError(
                f"{session_dir / MANIFEST_NAME}: the manifest is missing or invalid "
                f"({reading.problem})"
            )
        if name in manifest.entries:
            raise SessionError(f"entry {name!r} already exists in {session_dir}")
        try:
            os.mkdir(name, _DIR_MODE, dir_fd=dir_fd)
        except FileExistsError as exc:
            raise SessionError(f"{session_dir / name} already exists") from exc
        except OSError as exc:
            raise SessionError(
                f"could not create {session_dir / name}: {type(exc).__name__}"
            ) from exc
        entries = {**manifest.entries, name: EntryRecord(now.timestamp(), purpose, plan, ttl_hours)}
        updated = Manifest(
            manifest.session_id, manifest.born, manifest.checkout, manifest.branch, entries
        )
        try:
            _replace_file(dir_fd, MANIFEST_NAME, _encode(updated))
        except OSError as exc:
            os.rmdir(name, dir_fd=dir_fd)
            raise SessionError(f"could not record {name!r}: {type(exc).__name__}") from exc
    return session_dir / name


def remove_empty_session_dir(
    root_fd: int, name: str, *, born_before: float, held: Callable[[], bool]
) -> str:
    """Remove the session directory ``name`` under ``root_fd`` when it is empty and old.

    Returns "" when removed, else why it stays. Empty means the manifest is its
    only file; old means the session and every child the manifest records were
    born before ``born_before``. ``held()`` (asked under the lock, last) keeps
    it, e.g. while an archive record still names a path inside it. Taken under
    the same ``flock`` as :func:`new_entry`; the manifest is unlinked first and
    rewritten when the ``rmdir`` fails, so a directory is never left without one.
    """
    if not is_session_dir_name(name):
        return "not a session directory name"
    try:
        dir_fd = os.open(name, _DIR_FLAGS, dir_fd=root_fd)
    except OSError as exc:
        return f"could not open: {type(exc).__name__}"
    try:
        fcntl.flock(dir_fd, fcntl.LOCK_EX)
        return _remove_locked(root_fd, name, dir_fd, born_before, held)
    finally:
        os.close(dir_fd)


def _remove_locked(
    root_fd: int, name: str, dir_fd: int, born_before: float, held: Callable[[], bool]
) -> str:
    reading = _read_manifest_at(dir_fd)
    manifest = reading.manifest
    if manifest is None:
        return f"the manifest is missing or invalid ({reading.problem})"
    births = [manifest.born, *(record.born for record in manifest.entries.values())]
    if max(births) >= born_before:
        return "a recent session or child birth"
    if os.listdir(dir_fd) != [MANIFEST_NAME]:
        return "not empty"
    if held():
        return "held: something still names a path inside it"
    opened = os.fstat(dir_fd)
    try:
        named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except OSError as exc:
        return f"the name could not be read again: {type(exc).__name__}"
    if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
        return "the name no longer holds the directory that was checked"
    os.unlink(MANIFEST_NAME, dir_fd=dir_fd)
    try:
        os.rmdir(name, dir_fd=root_fd)
    except OSError as exc:
        _replace_file(dir_fd, MANIFEST_NAME, _encode(manifest))
        return f"not removed ({type(exc).__name__}): manifest rewritten"
    return ""
