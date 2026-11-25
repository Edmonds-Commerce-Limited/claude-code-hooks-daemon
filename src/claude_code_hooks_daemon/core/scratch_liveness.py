"""Whether something is using a scratch entry now (Plan 00627 Task 1.5, DESIGN.md section 4).

An entry is LIVE, whatever its age, when a process has its working directory
inside it, when a tracked background command names its path, or when it is
younger than ``scratch.min_age_minutes`` by its birth or its root's ctime.

Every signal fails towards LIVE. Background-process records that cannot be
read whole (an unreadable file, undecodable bytes, a line that is not a JSON
object with a string command) make every entry LIVE with that reason, because
"I could not read the records" is not "no process names this entry". A missing
records file is the one empty answer: nothing has been backgrounded.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to

logger = logging.getLogger(__name__)

_NANOSECONDS = 1_000_000_000
_SECONDS_PER_MINUTE = 60

#: The JSON key the background tracker records each command under.
COMMAND_KEY = "command"


@dataclass(frozen=True)
class BackgroundRecords:
    """The commands the background tracker recorded, or why they could not be read."""

    commands: tuple[str, ...]
    #: Non-empty when the records could not be read whole: every entry is then LIVE.
    error: str = ""


@dataclass(frozen=True)
class LivenessInputs:
    """The signals one sweep reads once and applies to every entry."""

    #: pid -> resolved working directory (``default_process_cwds``).
    cwds: Mapping[int, Path]
    background: BackgroundRecords
    min_age_minutes: int
    #: Wall clock, seconds.
    now: float
    #: pids whose working directory exists but could not be read: liveness is unknown.
    unreadable_pids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ProcessCwdReading:
    """Every readable process working directory, and the pids that could not be read."""

    cwds: Mapping[int, Path]
    unreadable: tuple[int, ...]
    #: pid -> every path it holds open by a descriptor or a memory map.
    open_paths: Mapping[int, tuple[Path, ...]] = field(default_factory=dict)


#: Where the kernel lists processes.
PROC_ROOT = Path("/proc")


def read_process_cwds(
    *, proc_root: Path = PROC_ROOT, own_pid: int | None = None
) -> ProcessCwdReading:
    """pid -> working directory from ``<proc_root>/<pid>/cwd``, naming each pid that failed.

    Unlike ``worktree_reaping.default_process_cwds``, a pid is skipped only when
    it has exited (its ``cwd`` link is gone) or is a known non-dumpable agent
    (``NON_DUMPABLE_AGENT_COMMS``) whose ``cwd`` the kernel hides; any other
    failure, permission included, is reported, because an unread process may
    be sitting in the entry. The link is read, not followed, so a deleted
    directory still reads.
    No ``proc_root`` at all (a non-Linux host) reads nothing; the sweep treats
    an empty map as liveness unknown.
    """
    if not proc_root.is_dir():
        return ProcessCwdReading({}, ())
    me = os.getpid() if own_pid is None else own_pid
    cwds: dict[int, Path] = {}
    open_paths: dict[int, tuple[Path, ...]] = {}
    unreadable: list[int] = []
    for entry in sorted(proc_root.iterdir()):
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        pid = int(entry.name)
        try:
            cwds[pid] = (entry / "cwd").readlink().resolve()
            open_paths[pid] = (*_descriptor_paths(entry), *_mapped_paths(entry))
        except (FileNotFoundError, ProcessLookupError) as exc:
            log_and_continue(
                logger,
                exc,
                reason=f"process {pid} exited between listing and reading, so it is in no entry",
                level=logging.DEBUG,
            )
            continue
        except OSError as exc:
            if _is_non_dumpable_agent(entry):
                log_and_continue(
                    logger,
                    exc,
                    reason=f"process {pid} is a non-dumpable agent whose cwd the kernel hides",
                    level=logging.DEBUG,
                )
                continue
            unreadable.append(pid)
    return ProcessCwdReading(cwds, tuple(sorted(unreadable)), open_paths)


#: Processes that mark themselves non-dumpable, so without CAP_SYS_PTRACE the
#: kernel refuses even root their ``cwd``, ``fd`` and ``maps``. They are
#: key-holding daemons that never work inside a scratch entry; one of them
#: must not leave every sweep and worktree evacuation "incomplete" for ever.
NON_DUMPABLE_AGENT_COMMS = frozenset({"ssh-agent", "gpg-agent"})


def _is_non_dumpable_agent(proc_entry: Path) -> bool:
    """True when ``<proc>/<pid>/comm`` (world-readable) names a known non-dumpable agent."""
    try:
        comm = (proc_entry / "comm").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return False
    return comm in NON_DUMPABLE_AGENT_COMMS


#: What the kernel appends to a descriptor link whose file has been unlinked.
_DELETED_SUFFIX = " (deleted)"

#: A ``maps`` line's path is its sixth field onward; earlier fields hold no space.
_MAPS_FIELDS_BEFORE_PATH = 5


def _file_path(text: str) -> Path | None:
    """The file a descriptor link or map names, or None for a socket, pipe or anonymous map."""
    if not text.startswith("/"):
        return None
    return Path(text.removesuffix(_DELETED_SUFFIX))


def _descriptor_paths(entry: Path) -> tuple[Path, ...]:
    """Every file ``<entry>/fd`` holds open.

    A table that is gone means the process exited and holds nothing; a
    descriptor closed while the table is read holds nothing either. Any other
    failure is raised: an unread table may hold a file inside an entry.
    """
    try:
        links = list((entry / "fd").iterdir())
    except FileNotFoundError as exc:
        log_and_continue(
            logger, exc, reason="a process with no fd table has exited", level=logging.DEBUG
        )
        return ()
    found: list[Path] = []
    for link in links:
        try:
            target = str(link.readlink())
        except FileNotFoundError as exc:
            log_and_continue(
                logger,
                exc,
                reason="a descriptor closed while listed holds nothing",
                level=logging.DEBUG,
            )
            continue
        path = _file_path(target)
        if path is not None:
            found.append(path)
    return tuple(found)


def _mapped_paths(entry: Path) -> tuple[Path, ...]:
    """Every file ``<entry>/maps`` maps; a missing map means the process exited."""
    try:
        text = (entry / "maps").read_text(encoding="utf-8", errors="surrogateescape")
    except FileNotFoundError as exc:
        log_and_continue(
            logger, exc, reason="a process with no memory map has exited", level=logging.DEBUG
        )
        return ()
    found: list[Path] = []
    for line in text.splitlines():
        fields = line.split(maxsplit=_MAPS_FIELDS_BEFORE_PATH)
        if len(fields) > _MAPS_FIELDS_BEFORE_PATH:
            path = _file_path(fields[_MAPS_FIELDS_BEFORE_PATH])
            if path is not None:
                found.append(path)
    return tuple(found)


def read_background_records(state_file: Path) -> BackgroundRecords:
    """Read the tracker's JSONL file; any defect is an error, never a skipped line."""
    try:
        text = state_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return BackgroundRecords(commands=())
    except (OSError, UnicodeDecodeError) as exc:
        return BackgroundRecords((), f"{state_file} could not be read: {type(exc).__name__}")
    commands: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return BackgroundRecords((), f"{state_file} line {number} is not JSON")
        if not isinstance(record, dict):
            return BackgroundRecords((), f"{state_file} line {number} is not a JSON object")
        if COMMAND_KEY not in record:
            continue
        command = record[COMMAND_KEY]
        if not isinstance(command, str):
            return BackgroundRecords((), f"{state_file} line {number} has a non-string command")
        commands.append(command)
    return BackgroundRecords(tuple(commands))


