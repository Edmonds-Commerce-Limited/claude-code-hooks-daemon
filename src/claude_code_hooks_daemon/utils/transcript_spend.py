"""Cumulative spend of one agent transcript in O(new bytes) (Plan 00471 Task 2.0).

The tail reader answers "how big is this agent's context now". The ledger needs
more: every request it ever made, its compactions and its inbound messages. A
full scan per stop was 47 MB x 19 stops for the largest resumed agent, so this
module keeps an offset cache ``{path: (inode, size, offset, totals)}``: each
call parses only the bytes appended since the last one.

The entry is reset when the inode changes (the file was replaced) or the size
shrinks below the offset (it was truncated), and persisted to one small sidecar
per transcript so a daemon restart does not rescan.

**Counted per API request, not per record.** Claude Code writes one record per
content block and each carries the whole request's usage, with ``output_tokens``
growing block by block. Consecutive records of one ``requestId`` therefore
update that request's output rather than counting again, and a request id seen
earlier (a resume generation replaying history) is not counted twice.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path
from claude_code_hooks_daemon.utils.transcript_tail import (
    as_int,
    context_of,
    input_token_equivalents,
    real_assistant_usage,
)

logger = logging.getLogger(__name__)

#: A plan number in a branch, directory or agent name: ``p471``, ``plan464``,
#: ``00518``. Three to five significant digits, not glued to other letters.
_PLAN_NUMBER: Final[re.Pattern[str]] = re.compile(
    r"(?<![0-9a-z])(?:plan|p|n)?[-_]?0*([1-9][0-9]{2,4})(?![0-9])"
)

#: The wrapper Claude Code puts around a message from another agent.
_INBOUND_MARKER: Final[str] = "<teammate-message"

_STORE_DIGEST_LENGTH: Final[int] = 16


def plan_key_from(*candidates: str) -> str:
    """The first plan number found in ``candidates`` (branch, cwd, name), or ``""``."""
    for candidate in candidates:
        match = _PLAN_NUMBER.search(candidate.lower()) if candidate else None
        if match is not None:
            return match.group(1)
    return ""


@dataclass
class SpendTotals:
    """One agent's cumulative spend, as the ledger records it."""

    requests: int = 0
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    ttl_5m_write_tokens: int = 0
    ttl_1h_write_tokens: int = 0
    output_tokens: int = 0
    ite: float = 0.0
    max_ctx: int = 0
    ctx_sum: int = 0
    last_ctx: int = 0
    compactions: int = 0
    compact_pre_tokens: list[int] = field(default_factory=list)
    inbound_messages: int = 0
    plan_key: str = ""
    model_param: str = ""
    resolved_model: str = ""
    per_model_requests: dict[str, int] = field(default_factory=dict)

    @property
    def mean_ctx(self) -> int:
        """Mean context per request; zero before the first request."""
        return round(self.ctx_sum / self.requests) if self.requests else 0

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready copy, with the derived ``mean_ctx`` alongside."""
        data = asdict(self)
        data["mean_ctx"] = self.mean_ctx
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpendTotals:
        """Rebuild from :meth:`to_dict` output; a malformed field takes its default."""
        totals = cls()
        for name, default in asdict(totals).items():
            raw = data.get(name)
            if isinstance(default, bool):
                continue
            if isinstance(default, int):
                setattr(totals, name, as_int(raw))
            elif isinstance(default, float):
                setattr(
                    totals,
                    name,
                    (
                        float(raw)
                        if isinstance(raw, (int, float)) and not isinstance(raw, bool)
                        else 0.0
                    ),
                )
            elif isinstance(default, str):
                setattr(totals, name, raw if isinstance(raw, str) else "")
            elif isinstance(default, list):
                setattr(
                    totals, name, [as_int(item) for item in raw] if isinstance(raw, list) else []
                )
            elif isinstance(default, dict):
                if isinstance(raw, dict):
                    setattr(totals, name, {str(k): as_int(v) for k, v in raw.items()})
        return totals


@dataclass
class _Entry:
    """One transcript's cache entry."""

    inode: int = -1
    offset: int = 0
    totals: SpendTotals = field(default_factory=SpendTotals)
    seen_ids: set[str] = field(default_factory=set)
    last_id: str = ""
    last_output: int = 0

    def to_json(self, path: Path) -> str:
        return json.dumps(
            {
                "path": str(path),
                "inode": self.inode,
                "offset": self.offset,
                "totals": asdict(self.totals),
                "seen_ids": sorted(self.seen_ids),
                "last_id": self.last_id,
                "last_output": self.last_output,
            }
        )

    @classmethod
    def from_json(cls, text: str, path: Path) -> _Entry | None:
        try:
            data = json.loads(text)
        except ValueError:
            return None
        if not isinstance(data, dict) or data.get("path") != str(path):
            return None
        totals = data.get("totals")
        seen = data.get("seen_ids")
        last_id = data.get("last_id")
        return cls(
            inode=as_int(data.get("inode")),
            offset=as_int(data.get("offset")),
            totals=SpendTotals.from_dict(totals if isinstance(totals, dict) else {}),
            seen_ids=(
                {item for item in seen if isinstance(item, str)}
                if isinstance(seen, list)
                else set()
            ),
            last_id=last_id if isinstance(last_id, str) else "",
            last_output=as_int(data.get("last_output")),
        )


