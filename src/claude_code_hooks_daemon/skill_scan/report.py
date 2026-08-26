"""Report generation for the skill-opportunity scan (Plan 00274).

Reports follow docs/guides/CREATING_REPORTS.md conventions
(``untracked/reports/YYYY-MM-DD-skill-opportunities.md``, PLAN.md Decision
6) with a standing privacy header — this content is derived from private
session transcripts. Everything rendered passes through secret redaction.

The report is the subagent's briefing (PLAN.md Decision 9): it embeds the
judging rubric and the redacted digest, and the dispatching agent appends
the subagent's findings under ``## Findings``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from claude_code_hooks_daemon.skill_scan.clustering import normalise
from claude_code_hooks_daemon.skill_scan.constants import (
    MAX_REPORT_CLUSTERS,
    REPORT_FILE_SUFFIX,
)
from claude_code_hooks_daemon.skill_scan.models import Cluster, ScanStats
from claude_code_hooks_daemon.utils.secret_redaction import redact_text

_PRIVACY_HEADER = (
    "> **PRIVACY**: derived from private session transcripts - review before\n"
    "> sharing outside the project. Representatives are normalised, truncated\n"
    "> and secret-redacted, but redaction is list-based and cannot catch\n"
    "> unlisted secrets.\n"
)
_NO_INVENTORY = "(none)"


def write_report(
    report_dir: Path,
    clusters: list[Cluster],
    stats: ScanStats,
    terms: tuple[str, ...],
    existing: list[str],
    judging_prompt: str,
    today: date,
) -> Path:
    """Write the dated report file and return its path."""
    report_path = report_dir / f"{today.isoformat()}{REPORT_FILE_SUFFIX}"
    report_dir.mkdir(parents=True, exist_ok=True)

    multi = [cluster for cluster in clusters if len(cluster.prompts) > 1]
    inventory = ", ".join(existing) if existing else _NO_INVENTORY
    lines: list[str] = [
        f"# Skill Opportunity Report — {today.isoformat()}",
        "",
        _PRIVACY_HEADER,
        "## Scan statistics",
        "",
        f"- Transcript files scanned: {stats.files} ({stats.lines} lines)",
        f"- `type: user` records: {stats.user_records}",
        f"- Excluded by field flags (meta/sidechain/compaction): {stats.excluded_flags}",
        f"- Excluded block-content (tool results etc.): {stats.excluded_blocks}",
        f"- Excluded by content markers (machine traffic): {stats.excluded_markers}",
        f"- Genuine human prompts: {stats.genuine}",
        f"- Unparseable lines (schema-drift canary): {stats.unparseable}",
        f"- Clusters: {len(clusters)} total, {len(multi)} with repetition",
        f"- Existing skills/commands suppressed: {inventory}",
        "",
        "## Top repeated clusters (deterministic)",
        "",
    ]
    if not multi:
        lines.append("_No repeated clusters in the window._")
    for idx, cluster in enumerate(multi[:MAX_REPORT_CLUSTERS], start=1):
        # Same normalise-then-redact path as the digest: raw prompt text
        # (including embedded paths) never reaches the report either.
        rep = redact_text(normalise(cluster.representative), terms)
        lines.append(
            f"{idx}. **{len(cluster.prompts)}x / {cluster.distinct_sessions} session(s)** — "
            f"`{rep}`"
        )
    lines.extend(
        [
            "",
            "## Judging (subagent task)",
            "",
            "Dispatch a subagent with the prompt below. Append its answer under",
            "`## Findings`. Report-only: never create a skill without human sign-off.",
            "",
            "```text",
            redact_text(judging_prompt, terms),
            "```",
            "",
            "## Findings",
            "",
            "_Pending subagent judging._",
            "",
        ]
    )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
