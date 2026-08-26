"""Pipeline orchestration for the skill-opportunity scan (Plan 00274).

Extraction → clustering → digest → report. The judging stage is NOT run
here: the report embeds the ready-to-judge rubric prompt and the agent
dispatches an in-session subagent at it (PLAN.md Decision 9 — no headless
model shell-out).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from claude_code_hooks_daemon.skill_scan.clustering import cluster_prompts
from claude_code_hooks_daemon.skill_scan.digest import (
    build_digest,
    build_model_prompt,
    existing_skill_names,
)
from claude_code_hooks_daemon.skill_scan.extraction import (
    derive_transcript_dir,
    extract_prompts,
)
from claude_code_hooks_daemon.skill_scan.models import ScanStats, SkillScanOptions
from claude_code_hooks_daemon.skill_scan.report import write_report


@dataclass(frozen=True)
class ScanResult:
    """Everything the CLI needs to report a scan's outcome."""

    stats: ScanStats
    digest: str
    report_path: Path | None
    #: The ready-to-judge rubric prompt embedded in the report for the
    #: in-session subagent (``None`` on a dry run).
    judging_prompt: str | None


def run_scan(
    project_root: Path,
    options: SkillScanOptions,
    report_dir: Path,
    secret_terms: tuple[str, ...],
    today: date,
    dry_run: bool = False,
    window_days: int | None = None,
) -> ScanResult:
    """Run the whole pipeline once.

    Args:
        project_root: Project whose transcripts and skill inventory apply.
        options: The shared handler/CLI config surface.
        report_dir: Where the dated report is written.
        secret_terms: Secret word list terms; redacted everywhere.
        today: Report date (injected for testability).
        dry_run: Stages 1-2 only; print-ready digest, no report.
        window_days: Override of ``options.transcript_window_days``.
    """
    transcript_dir = (
        Path(options.transcript_dir)
        if options.transcript_dir is not None
        else derive_transcript_dir(project_root)
    )
    effective_window = window_days if window_days is not None else options.transcript_window_days

    stats = ScanStats()
    prompts = extract_prompts(
        transcript_dir,
        window_days=effective_window,
        stats=stats,
        extra_exclude_patterns=options.extra_exclude_patterns,
    )
    clusters = cluster_prompts(prompts)
    digest = build_digest(clusters, secret_terms, max_clusters=options.max_prompts)

    if dry_run:
        return ScanResult(stats=stats, digest=digest, report_path=None, judging_prompt=None)

    existing = existing_skill_names(project_root)
    judging_prompt = build_model_prompt(digest, existing)
    report_path = write_report(
        report_dir=report_dir,
        clusters=clusters,
        stats=stats,
        terms=secret_terms,
        existing=existing,
        judging_prompt=judging_prompt,
        today=today,
    )
    return ScanResult(
        stats=stats,
        digest=digest,
        report_path=report_path,
        judging_prompt=judging_prompt,
    )