def _apply(entry: _Entry, record: dict[str, Any]) -> None:
    """Fold one transcript record into ``entry``."""
    totals = entry.totals
    if not totals.plan_key:
        branch = record.get("gitBranch")
        cwd = record.get("cwd")
        totals.plan_key = plan_key_from(
            branch if isinstance(branch, str) else "", cwd if isinstance(cwd, str) else ""
        )
    kind = record.get("type")
    if kind == "system" and record.get("subtype") == "compact_boundary":
        totals.compactions += 1
        metadata = record.get("compactMetadata")
        if isinstance(metadata, dict):
            totals.compact_pre_tokens.append(as_int(metadata.get("preTokens")))
        return
    if kind == "user":
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str) and _INBOUND_MARKER in content:
            totals.inbound_messages += 1
        return
    found = real_assistant_usage(record)
    if found is None:
        return
    message, usage = found
    request_id = record.get("requestId") or message.get("id")
    request_id = request_id if isinstance(request_id, str) else ""
    output = as_int(usage.get("output_tokens"))
    if request_id and request_id == entry.last_id:
        delta = output - entry.last_output
        if delta > 0:
            totals.output_tokens += delta
            totals.ite += 5.0 * delta
            entry.last_output = output
        return
    if request_id and request_id in entry.seen_ids:
        return
    if request_id:
        entry.seen_ids.add(request_id)
    entry.last_id = request_id
    entry.last_output = output

    context = context_of(usage)
    creation = usage.get("cache_creation")
    totals.requests += 1
    totals.input_tokens += as_int(usage.get("input_tokens"))
    totals.cache_read_tokens += as_int(usage.get("cache_read_input_tokens"))
    totals.cache_write_tokens += as_int(usage.get("cache_creation_input_tokens"))
    if isinstance(creation, dict):
        totals.ttl_5m_write_tokens += as_int(creation.get("ephemeral_5m_input_tokens"))
        totals.ttl_1h_write_tokens += as_int(creation.get("ephemeral_1h_input_tokens"))
    totals.output_tokens += output
    totals.ite += input_token_equivalents(usage)
    totals.max_ctx = max(totals.max_ctx, context)
    totals.ctx_sum += context
    totals.last_ctx = context
    model = message.get("model")
    if isinstance(model, str) and model:
        totals.resolved_model = model
        totals.per_model_requests[model] = totals.per_model_requests.get(model, 0) + 1
    requested = record.get("requestedModel")
    if not totals.model_param and isinstance(requested, str):
        totals.model_param = requested


class TranscriptSpendCache:
    """Offset-cached cumulative :class:`SpendTotals` per transcript.

    ``store_dir`` holds one sidecar per transcript; ``None`` keeps the cache in
    memory only. Thread-safe: the daemon dispatches handlers concurrently.
    """

    def __init__(self, store_dir: Path | None) -> None:
        self._store_dir = store_dir
        self._entries: dict[Path, _Entry] = {}
        self._lock = threading.Lock()

    def _store_path(self, transcript: Path) -> Path | None:
        if self._store_dir is None:
            return None
        digest = hashlib.sha256(str(transcript).encode("utf-8")).hexdigest()[:_STORE_DIGEST_LENGTH]
        return self._store_dir / f"{digest}.json"

    def _load(self, transcript: Path) -> _Entry:
        store = self._store_path(transcript)
        if store is None:
            return _Entry()
        try:
            text = store.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _Entry()
        except OSError as exc:
            log_and_continue(
                logger,
                exc,
                reason="an unreadable offset sidecar costs one rescan of its transcript, never a wrong total",
                level=logging.DEBUG,
            )
            return _Entry()
        return _Entry.from_json(text, transcript) or _Entry()

    def _save(self, transcript: Path, entry: _Entry) -> None:
        store = self._store_path(transcript)
        if store is None:
            return
        try:
            store.parent.mkdir(parents=True, exist_ok=True)
            tmp = unique_temp_path(store)
            tmp.write_text(entry.to_json(transcript), encoding="utf-8")
            tmp.replace(store)
        except OSError as exc:
            log_and_continue(
                logger,
                exc,
                reason="an unwritable offset sidecar costs a rescan after the next daemon restart, never a wrong total",
                level=logging.DEBUG,
            )

    def offset_of(self, transcript: Path) -> int:
        """The byte offset parsed so far (0 for a transcript never read)."""
        with self._lock:
            entry = self._entries.get(transcript)
            if entry is None:
                entry = self._load(transcript)
                self._entries[transcript] = entry
            return entry.offset

    def totals(self, transcript: Path) -> SpendTotals:
        """Cumulative totals of ``transcript``, parsing only the bytes appended since last time.

        Raises OSError when the transcript cannot be read; the caller decides
        what an unmeasurable agent means.
        """
        with self._lock:
            entry = self._entries.get(transcript)
            if entry is None:
                entry = self._load(transcript)
            with transcript.open("rb") as handle:
                stat = os.fstat(handle.fileno())
                if stat.st_ino != entry.inode or stat.st_size < entry.offset:
                    entry = _Entry(inode=stat.st_ino)
                handle.seek(entry.offset)
                data = handle.read(stat.st_size - entry.offset)
            complete = data.rfind(b"\n") + 1
            moved = complete > 0
            for line in data[:complete].split(b"\n"):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(record, dict):
                    _apply(entry, record)
            entry.offset += complete
            self._entries[transcript] = entry
            if moved:
                self._save(transcript, entry)
            return SpendTotals.from_dict(asdict(entry.totals))
