"""The shared spend ledger's on-disk store (Plan 00471 Task 2.1, shared with Plan 00472).

The :class:`TranscriptSpendCache` sidecars, one per transcript, live in
``<daemon untracked>/spend-offsets/``. Everything else the spend levers record
lives under ``<daemon untracked>/spend-ledger/<session>/``, a directory the
daemon's start-up cleanup removes whole once it is
``spend_ledger_retention_days`` (90) old:

- ``<session>/unmeasured/``: one marker per ``(agent_id, reason)`` a gate could
  not measure, so a fail-open is counted once and never per tool call
  (RULINGS-fable.md Q2);
- ``<session>/events.jsonl``: one row per deliberate act a lever records (a
  ``budget:`` override, a ``RESUME-LARGE:`` override, an advisory fired);
- ``<session>/state/``: per-agent and per-key counters the handlers keep;
- ``<session>/dispatches/``: one row per ``Agent``/``Task`` dispatch, keyed by
  ``tool_use_id`` (Plan 00472 T1): how its model was chosen at PreToolUse,
  joined with the ``resolvedModel`` PostToolUse reports.

The per-agent ledger rows themselves are the ``cache-sidecar`` files
``subagent_cache_aggregator`` writes at each stop.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path
from claude_code_hooks_daemon.utils.transcript_spend import TranscriptSpendCache
from claude_code_hooks_daemon.utils.transcript_tail import META_SUFFIX

logger = logging.getLogger(__name__)

#: Directory under the daemon's untracked dir, one subdirectory per session.
LEDGER_SUBDIR: Final[str] = "spend-ledger"

#: Directory under the daemon's untracked dir holding the offset-cache sidecars.
OFFSETS_SUBDIR: Final[str] = "spend-offsets"

#: The verdict-log value of a gate that allowed because it could not measure.
UNMEASURED_VERDICT: Final[str] = "unmeasured"

_UNMEASURED_SUBDIR: Final[str] = "unmeasured"
_STATE_SUBDIR: Final[str] = "state"
_DISPATCH_SUBDIR: Final[str] = "dispatches"
_EVENTS_FILE: Final[str] = "events.jsonl"
_TOOL_USE_ID: Final[str] = "tool_use_id"
#: False on a row PostToolUse created because no PreToolUse row existed (unjoined).
_PRE_RECORDED: Final[str] = "pre_recorded"
_UNSAFE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]")
_DIGEST_LENGTH: Final[int] = 16

_caches: dict[Path | None, TranscriptSpendCache] = {}
_caches_lock = threading.Lock()
_events_lock = threading.Lock()


def _safe(value: str) -> str:
    cleaned = _UNSAFE.sub("_", value).strip(".")
    return cleaned or "unknown"


def _digest(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]


def session_dir(untracked: Path, session_id: str) -> Path:
    """This session's ledger directory; the id is sanitised, never trusted as a path."""
    return untracked / LEDGER_SUBDIR / _safe(session_id)


def state_path(untracked: Path, session_id: str, kind: str, key: str) -> Path:
    """Where a handler keeps one small JSON state document for ``(kind, key)``."""
    return session_dir(untracked, session_id) / _STATE_SUBDIR / _safe(kind) / f"{_digest(key)}.json"


def read_state(path: Path) -> dict[str, Any]:
    """A state document, or ``{}`` when it is absent or unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"an unreadable state document {path} reads as empty: a lever's counters start afresh and a sidecar reading is unknown; it never blocks a call",
            level=logging.DEBUG,
        )
        return {}
    return data if isinstance(data, dict) else {}


def write_state(path: Path, data: dict[str, Any]) -> None:
    """Write a state document atomically; a failure is logged and the call proceeds."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = unique_temp_path(path)
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason="an unwritable lever state costs a repeated advisory at worst; the call proceeds",
            level=logging.WARNING,
        )


def _dispatch_row_path(untracked: Path, session_id: str, tool_use_id: str) -> Path:
    return session_dir(untracked, session_id) / _DISPATCH_SUBDIR / f"{_digest(tool_use_id)}.json"


def write_dispatch_row(
    untracked: Path, session_id: str, tool_use_id: str, fields: dict[str, Any]
) -> None:
    """Write the PreToolUse row of one dispatch, replacing any earlier one."""
    write_state(
        _dispatch_row_path(untracked, session_id, tool_use_id),
        {_TOOL_USE_ID: tool_use_id, **fields, _PRE_RECORDED: True},
    )


def merge_dispatch_row(
    untracked: Path, session_id: str, tool_use_id: str, fields: dict[str, Any]
) -> None:
    """Add ``fields`` to a dispatch's row; with no PreToolUse row it is created unjoined.

    PreToolUse and PostToolUse of one call are sequential, so the
    read-merge-write cannot race with another writer of the same row.
    """
    path = _dispatch_row_path(untracked, session_id, tool_use_id)
    row = read_state(path) or {_TOOL_USE_ID: tool_use_id, _PRE_RECORDED: False}
    write_state(path, {**row, **fields})


