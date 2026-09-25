"""Recognise Claude Code's automatic model-downgrade records in a transcript.

Anthropic's safety classifier can substitute the session model mid-session
(`fable` -> `opus`). Claude Code writes that substitution into the session
transcript as a first-class structured record, which makes it the one signal
that attributes a family change POSITIVELY to the machine — a human `/model`
emits nothing of the kind, so no inference about human intent is needed to tell
the two apart. Everything else available (a keystroke tap, a model high-water
mark, the user settings file) can only guess, and Plan 00328's reproduction
shows what that costs in the field.

Two shapes carry the same event, both observed across the 25 real records in
that plan's field scan:

- a ``fallback`` content block inside the assistant message, naming
  ``from.model`` and ``to.model`` and nothing else;
- a standalone ``model_refusal_fallback`` record 7-90s later, adding
  ``apiRefusalCategory`` and ``scope``.

They pair but not exactly, so a consumer takes whichever it sees and dedupes.
:func:`scan_transcript_tail` does the pairing: a standalone record written
right after the block for the same two models is the SAME downgrade, and keeps
the block's identity and event time.

Every record carries an identity (``record_id``): the transcript entry's own
``uuid``, or, for an entry without one, the byte offset of its line -- the
transcript is append-only, so that offset never changes. The supervisor spends
a record by this identity once the episode it opened has run its course.

This module is the single home for that recognition:
:class:`~claude_code_hooks_daemon.handlers.session_start.model_fallback_detector.ModelFallbackDetectorHandler`
reads it to build its richer per-record diagnostics, and the per-session
downgrade recorder reads it to publish the fact for the ccy supervisor.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

# ── Transcript record shapes (see the Plan 00278 field report) ──────────────
KEY_SUBTYPE: Final[str] = "subtype"
FALLBACK_SUBTYPE: Final[str] = "model_refusal_fallback"
KEY_MESSAGE: Final[str] = "message"
KEY_CONTENT: Final[str] = "content"
KEY_TYPE: Final[str] = "type"
FALLBACK_BLOCK_TYPE: Final[str] = "fallback"
KEY_ORIGINAL_MODEL: Final[str] = "originalModel"
KEY_FALLBACK_MODEL: Final[str] = "fallbackModel"
KEY_REFUSAL_CATEGORY: Final[str] = "apiRefusalCategory"
KEY_SCOPE: Final[str] = "scope"
KEY_TIMESTAMP: Final[str] = "timestamp"
KEY_UUID: Final[str] = "uuid"
KEY_FROM: Final[str] = "from"
KEY_TO: Final[str] = "to"
KEY_MODEL: Final[str] = "model"

#: Stand-in for a field the record does not carry. The block shape names no
#: refusal category or scope, and inventing one would let a consumer act on a
#: value the transcript never asserted.
UNKNOWN_MODEL: Final[str] = "unknown"

#: Cheap substring pre-filter: only lines that can possibly hold a fallback
#: record are json-parsed, so a large transcript stays a linear string scan.
PREFILTER_TOKENS: Final[tuple[str, ...]] = (FALLBACK_SUBTYPE, f'"{FALLBACK_BLOCK_TYPE}"')

# Default bounded tail window. The record only has to be seen ONCE per session
# (its own `scope` is `session`), and a downgraded session goes on emitting
# hook events, so a bounded window that occasionally misses one appearance
# still catches the next. Matching TranscriptReader.load_tail's 1 MiB keeps the
# two bounded readers in this codebase consistent.
_DEFAULT_TAIL_BYTES: Final[int] = 1_048_576

_NEWLINE: Final[bytes] = b"\n"
_FILE_START_OFFSET: Final[int] = 0

#: Identity of a record whose entry has no ``uuid``: its line's byte offset.
OFFSET_RECORD_ID_PREFIX: Final[str] = "offset:"

#: The standalone record lands 7-90s after the block in the Plan 00328 field
#: scan. Twice the observed maximum pairs every real pair while keeping a
#: genuinely NEW downgrade of the same two models (a restore, then a second
#: refusal) its own record.
PAIR_WINDOW_SECONDS: Final[float] = 180.0


@dataclass(frozen=True, slots=True)
class FallbackFacts:
    """The substance of one automatic model-downgrade record.

    Deliberately excludes the surrounding transcript text. A refusal record
    sits next to whatever provoked the refusal, and consumers of this type
    (a status fact file, a supervisor decision) need the models and the reason,
    never the content.
    """

    original_model: str
    fallback_model: str
    category: str
    scope: str
    timestamp: str
    #: The transcript entry's ``uuid``; empty when it has none, in which case
    #: :func:`scan_transcript_tail` substitutes the line's byte offset.
    record_id: str = ""


def event_epoch(timestamp: str) -> float | None:
    """The record's transcript timestamp as epoch seconds, or ``None``.

    A timestamp without a zone is UTC, which is how Claude Code writes them.
    ``None`` also covers an unparseable value: the caller (:func:`_is_pair`)
    treats a record with no readable time as not pairable, which is the
    fail-closed reading, and the parse failure is logged here so it is never
    silently indistinguishable from a genuinely empty timestamp.
    """
    if not timestamp:
        return None
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        logger.debug("model_fallback_records: unparseable timestamp %r: %s", timestamp, exc)
        parsed = None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _as_str(value: Any, default: str = UNKNOWN_MODEL) -> str:
    """Coerce a record field to a non-empty string, or ``default``."""
    if value is None:
        return default
    text = str(value)
    return text if text else default


def _fallback_block(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The first assistant-message ``fallback`` content block, if any."""
    message = payload.get(KEY_MESSAGE)
    if not isinstance(message, dict):
        return None
    content = message.get(KEY_CONTENT)
    if not isinstance(content, list):
        return None
    for block in content:
        if isinstance(block, dict) and block.get(KEY_TYPE) == FALLBACK_BLOCK_TYPE:
            return block
    return None


