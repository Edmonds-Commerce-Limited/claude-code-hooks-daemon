"""Ranked block-frequency report + promotion recommendation (Plan 00116 Task 2b.1).

Combines a :class:`~claude_code_hooks_daemon.block_report.analyser.BlockSummary`
with the project's committed ``claude_md.promotion`` config to produce a
ranked table, a per-handler promotion RECOMMENDATION, and drift notes when
the committed list disagrees with the measured evidence. This report never
enforces anything — the injector (owned separately) is the only consumer
that acts on the committed ``promoted_handlers`` list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from claude_code_hooks_daemon.block_report.analyser import BlockSummary


class Drift(StrEnum):
    """A mismatch between the committed promotion list and real evidence."""

    PROMOTED_BUT_COLD = "promoted-but-cold"
    HOT_BUT_UNPROMOTED = "hot-but-unpromoted"


@dataclass(frozen=True)
class BlockReportRow:
    """One handler's line in the report."""

    handler: str
    total_blocks: int
    distinct_sessions: int
    last_seen: str | None
    currently_promoted: bool
    recommended_promote: bool
    drift: Drift | None


@dataclass(frozen=True)
class BlockReport:
    """The full report: ranked rows plus scan provenance."""

    rows: list[BlockReportRow] = field(default_factory=list)
    transcripts_scanned: int = 0
    sessions_scanned: int = 0
    malformed_lines: int = 0
    unattributed_denies: int = 0
    min_blocks: int = 5
    min_sessions: int = 2


def _drift_for(*, currently_promoted: bool, recommended_promote: bool) -> Drift | None:
    if currently_promoted and not recommended_promote:
        return Drift.PROMOTED_BUT_COLD
    if recommended_promote and not currently_promoted:
        return Drift.HOT_BUT_UNPROMOTED
    return None


def build_report(
    summary: BlockSummary,
    promoted_handlers: list[str],
    min_blocks: int,
    min_sessions: int,
) -> BlockReport:
    """Combine observed deny counts and the promotion config into a report.

    A handler appears when it was observed in transcripts OR is in the
    committed ``promoted_handlers`` list — the latter is what surfaces a
    promoted handler with ZERO real evidence (the strongest form of drift).

    Args:
        summary: The transcript scan result.
        promoted_handlers: The project's committed ``claude_md.promotion.
            promoted_handlers`` list.
        min_blocks: Block-count threshold for the promotion recommendation.
        min_sessions: Distinct-session threshold for the recommendation.

    Returns:
        A :class:`BlockReport` with rows ranked by total blocks descending,
        then by handler name.
    """
    handlers = set(summary.blocks) | set(promoted_handlers)
    rows: list[BlockReportRow] = []
    for handler in handlers:
        usage = summary.blocks.get(handler)
        total = usage.total if usage else 0
        sessions = len(usage.sessions) if usage else 0
        last_seen = usage.last_seen if usage else None
        currently_promoted = handler in promoted_handlers
        recommended_promote = total >= min_blocks and sessions >= min_sessions
        rows.append(
            BlockReportRow(
                handler=handler,
                total_blocks=total,
                distinct_sessions=sessions,
                last_seen=last_seen,
                currently_promoted=currently_promoted,
                recommended_promote=recommended_promote,
                drift=_drift_for(
                    currently_promoted=currently_promoted,
                    recommended_promote=recommended_promote,
                ),
            )
        )
    rows.sort(key=lambda row: (-row.total_blocks, row.handler))
    return BlockReport(
        rows=rows,
        transcripts_scanned=summary.transcripts_scanned,
        sessions_scanned=summary.sessions_scanned,
        malformed_lines=summary.malformed_lines,
        unattributed_denies=summary.unattributed_denies,
        min_blocks=min_blocks,
        min_sessions=min_sessions,
    )


def render_markdown(report: BlockReport) -> str:
    """Render the human-readable report."""
    lines = [
        "# Handler block-frequency report",
        "",
        f"Scanned {report.transcripts_scanned} transcript file(s) across "
        f"{report.sessions_scanned} session(s); {report.malformed_lines} malformed "
        f"line(s) and {report.unattributed_denies} unattributed deny(s) skipped. "
        "Counts are handler NAMES only — command text and file contents are "
        "never copied into this report.",
        "",
        f"Promotion recommendation threshold: >= {report.min_blocks} total block(s) "
        f"AND >= {report.min_sessions} distinct session(s).",
        "",
        "| Handler | Blocks | Sessions | Last seen | Promoted | Recommend | Drift |",
        "| ------- | ------ | -------- | --------- | -------- | --------- | ----- |",
    ]
    for row in report.rows:
        last_seen = row.last_seen or "-"
        promoted = "yes" if row.currently_promoted else "no"
        recommend = "PROMOTE" if row.recommended_promote else "progressive"
        drift = row.drift.value if row.drift else "-"
        lines.append(
            f"| {row.handler} | {row.total_blocks} | {row.distinct_sessions} | "
            f"{last_seen} | {promoted} | {recommend} | {drift} |"
        )
    lines.append("")
    recommended = [row.handler for row in report.rows if row.recommended_promote]
    if recommended:
        lines.append("## Recommended promoted_handlers")
        lines.append("")
        lines.append("```yaml")
        lines.append("claude_md:")
        lines.append("  promotion:")
        lines.append("    promoted_handlers:")
        for handler in sorted(recommended):
            lines.append(f"      - {handler}")
        lines.append("```")
    else:
        lines.append("No handler currently meets the promotion threshold.")
    lines.append("")
    return "\n".join(lines) + "\n"


def report_to_json(report: BlockReport) -> dict[str, Any]:
    """Render the machine-readable report."""
    return {
        "transcripts_scanned": report.transcripts_scanned,
        "sessions_scanned": report.sessions_scanned,
        "malformed_lines": report.malformed_lines,
        "unattributed_denies": report.unattributed_denies,
        "min_blocks": report.min_blocks,
        "min_sessions": report.min_sessions,
        "rows": [
            {
                "handler": row.handler,
                "total_blocks": row.total_blocks,
                "distinct_sessions": row.distinct_sessions,
                "last_seen": row.last_seen,
                "currently_promoted": row.currently_promoted,
                "recommended_promote": row.recommended_promote,
                "drift": row.drift.value if row.drift else None,
            }
            for row in report.rows
        ],
    }
