"""Stage 1: deterministic extraction of genuine human prompts (Plan 00274).

Reads Claude Code session transcripts (``~/.claude/projects/<slug>/*.jsonl``)
and applies the two-layer noise filter verified in BRAINSTORM.md section 2:
field-level flags first, then content-level markers. Tolerant of unknown
record shapes — skip and count, never crash (the jsonl format is Claude
Code's private, version-dependent format).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from claude_code_hooks_daemon.skill_scan.constants import (
    CLAUDE_PROJECTS_SUBDIR,
    EXCLUDE_CONTENT_MARKERS,
    EXCLUDE_FLAGS,
    SECONDS_PER_DAY,
    TRANSCRIPT_GLOB,
    USER_RECORD_TYPE,
)
from claude_code_hooks_daemon.skill_scan.models import Prompt, ScanStats

logger = logging.getLogger(__name__)

_MESSAGE_FIELD = "message"
_CONTENT_FIELD = "content"
_TYPE_FIELD = "type"
_SESSION_ID_FIELD = "sessionId"
_SLUG_SEPARATOR = "-"
_PATH_SEPARATOR = "/"


def derive_transcript_dir(project_root: Path, home: Path | None = None) -> Path:
    """Claude Code's transcript directory for ``project_root``.

    Claude Code slugs a project path by replacing every path separator with
    ``-`` (so ``/workspace`` becomes ``-workspace``) under
    ``~/.claude/projects/``.
    """
    base = home if home is not None else Path.home()
    slug = str(project_root).replace(_PATH_SEPARATOR, _SLUG_SEPARATOR)
    return base.joinpath(*CLAUDE_PROJECTS_SUBDIR) / slug


def _is_genuine_text(text: str, markers: tuple[str, ...]) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return all(marker not in stripped for marker in markers)


def extract_prompts(
    transcript_dir: Path,
    window_days: int | None,
    stats: ScanStats,
    extra_exclude_patterns: tuple[str, ...] = (),
) -> list[Prompt]:
    """Extract genuine human prompts from every jsonl file in the window.

    Args:
        transcript_dir: Directory of ``*.jsonl`` transcript files.
        window_days: Only files modified within this many days are read;
            ``None`` reads everything.
        stats: Counter object mutated in place (schema-drift canary).
        extra_exclude_patterns: Additional content markers from config.

    Returns:
        Genuine human prompts, in file order. Missing directory returns [].
    """
    markers = EXCLUDE_CONTENT_MARKERS + extra_exclude_patterns
    cutoff = time.time() - window_days * SECONDS_PER_DAY if window_days else None
    prompts: list[Prompt] = []

    if not transcript_dir.is_dir():
        logger.debug("Transcript directory does not exist: %s", transcript_dir)
        return prompts

    for path in sorted(transcript_dir.glob(TRANSCRIPT_GLOB)):
        try:
            mtime = path.stat().st_mtime
        except OSError as exc:
            logger.debug("Could not stat transcript %s: %s", path, exc)
            continue
        if cutoff is not None and mtime < cutoff:
            continue
        stats.files += 1
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    stats.lines += 1
                    _consume_line(line, path, mtime, markers, stats, prompts)
        except OSError as exc:
            logger.debug("Could not read transcript %s: %s", path, exc)
    return prompts


def _consume_line(
    line: str,
    path: Path,
    mtime: float,
    markers: tuple[str, ...],
    stats: ScanStats,
    prompts: list[Prompt],
) -> None:
    """Parse one jsonl line, appending a Prompt when it is genuinely human."""
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        stats.unparseable += 1
        return
    if not isinstance(record, dict) or record.get(_TYPE_FIELD) != USER_RECORD_TYPE:
        return
    stats.user_records += 1
    if any(record.get(flag) for flag in EXCLUDE_FLAGS):
        stats.excluded_flags += 1
        return
    message = record.get(_MESSAGE_FIELD)
    content = message.get(_CONTENT_FIELD) if isinstance(message, dict) else None
    if not isinstance(content, str):
        stats.excluded_blocks += 1
        return
    if not _is_genuine_text(content, markers):
        stats.excluded_markers += 1
        return
    stats.genuine += 1
    prompts.append(
        Prompt(
            text=content.strip(),
            session_id=str(record.get(_SESSION_ID_FIELD, path.stem)),
            mtime=mtime,
        )
    )
