"""Read an agent's current context from the END of its transcript (Plan 00471 Task 2.0).

A gate that runs on every tool call cannot scan a 50 MB transcript: measured on
the 48.9 MB ``plan464-impl`` file a full scan costs 58 ms, against 59 µs for a
tail read. So this module seeks to EOF minus a window, scans the lines it holds
backwards for the last real assistant ``usage``, and doubles the window only on
a miss. The largest line measured is 264 KB, so the worst case is a few
doublings, and the number of reads does not grow with the file.

**Current context** is ``input + cache_read + cache_creation`` of the last real
request. ``<synthetic>`` records carry zero usage and are skipped: the very last
assistant record of a measured transcript was one.

**Stopped** means the last conversational record (``user`` or ``assistant``,
synthetic ones aside) is an assistant turn ending ``end_turn``. A later user
record is an inbound message or a tool result, and the agent is running again.

The resolver accepts both shapes a subagent's ``transcript_path`` may take
(Plan 00471 RULINGS-fable.md Q5): the agent's own file, or the main session's
transcript, from which the agent's file is derived.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Final

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

#: The first window read back from EOF; doubled on every miss.
INITIAL_WINDOW_BYTES: Final[int] = 64 * 1024

#: The model name Claude Code writes on records that are not API responses.
SYNTHETIC_MODEL: Final[str] = "<synthetic>"

#: The sidecar Claude Code writes beside each ``agent-<id>.jsonl``.
META_SUFFIX: Final[str] = ".meta.json"

#: The stop reason of a finished turn.
END_TURN: Final[str] = "end_turn"

#: An agent id is used as a path segment, so anything else is refused.
_SAFE_AGENT_ID: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9._-]+")

#: Price ratios to plain input (API list prices; the subscription weights are
#: unpublished, so this is a proxy whose percentages are what matter).
_WEIGHT_INPUT: Final[float] = 1.0
_WEIGHT_WRITE_5M: Final[float] = 1.25
_WEIGHT_WRITE_1H: Final[float] = 2.0
_WEIGHT_READ: Final[float] = 0.1
_WEIGHT_OUTPUT: Final[float] = 5.0


@dataclass(frozen=True)
class TailReading:
    """What the end of one transcript says about its agent."""

    context_tokens: int
    model: str
    stopped: bool


def as_int(raw: object) -> int:
    """A token count as an int; anything that is not a number counts as zero."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0
    return int(raw)


def context_of(usage: Mapping[str, Any]) -> int:
    """The context size one request carried: input plus both cache fields."""
    return (
        as_int(usage.get("input_tokens"))
        + as_int(usage.get("cache_read_input_tokens"))
        + as_int(usage.get("cache_creation_input_tokens"))
    )


def input_token_equivalents(usage: Mapping[str, Any]) -> float:
    """One request's cost in input-token equivalents (ite).

    Weights: input 1, 5-minute cache write 1.25, 1-hour cache write 2, cache
    read 0.1, output 5. A write with no TTL split counts as 5-minute.
    """
    writes = as_int(usage.get("cache_creation_input_tokens"))
    creation = usage.get("cache_creation")
    writes_1h = (
        as_int(creation.get("ephemeral_1h_input_tokens")) if isinstance(creation, dict) else 0
    )
    writes_1h = min(writes_1h, writes)
    return (
        _WEIGHT_INPUT * as_int(usage.get("input_tokens"))
        + _WEIGHT_WRITE_5M * (writes - writes_1h)
        + _WEIGHT_WRITE_1H * writes_1h
        + _WEIGHT_READ * as_int(usage.get("cache_read_input_tokens"))
        + _WEIGHT_OUTPUT * as_int(usage.get("output_tokens"))
    )


def real_assistant_usage(
    record: Mapping[str, Any],
) -> tuple[Mapping[str, Any], dict[str, Any]] | None:
    """``(message, usage)`` of a real (non-synthetic) assistant record, else None."""
    if record.get("type") != "assistant":
        return None
    message = record.get("message")
    if not isinstance(message, dict) or message.get("model") == SYNTHETIC_MODEL:
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    return message, usage


def _is_conversational(record: Mapping[str, Any]) -> bool:
    """A user or real assistant record: the ones that say whether a turn is open."""
    kind = record.get("type")
    if kind == "user":
        return True
    if kind != "assistant":
        return False
    message = record.get("message")
    return isinstance(message, dict) and message.get("model") != SYNTHETIC_MODEL


