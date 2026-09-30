"""Is a human at the keyboard of this session right now (N274).

``AskUserQuestion`` under the declared ``unattended`` mode assumes nobody is
reading. That declaration describes the project, not the moment: the owner can
sit down at an unattended project's session and type, and the very next
question must reach them. A genuine human prompt received recently in THIS
session is that proof.

``PreToolUse`` carries no attended-versus-unattended flag, so the evidence is
the session transcript, read through the classification the skill-opportunity
scan already owns (``skill_scan.constants``): a record is a human prompt when it
is a plain-text ``user`` record, carries none of the machine-traffic content
markers (daemon cron ticks, ``ccy-supervisor`` lines, teammate messages, task
notifications) and none of the machine flags (``isMeta``, ``isSidechain``, ...).
Claude Code also stamps an explicit ``origin.kind``; when present it must be
``human``, which catches peer messages and task notifications whose text
carries no marker. A record without the field (older Claude Code) is judged by
the markers alone.

Only the tail of the transcript is read. A prompt buried under more output than
that reads as absent, which is the fail-closed direction: the project's own
declaration stands. Every unreadable or malformed input reads as "no human".
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.skill_scan.constants import (
    EXCLUDE_CONTENT_MARKERS,
    EXCLUDE_FLAGS,
    USER_RECORD_TYPE,
)
from claude_code_hooks_daemon.skill_scan.extraction import is_genuine_text

logger = logging.getLogger(__name__)

# Long enough to ride out a meeting or a lunch without the project's question
# gate flipping back mid-conversation, short enough that an owner who has
# walked away is not still treated as present for the rest of an unattended
# night. Configurable per project via the handler's ``human_presence_minutes``.
HUMAN_PRESENCE_WINDOW_SECONDS: Final[float] = 30 * 60.0

# One megabyte of tail: several hundred ordinary records, enough to reach back
# past a burst of tool output to the last prompt.
_TAIL_BYTES: Final[int] = 1024 * 1024

_TYPE_FIELD: Final[str] = "type"
_MESSAGE_FIELD: Final[str] = "message"
_CONTENT_FIELD: Final[str] = "content"
_SESSION_ID_FIELD: Final[str] = "sessionId"
_TIMESTAMP_FIELD: Final[str] = "timestamp"
_ORIGIN_FIELD: Final[str] = "origin"
_ORIGIN_KIND_FIELD: Final[str] = "kind"
_ORIGIN_HUMAN: Final[str] = "human"


def _read_tail_lines(path: Path) -> list[str]:
    """The complete lines within the last ``_TAIL_BYTES`` of ``path``, oldest first."""
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            start = max(0, size - _TAIL_BYTES)
            handle.seek(start)
            raw = handle.read()
    except OSError as exc:
        logger.debug("human_presence: cannot read transcript %s: %s", path, exc)
        return []
    lines = raw.decode("utf-8", errors="replace").splitlines()
    if start > 0 and lines:
        # The cut almost certainly landed mid-line.
        lines = lines[1:]
    return lines


def _is_human_prompt(record: dict[str, Any], session_id: str | None) -> bool:
    """Whether ``record`` is a genuine human prompt of ``session_id``."""
    if record.get(_TYPE_FIELD) != USER_RECORD_TYPE:
        return False
    if any(record.get(flag) for flag in EXCLUDE_FLAGS):
        return False
    if session_id is not None and record.get(_SESSION_ID_FIELD) != session_id:
        return False
    origin = record.get(_ORIGIN_FIELD)
    if isinstance(origin, dict) and origin.get(_ORIGIN_KIND_FIELD) != _ORIGIN_HUMAN:
        return False
    message = record.get(_MESSAGE_FIELD)
    content = message.get(_CONTENT_FIELD) if isinstance(message, dict) else None
    return isinstance(content, str) and is_genuine_text(content, EXCLUDE_CONTENT_MARKERS)


def _timestamp_seconds(record: dict[str, Any]) -> float:
    """The record's ISO timestamp as epoch seconds.

    Raises:
        ValueError: the timestamp is absent or not an ISO date-time string.
    """
    stamp = record.get(_TIMESTAMP_FIELD)
    if not isinstance(stamp, str):
        raise ValueError(f"record has no string {_TIMESTAMP_FIELD!r}: {stamp!r}")
    parsed = datetime.fromisoformat(stamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def human_prompt_within(
    transcript_path: Path, session_id: str | None, now: float, window_seconds: float
) -> bool:
    """Whether the latest genuine human prompt of this session is within the window.

    Args:
        transcript_path: The session's jsonl transcript.
        session_id: The current session; a prompt recorded for another session
            does not count. ``None`` accepts any record (the hook input named
            no session).
        now: The current wall-clock time, epoch seconds.
        window_seconds: How recent the prompt must be.

    Returns:
        True only when a genuine human prompt exists whose age is within
        ``[0, window_seconds]``. The latest genuine prompt decides; a newer
        automated prompt neither renews nor hides it. A future-dated prompt
        (clock skew, corruption) is not proof of presence.
    """
    for line in reversed(_read_tail_lines(transcript_path)):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.debug("human_presence: skipping unparseable transcript line: %s", exc)
            continue
        if not isinstance(record, dict) or not _is_human_prompt(record, session_id):
            continue
        try:
            stamped = _timestamp_seconds(record)
        except ValueError as exc:
            # The latest genuine prompt cannot be dated, so it proves nothing;
            # an older one would not speak for the present either.
            logger.debug("human_presence: undatable human prompt: %s", exc)
            return False
        return 0 <= now - stamped <= window_seconds
    return False
