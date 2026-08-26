"""Pipeline orchestration for the skill-opportunity scan (Plan 00274).

Extraction → clustering → digest → model → report. The model stage is
injected (``ModelInvoker``) and every external boundary is fail-open: a
model failure yields a partial report, an empty window a no-op report.
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
from claude_code_hooks_daemon.skill_scan.invoker import (
    ModelInvoker,
    ModelSuggestions,
    parse_model_output,
)
from claude_code_hooks_daemon.skill_scan.models import ScanStats, SkillScanOptions
from claude_code_hooks_daemon.skill_scan.report import write_report


@dataclass(frozen=True)
class ScanResult:
    """Everything the CLI needs to report a scan's outcome."""

    stats: ScanStats
    digest: str
    report_path: Path | None
    model_error: str | None
    suggestions: ModelSuggestions | None


def run_scan(
    project_root: Path,
    options: SkillScanOptions,
    invoker: ModelInvoker,
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
        invoker: The model stage (injectable; mocked in tests).
        report_dir: Where the dated report is written.
        secret_terms: Secret word list terms; redacted everywhere.
        today: Report date (injected for testability).
        dry_run: Stages 1-2 only; print-ready digest, no model, no report.
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
        return ScanResult(
            stats=stats, digest=digest, report_path=None, model_error=None, suggestions=None
        )

    existing = existing_skill_names(project_root)
    suggestions: ModelSuggestions | None = None
    raw_output: str | None = None
    model_error: str | None = None
    if prompts:
        model_prompt = build_model_prompt(digest, existing)
        output, model_error = invoker.invoke(model_prompt)
        if output is not None:
            suggestions = parse_model_output(output)
            if suggestions is None:
                raw_output = output
    else:
        model_error = "nothing to scan in the transcript window"

    report_path = write_report(
        report_dir=report_dir,
        clusters=clusters,
        stats=stats,
        terms=secret_terms,
        suggestions=suggestions,
        raw_model_output=raw_output,
        model_error=model_error,
        existing=existing,
        today=today,
    )
    return ScanResult(
        stats=stats,
        digest=digest,
        report_path=report_path,
        model_error=model_error,
        suggestions=suggestions,
    )