def _scan_backwards(lines: Iterable[bytes]) -> tuple[TailReading | None, bool]:
    """Scan ``lines`` newest first. Returns the reading and whether it is complete."""
    stopped: bool | None = None
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="a line that is not a transcript record carries no usage, so the scan reads the line before it",
                level=logging.DEBUG,
            )
            continue
        if not isinstance(record, dict):
            continue
        if stopped is None and _is_conversational(record):
            message = record.get("message")
            stopped = (
                record.get("type") == "assistant"
                and isinstance(message, dict)
                and message.get("stop_reason") == END_TURN
            )
        found = real_assistant_usage(record)
        if found is not None:
            message, usage = found
            model = message.get("model")
            return (
                TailReading(
                    context_tokens=context_of(usage),
                    model=model if isinstance(model, str) else "",
                    stopped=bool(stopped),
                ),
                True,
            )
    return None, False


def _open_binary(path: Path) -> IO[bytes]:
    return path.open("rb")


def read_tail(
    path: Path,
    *,
    initial_window: int = INITIAL_WINDOW_BYTES,
    opener: Callable[[Path], IO[bytes]] = _open_binary,
) -> TailReading | None:
    """The last real request's context, model and stopped state of ``path``.

    Returns None when the whole file holds no real assistant usage (a fresh
    agent). Raises OSError when the file cannot be opened or read: the caller
    decides what an unmeasurable transcript means.
    """
    with opener(path) as handle:
        size = handle.seek(0, 2)
        window = max(1, initial_window)
        while True:
            start = max(0, size - window)
            handle.seek(start)
            data = handle.read(size - start)
            lines = data.split(b"\n")
            if start > 0:
                # The first piece may be the tail of a line cut by the window.
                lines = lines[1:]
            reading, complete = _scan_backwards(reversed(lines))
            if complete or start == 0:
                return reading
            window *= 2


def subagents_dir(transcript_path: str, session_id: str) -> Path | None:
    """The directory holding a session's ``agent-*.jsonl`` transcripts.

    ``transcript_path`` is either an agent's own file (already inside it) or
    the main session's ``<dir>/<session>.jsonl`` (its sibling directory).
    """
    if not transcript_path:
        return None
    path = Path(transcript_path)
    if path.parent.name == "subagents":
        return path.parent
    if not session_id:
        return None
    return path.parent / session_id / "subagents"


def agent_name_of(transcript: Path) -> str:
    """The ``name`` in the agent's ``meta.json``, or ``""``."""
    meta = transcript.with_name(transcript.name.removesuffix(".jsonl") + META_SUFFIX)
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    name = data.get("name") if isinstance(data, dict) else None
    return name if isinstance(name, str) else ""


def find_agent_transcript(directory: Path, target: str) -> Path | None:
    """The transcript a SendMessage ``to`` names: a raw agent id, or a teammate name.

    A name resolves to the newest ``agent-a<name>-*.jsonl`` whose ``meta.json``
    confirms the name, so an older generation of the same name is never judged
    in place of the live one. None when nothing matches (a cross-session peer).

    Raises OSError when ``directory`` or a candidate cannot be read: the
    caller decides what an unmeasurable target means. A missing directory is
    a session with no agents and matches nothing.
    """
    if not _SAFE_AGENT_ID.fullmatch(target or ""):
        return None
    direct = directory / f"agent-{target}.jsonl"
    if direct.is_file():
        return direct
    if not directory.is_dir():
        return None
    prefix = f"agent-a{target}-"
    with os.scandir(directory) as entries:
        candidates = [
            Path(entry.path)
            for entry in entries
            if entry.name.startswith(prefix) and entry.name.endswith(".jsonl")
        ]
    confirmed = [path for path in candidates if agent_name_of(path) == target]
    return max(confirmed, key=lambda path: path.stat().st_mtime, default=None)


def resolve_agent_transcript(transcript_path: str, session_id: str, agent_id: str) -> Path | None:
    """The transcript of the agent ``agent_id``, or None when it cannot be found.

    Its basename is ``agent-<agent_id>.jsonl`` when the hook carried the
    agent's own path; otherwise the path is derived from the main transcript
    (``<dir>/<session_id>/subagents/agent-<agent_id>.jsonl``).
    """
    if not transcript_path or not _SAFE_AGENT_ID.fullmatch(agent_id or ""):
        return None
    name = f"agent-{agent_id}.jsonl"
    given = Path(transcript_path)
    if given.name == name:
        return given if given.is_file() else None
    directory = subagents_dir(transcript_path, session_id)
    if directory is None:
        return None
    candidate = directory / name
    return candidate if candidate.is_file() else None
