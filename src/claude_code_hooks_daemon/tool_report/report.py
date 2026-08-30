"""Tools-vs-tokens report generator (Plan 00293 Task 2.2).

Builds the recommendation report from a transcript usage summary plus the
project's declared never-wants. The report RECOMMENDS a disposition per tool
and names the known source-disable route; it never enforces anything —
projects decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from claude_code_hooks_daemon.tool_report.analyser import UsageSummary
from claude_code_hooks_daemon.tool_report.costs import MEASURED_SCHEMA_TOKENS, disable_route_for


class Tier(StrEnum):
    """Recommendation tiers, strongest claim first."""

    NEVER_WANT = "never-want"
    NEVER_USED = "never-used"
    LOW_USE = "low-use"
    KEEP = "keep"


@dataclass(frozen=True)
class ToolReportRow:
    """One tool's line in the report."""

    tool: str
    calls: int
    sessions: int
    schema_tokens: int | None
    loading: str | None
    tier: Tier
    reason: str
    disable_route: str


@dataclass(frozen=True)
class ToolReport:
    """The full report: ranked rows plus scan provenance."""

    rows: list[ToolReportRow] = field(default_factory=list)
    transcripts_scanned: int = 0
    sessions_scanned: int = 0
    malformed_lines: int = 0
    low_use_max_calls: int = 2


def _tier_for(
    tool: str, calls: int, never_want: dict[str, str], low_use_max_calls: int
) -> tuple[Tier, str]:
    """Classify one tool; the declared never-want always wins."""
    if tool in never_want:
        return Tier.NEVER_WANT, never_want[tool]
    if calls == 0:
        return Tier.NEVER_USED, "no calls observed in any scanned session"
    if calls <= low_use_max_calls:
        return Tier.LOW_USE, f"only {calls} call(s) across all scanned sessions"
    return Tier.KEEP, "in active use"


def build_report(
    summary: UsageSummary,
    never_want: dict[str, str],
    low_use_max_calls: int,
) -> ToolReport:
    """Combine observed usage, measured costs and declarations into a report.

    Tools appear when observed in transcripts, declared as never-wants, or
    present in the measured-cost table — the last is what makes a NEVER-USED
    tool visible at all, since absence from transcripts is exactly its signal.

    Args:
        summary: The transcript scan result.
        never_want: Declared never-want tools mapped to their reasons.
        low_use_max_calls: Highest total call count still classed as low-use.

    Returns:
        A :class:`ToolReport` with rows ranked by schema token cost
        (unknown-cost tools last), then by name.
    """
    tools = set(summary.usages) | set(MEASURED_SCHEMA_TOKENS) | set(never_want)
    rows: list[ToolReportRow] = []
    for tool in tools:
        usage = summary.usages.get(tool)
        calls = usage.calls if usage else 0
        sessions = usage.sessions if usage else 0
        cost = MEASURED_SCHEMA_TOKENS.get(tool)
        tier, reason = _tier_for(tool, calls, never_want, low_use_max_calls)
        rows.append(
            ToolReportRow(
                tool=tool,
                calls=calls,
                sessions=sessions,
                schema_tokens=cost.tokens if cost else None,
                loading=cost.loading if cost else None,
                tier=tier,
                reason=reason,
                disable_route=disable_route_for(tool),
            )
        )
    rows.sort(key=lambda row: (-(row.schema_tokens or -1), row.tool))
    return ToolReport(
        rows=rows,
        transcripts_scanned=summary.transcripts_scanned,
        sessions_scanned=summary.sessions_scanned,
        malformed_lines=summary.malformed_lines,
        low_use_max_calls=low_use_max_calls,
    )


def render_markdown(report: ToolReport) -> str:
    """Render the human-readable report."""
    lines = [
        "# Tool usage vs token cost report",
        "",
        f"Scanned {report.transcripts_scanned} transcript file(s) across "
        f"{report.sessions_scanned} session(s); {report.malformed_lines} malformed "
        "line(s) skipped. Counts are tool NAMES only — no transcript content is "
        "ever copied into this report.",
        "",
        "This report RECOMMENDS and never enforces: nothing is disabled "
        "automatically, the project decides. Schema token figures are "
        "estimates measured from one rendered session (tiktoken cl100k, "
        "2026-08-30) — rendered schemas are session-variant, so confirm any "
        "figure with `/context` in your own session. A `deferred` tool is "
        "already nearly free (name-only until loaded); disabling one saves "
        "almost nothing.",
        "",
        "| Tool | Schema tokens (est.) | Loading | Calls | Sessions | Tier | Why |",
        "| ---- | -------------------- | ------- | ----- | -------- | ---- | --- |",
    ]
    for row in report.rows:
        tokens = str(row.schema_tokens) if row.schema_tokens is not None else "?"
        loading = row.loading or "?"
        lines.append(
            f"| {row.tool} | {tokens} | {loading} | {row.calls} | "
            f"{row.sessions} | {row.tier.value} | {row.reason} |"
        )
    lines.append("")
    lines.append("## Disable routes for recommended tiers")
    lines.append("")
    lines.append(
        "Only bare tool-name disables remove a schema from context; a "
        "specifier or parameter deny rule refuses calls without saving any "
        "tokens (see the plan's RESEARCH-tool-disable.md)."
    )
    lines.append("")
    for row in report.rows:
        if row.tier in (Tier.NEVER_WANT, Tier.NEVER_USED):
            lines.append(f"- **{row.tool}** ({row.tier.value}): {row.disable_route}")
    lines.append("")
    lines.append(
        f"Low-use floor: {report.low_use_max_calls} call(s) " "(`tool_policy.low_use_max_calls`)."
    )
    return "\n".join(lines) + "\n"


def report_to_json(report: ToolReport) -> dict[str, Any]:
    """Render the machine-readable report."""
    return {
        "transcripts_scanned": report.transcripts_scanned,
        "sessions_scanned": report.sessions_scanned,
        "malformed_lines": report.malformed_lines,
        "low_use_max_calls": report.low_use_max_calls,
        "rows": [
            {
                "tool": row.tool,
                "schema_tokens": row.schema_tokens,
                "loading": row.loading,
                "calls": row.calls,
                "sessions": row.sessions,
                "tier": row.tier.value,
                "reason": row.reason,
                "disable_route": row.disable_route,
            }
            for row in report.rows
        ],
    }
