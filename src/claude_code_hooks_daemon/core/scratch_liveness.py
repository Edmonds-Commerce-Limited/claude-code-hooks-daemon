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
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

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
    return path == entry or entry in path.parents


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
    "BackgroundRecords",
    "LivenessInputs",
    "entry_liveness",
    "read_background_records",
]