def block_endpoint_model(block: dict[str, Any], key: str) -> str:
    """The model name inside a fallback block's ``from``/``to`` object."""
    endpoint = block.get(key)
    if isinstance(endpoint, dict):
        return _as_str(endpoint.get(KEY_MODEL))
    return UNKNOWN_MODEL


def parse_fallback_payload(payload: dict[str, Any]) -> FallbackFacts | None:
    """Recognise either record shape in an already-parsed transcript payload.

    Returns ``None`` for every line that is not a downgrade record — which is
    almost all of them, so callers should pre-filter with
    :data:`PREFILTER_TOKENS` before paying for a JSON parse.
    """
    if payload.get(KEY_SUBTYPE) == FALLBACK_SUBTYPE:
        return FallbackFacts(
            original_model=_as_str(payload.get(KEY_ORIGINAL_MODEL)),
            fallback_model=_as_str(payload.get(KEY_FALLBACK_MODEL)),
            category=_as_str(payload.get(KEY_REFUSAL_CATEGORY)),
            scope=_as_str(payload.get(KEY_SCOPE)),
            timestamp=_as_str(payload.get(KEY_TIMESTAMP), default=""),
            record_id=_as_str(payload.get(KEY_UUID), default=""),
        )

    block = _fallback_block(payload)
    if block is None:
        return None
    return FallbackFacts(
        original_model=block_endpoint_model(block, KEY_FROM),
        fallback_model=block_endpoint_model(block, KEY_TO),
        # The block carries neither, and a guess here would be asserted
        # downstream as though the transcript had said it.
        category=UNKNOWN_MODEL,
        scope=UNKNOWN_MODEL,
        timestamp=_as_str(payload.get(KEY_TIMESTAMP), default=""),
        record_id=_as_str(payload.get(KEY_UUID), default=""),
    )


def _parse_payload_line(line: str) -> dict[str, Any] | None:
    """Parse one raw JSONL line into an object, or ``None``.

    A malformed or non-object line is simply not a record and must never cost
    the whole scan -- a transcript is appended to live, so the last line can
    be a partial write. That skip is logged rather than silent, so a genuinely
    corrupt transcript is still visible somewhere.
    """
    stripped = line.strip()
    if not stripped:
        return None
    payload: Any = None
    try:
        payload = json.loads(stripped)
    except ValueError as exc:
        logger.debug("model_fallback_records: unparseable transcript line: %s", exc)
        payload = None
    return payload if isinstance(payload, dict) else None


