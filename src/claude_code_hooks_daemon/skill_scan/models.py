"""Data models for the skill-opportunity scan pipeline (Plan 00274)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from claude_code_hooks_daemon.skill_scan.constants import (
    DEFAULT_CHECK_INTERVAL_DAYS,
    DEFAULT_MAX_CLUSTERS,
    DEFAULT_TRANSCRIPT_WINDOW_DAYS,
    REPRESENTATIVE_MAX_CHARS,
)


@dataclass(frozen=True)
class Prompt:
    """One genuine human prompt extracted from a transcript."""

    text: str
    session_id: str
    mtime: float


@dataclass
class Cluster:
    """A group of near-identical normalised prompts."""

    key_tokens: frozenset[str]
    prompts: list[Prompt] = field(default_factory=list)

    @property
    def distinct_sessions(self) -> int:
        """Number of distinct sessions this cluster spans."""
        return len({prompt.session_id for prompt in self.prompts})

    @property
    def representative(self) -> str:
        """Longest member prompt, truncated to the digest budget."""
        longest = max(self.prompts, key=lambda prompt: len(prompt.text))
        return longest.text[:REPRESENTATIVE_MAX_CHARS]


@dataclass
class ScanStats:
    """Counters for the schema-drift canary (BRAINSTORM.md section 2)."""

    files: int = 0
    lines: int = 0
    user_records: int = 0
    unparseable: int = 0
    excluded_flags: int = 0
    excluded_blocks: int = 0
    excluded_markers: int = 0
    genuine: int = 0


def _as_int(value: Any, default: int) -> int:
    """Coerce a config value to int, falling back to ``default``."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


@dataclass(frozen=True)
class SkillScanOptions:
    """The handler/CLI shared config surface (BRAINSTORM.md section 6)."""

    check_interval_days: int = DEFAULT_CHECK_INTERVAL_DAYS
    transcript_window_days: int = DEFAULT_TRANSCRIPT_WINDOW_DAYS
    max_prompts: int = DEFAULT_MAX_CLUSTERS
    extra_exclude_patterns: tuple[str, ...] = ()
    transcript_dir: str | None = None

    @classmethod
    def from_dict(cls, options: dict[str, Any]) -> SkillScanOptions:
        """Build options from a raw handler ``options`` mapping.

        Invalid values fall back to defaults — the scan is a best-effort
        advisory feature and must never crash on a mistyped config value.
        """
        raw_patterns = options.get("extra_exclude_patterns")
        patterns: tuple[str, ...] = ()
        if isinstance(raw_patterns, list):
            patterns = tuple(item for item in raw_patterns if isinstance(item, str) and item)

        raw_dir = options.get("transcript_dir")
        transcript_dir = raw_dir if isinstance(raw_dir, str) and raw_dir else None

        return cls(
            check_interval_days=_as_int(
                options.get("check_interval_days"), DEFAULT_CHECK_INTERVAL_DAYS
            ),
            transcript_window_days=_as_int(
                options.get("transcript_window_days"), DEFAULT_TRANSCRIPT_WINDOW_DAYS
            ),
            max_prompts=_as_int(options.get("max_prompts"), DEFAULT_MAX_CLUSTERS),
            extra_exclude_patterns=patterns,
            transcript_dir=transcript_dir,
        )