def read_dispatch_rows(untracked: Path, session_id: str) -> list[dict[str, Any]]:
    """Every readable dispatch row of the session, ordered by tool_use_id."""
    directory = session_dir(untracked, session_id) / _DISPATCH_SUBDIR
    try:
        paths = sorted(entry for entry in directory.iterdir() if entry.suffix == ".json")
    except FileNotFoundError:
        return []
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"an unlistable {directory} reads as no dispatch rows; only the tier report loses them",
            level=logging.WARNING,
        )
        return []
    rows = [read_state(path) for path in paths]
    return sorted(
        (row for row in rows if isinstance(row.get(_TOOL_USE_ID), str)),
        key=lambda row: str(row[_TOOL_USE_ID]),
    )


def spend_cache(untracked: Path | None) -> TranscriptSpendCache:
    """The process-wide offset cache for ``untracked`` (in memory only for ``None``)."""
    with _caches_lock:
        cache = _caches.get(untracked)
        if cache is None:
            store = untracked / OFFSETS_SUBDIR if untracked is not None else None
            cache = TranscriptSpendCache(store)
            _caches[untracked] = cache
        return cache


@dataclass(frozen=True)
class AgentMeta:
    """What Claude Code's ``agent-<id>.meta.json`` says about one agent."""

    name: str = ""
    agent_type: str = ""
    model: str = ""
    #: The dispatching call's id, the join key to its dispatch row (Plan 00472).
    tool_use_id: str = ""


def read_agent_meta(transcript: Path) -> AgentMeta:
    """The meta file beside ``transcript``; empty when absent or unreadable."""
    meta_path = transcript.with_name(transcript.name.removesuffix(".jsonl") + META_SUFFIX)
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AgentMeta()
    if not isinstance(data, dict):
        return AgentMeta()

    def text(key: str) -> str:
        value = data.get(key)
        return value if isinstance(value, str) else ""

    return AgentMeta(
        name=text("name"),
        agent_type=text("spawnedAgentType") or text("agentType"),
        model=text("model"),
        tool_use_id=text("toolUseId"),
    )


def note_unmeasured(
    untracked: Path,
    *,
    session_id: str,
    agent_id: str,
    reason: str,
    handler: str,
    tool_name: str,
    log_dir: Path,
) -> bool:
    """Record that a gate could not measure ``agent_id`` for ``reason``, once.

    Returns True when this call made the record (the first time for this
    ``(agent_id, reason)`` in the session), False when it already existed.
    The marker is created exclusively, so concurrent calls record one line.
    """
    marker = (
        session_dir(untracked, session_id)
        / _UNMEASURED_SUBDIR
        / f"{_digest(agent_id, reason)}.json"
    )
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        with marker.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps({"agent_id": agent_id, "reason": reason, "handler": handler}))
    except FileExistsError:
        return False
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason="an unwritable unmeasured marker loses the count of one fail-open; the call is allowed regardless",
            level=logging.WARNING,
        )
        return False
    from claude_code_hooks_daemon.daemon.verdict_log import append_handler_note

    try:
        append_handler_note(
            log_dir=log_dir,
            session_id=session_id,
            event="PreToolUse",
            tool_name=tool_name,
            handler=handler,
            verdict=UNMEASURED_VERDICT,
            detail={"agent_id": agent_id, "reason": reason},
        )
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason="the marker already counts this fail-open; only its verdict-log line is lost",
            level=logging.WARNING,
        )
    return True


def unmeasured_count(untracked: Path, session_id: str) -> int:
    """How many ``(agent_id, reason)`` pairs could not be measured this session."""
    directory = session_dir(untracked, session_id) / _UNMEASURED_SUBDIR
    try:
        return sum(1 for entry in directory.iterdir() if entry.suffix == ".json")
    except OSError:
        return 0


def append_event(untracked: Path, session_id: str, event: dict[str, Any]) -> None:
    """Append one ledger event row; the timestamp is added here."""
    path = session_dir(untracked, session_id) / _EVENTS_FILE
    row = {"ts": datetime.now(UTC).isoformat(), **event}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _events_lock, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason="an unwritable ledger loses one event row; the call it describes proceeds",
            level=logging.WARNING,
        )


def read_events(untracked: Path, session_id: str) -> list[dict[str, Any]]:
    """Every readable event row of the session, oldest first."""
    path = session_dir(untracked, session_id) / _EVENTS_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"an unreadable ledger {path} reads as no events; nothing gates on them",
            level=logging.WARNING,
        )
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError as exc:
            log_and_continue(
                logger,
                exc,
                reason=f"a torn or corrupt row of {path} is one lost event; the rows around it still read",
                level=logging.WARNING,
            )
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows
