"""Transcript block-frequency analyser (Plan 00116 Task 2b.1).

Streams a project's Claude Code session transcripts and counts hook DENY
events per blocking handler, attributed via
:mod:`claude_code_hooks_daemon.block_report.fingerprints`. The scan is
bounded and privacy-preserving in the same way as
:mod:`claude_code_hooks_daemon.tool_report.analyser`: transcripts are read
line by line, an oversized line is skipped unparsed, and only handler
NAMES, COUNTS, session ids and timestamps ever leave the scan — the deny
reason text (which may embed the blocked command) is inspected in memory
to attribute it, then discarded.

Deny-event shape (verified 2026-08-31 against this project's own real
transcripts under ``~/.claude/projects/-workspace/*.jsonl``, research for
Plan 00116 — never committed): a hook denial surfaces as a ``type: "user"``
record whose ``message.content`` is a list containing a ``tool_result``
block with ``is_error: true`` and a plain-string ``content`` holding the
handler's reason text, where the RECORD ITSELF also carries
``toolDenialKind: "permission-rule"``. That field is what distinguishes a
genuine hook deny from two look-alikes also seen in real transcripts: an
ordinary failed command (``is_error: true``, e.g. ``Error: Exit code 2``)
carries no ``toolDenialKind`` key at all, and a human declining a
permission prompt carries ``toolDenialKind: "user-rejected"`` with no
``BLOCKED`` text. Both are excluded by requiring the key equal exactly
``"permission-rule"``.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from claude_code_hooks_daemon.block_report.fingerprints import attribute_deny
from claude_code_hooks_daemon.tool_report.analyser import transcripts_root_for

logger = logging.getLogger(__name__)

__all__ = ["BlockSummary", "BlockUsage", "analyse_transcripts", "transcripts_root_for"]

# A transcript line longer than this is skipped without parsing — mirrors
# tool_report/analyser.py's MAX_LINE_BYTES: real deny records are far
# smaller, and multi-megabyte lines are file bodies this analyser has no
# business loading.
MAX_LINE_BYTES = 4_000_000

# The only toolDenialKind value that means "a hook denied this call".
_HOOK_DENY_KIND = "permission-rule"


@dataclass(frozen=True)
class BlockUsage:
    """Observed deny counts for one handler: name, counts, nothing else."""

    handler: str
    total: int
    sessions: frozenset[str]
    last_seen: str | None


@dataclass
class BlockSummary:
    """Aggregate scan result across a project's transcripts."""

    transcripts_scanned: int
    sessions_scanned: int
    malformed_lines: int
    unattributed_denies: int
    blocks: dict[str, BlockUsage] = field(default_factory=dict)


def _session_key(transcript: Path, root: Path) -> str:
    """Attribute a transcript file to its session (mirrors tool_report)."""
    relative = transcript.relative_to(root)
    if len(relative.parts) == 1:
        return transcript.stem
    return relative.parts[0]


@dataclass(frozen=True)
class _DenyEvent:
    """One raw hook-deny observation, before attribution."""

    reason: str
    timestamp: str | None


def _iter_deny_events(transcript: Path) -> tuple[list[_DenyEvent], int]:
    """Extract raw deny events from one transcript, streaming line by line.

    Returns:
        A tuple of (deny events, malformed line count). The reason text on
        each event is used only to attribute the deny and is never
        retained by the caller beyond that.
    """
    events: list[_DenyEvent] = []
    malformed = 0
    with transcript.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if len(line) > MAX_LINE_BYTES:
                continue
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(record, dict):
                continue
            if record.get("toolDenialKind") != _HOOK_DENY_KIND:
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            timestamp = record.get("timestamp")
            timestamp_str = timestamp if isinstance(timestamp, str) else None
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if not block.get("is_error"):
                    continue
                text = block.get("content")
                if isinstance(text, str) and text:
                    events.append(_DenyEvent(reason=text, timestamp=timestamp_str))
    return events, malformed


def analyse_transcripts(transcripts_root: Path) -> BlockSummary:
    """Scan every ``*.jsonl`` under ``transcripts_root`` for hook denials.

    Args:
        transcripts_root: The project's transcripts directory
            (``~/.claude/projects/<slug>``). A missing directory yields an
            empty summary — a fresh project simply has no transcripts yet.

    Returns:
        A :class:`BlockSummary` with per-handler deny counts, distinct
        session counts and last-seen timestamps.
    """
    if not transcripts_root.is_dir():
        return BlockSummary(
            transcripts_scanned=0, sessions_scanned=0, malformed_lines=0, unattributed_denies=0
        )

    totals: Counter[str] = Counter()
    sessions_using: dict[str, set[str]] = {}
    last_seen: dict[str, str] = {}
    sessions_seen: set[str] = set()
    transcripts_scanned = 0
    malformed_lines = 0
    unattributed_denies = 0

    for transcript in sorted(transcripts_root.rglob("*.jsonl")):
        session = _session_key(transcript, transcripts_root)
        sessions_seen.add(session)
        transcripts_scanned += 1
        try:
            events, file_malformed = _iter_deny_events(transcript)
        except OSError as exc:
            logger.warning("block-report: cannot read %s: %s", transcript, exc)
            continue
        malformed_lines += file_malformed
        for event in events:
            handler = attribute_deny(event.reason)
            if handler is None:
                unattributed_denies += 1
                continue
            totals[handler] += 1
            sessions_using.setdefault(handler, set()).add(session)
            if event.timestamp is not None:
                if handler not in last_seen or event.timestamp > last_seen[handler]:
                    last_seen[handler] = event.timestamp

    blocks = {
        handler: BlockUsage(
            handler=handler,
            total=total,
            sessions=frozenset(sessions_using.get(handler, set())),
            last_seen=last_seen.get(handler),
        )
        for handler, total in totals.items()
    }
    return BlockSummary(
        transcripts_scanned=transcripts_scanned,
        sessions_scanned=len(sessions_seen),
        malformed_lines=malformed_lines,
        unattributed_denies=unattributed_denies,
        blocks=blocks,
    )
