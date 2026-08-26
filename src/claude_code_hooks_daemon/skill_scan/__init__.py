"""Skill-opportunity detection pipeline (Plan 00274).

Mines Claude Code session transcripts for repeated workloads and recurring
points of confusion, and files a human-reviewed report of skill-creation
suggestions. Three stages: deterministic extraction, deterministic
condense/redact aggregation, one bounded model call. Never auto-creates a
skill.
"""

from claude_code_hooks_daemon.skill_scan.models import (
    Cluster,
    Prompt,
    ScanStats,
    SkillScanOptions,
)
from claude_code_hooks_daemon.skill_scan.pipeline import ScanResult, run_scan

__all__ = [
    "Cluster",
    "Prompt",
    "ScanResult",
    "ScanStats",
    "SkillScanOptions",
    "run_scan",
]