def _inside(path: Path, entry: Path) -> bool:
    return path_is_relative_to(path, entry)


def entry_liveness(
    entry: Path,
    *,
    relative: str | None,
    root_ctime_ns: int,
    birth: float | None,
    inputs: LivenessInputs,
) -> tuple[str, ...]:
    """Why entry ``entry`` is LIVE; empty when nothing shows it in use.

    ``entry`` is the resolved scratch root joined with the entry's name (the
    entry itself is never resolved: it may be a link). ``relative`` is the
    entry's path from the project root, also searched for in background
    commands, which are often typed with relative paths.
    """
    reasons: list[str] = []
    for pid, cwd in sorted(inputs.cwds.items()):
        if _inside(cwd, entry):
            reasons.append(f"process {pid} has its working directory inside the entry")
            break
    if inputs.background.error:
        reasons.append(f"background-process records could not be read ({inputs.background.error})")
    else:
        needles = [str(entry)] + ([relative] if relative else [])
        if any(needle in command for command in inputs.background.commands for needle in needles):
            reasons.append("a tracked background command names the entry")
    activity = root_ctime_ns / _NANOSECONDS
    if birth is not None:
        activity = max(activity, birth)
    if inputs.now - activity < inputs.min_age_minutes * _SECONDS_PER_MINUTE:
        reasons.append(f"younger than the minimum age of {inputs.min_age_minutes} minutes")
    return tuple(reasons)


__all__ = [
    "COMMAND_KEY",
    "NON_DUMPABLE_AGENT_COMMS",
    "PROC_ROOT",
    "BackgroundRecords",
    "LivenessInputs",
    "ProcessCwdReading",
    "entry_liveness",
    "read_background_records",
    "read_process_cwds",
]
