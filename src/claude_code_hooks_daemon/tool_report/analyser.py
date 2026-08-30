"""Transcript tool-usage analyser (Plan 00293 Task 2.1).

Streams a project's Claude Code session transcripts and counts ``tool_use``
content blocks per tool name. The scan is bounded by construction: files are
read line by line, a line over the size cap is skipped unparsed, and no
transcript content — prompts, file bodies, command text — is ever retained.
Only tool NAMES and COUNTS reach the output structures.

Transcript layout (observed 2026-08-30 under ``~/.claude/projects/<slug>/``):
top-level ``<session-uuid>.jsonl`` files hold main-thread sessions, and a
``<session-uuid>/subagents/*.jsonl`` tree holds that session's subagent
transcripts. Every ``*.jsonl`` under the slug directory is scanned; a nested
file attributes its session to the top-level path component it sits under, so
subagent activity counts toward its parent session rather than inventing one.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# A transcript line longer than this is skipped without parsing. Real
# tool_use records are far smaller; multi-megabyte lines are file bodies or
# pathological content the analyser has no business loading.
MAX_LINE_BYTES = 4_000_000

# Claude Code slugs a project path into a transcripts directory name by
# replacing every non-alphanumeric character with a dash (observed:
# ``/workspace`` → ``-workspace``; a nested ``/tmp/claude-0/-workspace/...``
# scratchpad path slugs every separator the same way).
_SLUG_PATTERN = re.compile(r"[^A-Za-z0-9-]")


@dataclass(frozen=True)
class ToolUsage:
    """Observed usage of one tool: its name and counts, nothing else."""

    name: str
    calls: int
    sessions: int


@dataclass(frozen=True)
class UsageSummary:
    """Aggregate scan result across a project's transcripts."""

    transcripts_scanned: int
    sessions_scanned: int
    malformed_lines: int
    usages: dict[str, ToolUsage] = field(default_factory=dict)


def transcripts_root_for(project_root: Path, claude_home: Path | None = None) -> Path:
    """Resolve the transcripts directory for a project root.

    Args:
        project_root: Absolute project root path.
        claude_home: Override for ``~/.claude`` (tests use a tmp dir).

    Returns:
        ``<claude_home>/projects/<slug>`` for the project.
    """
    home = claude_home if claude_home is not None else Path.home() / ".claude"
    slug = _SLUG_PATTERN.sub("-", str(project_root))
    return home / "projects" / slug


def _session_key(transcript: Path, root: Path) -> str:
    """Attribute a transcript file to its session.

    A top-level ``<uuid>.jsonl`` is its own session; anything nested (the
    ``<uuid>/subagents/`` tree) belongs to the top-level component it sits
    under.
    """
    relative = transcript.relative_to(root)
    if len(relative.parts) == 1:
        return transcript.stem
    return relative.parts[0]


def _scan_lines(transcript: Path, counts: Counter[str]) -> int:
    """Count tool_use blocks in one transcript file, streaming line by line.

    Returns:
        The number of malformed (unparseable) lines encountered.
    """
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
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name")
                if isinstance(name, str) and name:
                    counts[name] += 1
    return malformed


def analyse_transcripts(transcripts_root: Path) -> UsageSummary:
    """Scan every ``*.jsonl`` under ``transcripts_root`` for tool usage.

    Args:
        transcripts_root: The project's transcripts directory
            (``~/.claude/projects/<slug>``). A missing directory yields an
            empty summary rather than an error — a fresh project simply has
            no transcripts yet.

    Returns:
        A :class:`UsageSummary` with per-tool call and session counts.
    """
    if not transcripts_root.is_dir():
        return UsageSummary(transcripts_scanned=0, sessions_scanned=0, malformed_lines=0)

    total_calls: Counter[str] = Counter()
    sessions_using: dict[str, set[str]] = {}
    sessions_seen: set[str] = set()
    transcripts_scanned = 0
    malformed_lines = 0

    for transcript in sorted(transcripts_root.rglob("*.jsonl")):
        session = _session_key(transcript, transcripts_root)
        sessions_seen.add(session)
        transcripts_scanned += 1
        file_counts: Counter[str] = Counter()
        try:
            malformed_lines += _scan_lines(transcript, file_counts)
        except OSError as exc:
            logger.warning("tool-report: cannot read %s: %s", transcript, exc)
            continue
        for name, count in file_counts.items():
            total_calls[name] += count
            sessions_using.setdefault(name, set()).add(session)

    usages = {
        name: ToolUsage(name=name, calls=calls, sessions=len(sessions_using.get(name, set())))
        for name, calls in total_calls.items()
    }
    return UsageSummary(
        transcripts_scanned=transcripts_scanned,
        sessions_scanned=len(sessions_seen),
        malformed_lines=malformed_lines,
        usages=usages,
    )