def parse_fallback_line(line: str) -> FallbackFacts | None:
    """Recognise either record shape in one raw JSONL line."""
    payload = _parse_payload_line(line)
    return None if payload is None else parse_fallback_payload(payload)


def _read_tail_lines(path: Path, max_bytes: int) -> list[tuple[int, str]]:
    """The whole lines in the last ``max_bytes`` of ``path``, each with its byte offset.

    Read as BYTES so each offset is exact: it is a record's identity when its
    entry has no ``uuid``, so it must come out the same on every scan whatever
    the tail window, and a text-mode seek cannot promise that.
    """
    size = path.stat().st_size
    if size <= _FILE_START_OFFSET:
        return []
    start = max(_FILE_START_OFFSET, size - max_bytes)
    with path.open("rb") as stream:
        stream.seek(start)
        chunk = stream.read()
    offset = start
    if start > _FILE_START_OFFSET:
        # A mid-file seek lands inside a record; that fragment is not a line.
        newline = chunk.find(_NEWLINE)
        if newline < 0:
            return []
        offset += newline + 1
        chunk = chunk[newline + 1 :]
    lines: list[tuple[int, str]] = []
    for raw in chunk.split(_NEWLINE):
        lines.append((offset, raw.decode("utf-8", errors="replace")))
        offset += len(raw) + len(_NEWLINE)
    return lines


def _is_pair(block: FallbackFacts, refusal: FallbackFacts) -> bool:
    """Whether ``refusal`` is the standalone record of ``block``'s downgrade.

    Same two models, written after the block and within the pairing window.
    Both times must parse: without them, nothing shows it is the same event.
    """
    if (block.original_model, block.fallback_model) != (
        refusal.original_model,
        refusal.fallback_model,
    ):
        return False
    block_time = event_epoch(block.timestamp)
    refusal_time = event_epoch(refusal.timestamp)
    if block_time is None or refusal_time is None:
        return False
    return 0.0 <= refusal_time - block_time <= PAIR_WINDOW_SECONDS


def scan_transcript_tail(
    path: Path, *, max_bytes: int = _DEFAULT_TAIL_BYTES
) -> FallbackFacts | None:
    """Return the LATEST downgrade record in the tail of ``path``, or ``None``.

    Bounded by construction: a session transcript reaches hundreds of MB, and
    this runs on a hook event, so the whole file is never parsed. The latest
    record wins because the supervisor acts on the CURRENT state of the
    session, not its history.

    Every returned record has an identity (see the module docstring), and a
    standalone record that pairs with the block right before it keeps that
    block's identity and event time, so one downgrade never looks like two.

    Never raises. A missing, unreadable or directory path is "no record" — the
    consumers are advisory, and a scan that throws would take a hook dispatch
    down with it.
    """
    try:
        lines = _read_tail_lines(path, max_bytes)
    except OSError as exc:
        logger.debug("model_fallback_records: cannot read transcript %s: %s", path, exc)
        return None

    latest: FallbackFacts | None = None
    latest_is_block = False
    for offset, line in lines:
        if not any(token in line for token in PREFILTER_TOKENS):
            continue
        payload = _parse_payload_line(line)
        if payload is None:
            continue
        facts = parse_fallback_payload(payload)
        if facts is None:
            continue
        if not facts.record_id:
            facts = replace(facts, record_id=f"{OFFSET_RECORD_ID_PREFIX}{offset}")
        is_block = payload.get(KEY_SUBTYPE) != FALLBACK_SUBTYPE
        if not is_block and latest is not None and latest_is_block and _is_pair(latest, facts):
            facts = replace(facts, record_id=latest.record_id, timestamp=latest.timestamp)
        latest = facts
        latest_is_block = is_block
    return latest
