"""Tests for the tools-vs-tokens report generator (Plan 00293 Task 2.2).

The report ranks tools by estimated schema token cost against observed usage
and RECOMMENDS a disposition tier per tool — it never enforces anything.
Tiers: ``never-want`` (project-declared), ``never-used`` (zero observed
calls), ``low-use`` (at or below the configured floor), ``keep``.
"""

import json
from pathlib import Path

from claude_code_hooks_daemon.tool_report.analyser import ToolUsage, UsageSummary
from claude_code_hooks_daemon.tool_report.plugin_costs import PluginListingCost
from claude_code_hooks_daemon.tool_report.report import (
    Tier,
    build_report,
    render_markdown,
    report_to_json,
)


def _summary(usages: dict[str, ToolUsage], sessions: int = 4) -> UsageSummary:
    return UsageSummary(
        transcripts_scanned=sessions,
        sessions_scanned=sessions,
        malformed_lines=0,
        usages=usages,
    )


def _usage(name: str, calls: int, sessions: int) -> ToolUsage:
    return ToolUsage(name=name, calls=calls, sessions=sessions)


class TestTiering:
    """Recommendation tiers from usage + declarations."""

    def test_declared_never_want_wins_even_when_used(self) -> None:
        report = build_report(
            _summary({"Artifact": _usage("Artifact", 3, 1)}),
            never_want={"Artifact": "publishing leaves the repository"},
            low_use_max_calls=2,
        )
        row = next(r for r in report.rows if r.tool == "Artifact")
        assert row.tier == Tier.NEVER_WANT
        assert row.reason == "publishing leaves the repository"

    def test_known_tool_with_zero_calls_is_never_used(self) -> None:
        """Tools from the measured-cost table appear even when no transcript
        ever mentions them — absence IS the signal."""
        report = build_report(_summary({}), never_want={}, low_use_max_calls=2)
        row = next(r for r in report.rows if r.tool == "NotebookEdit")
        assert row.tier == Tier.NEVER_USED
        assert row.calls == 0

    def test_low_use_at_or_below_floor(self) -> None:
        report = build_report(
            _summary({"WebSearch": _usage("WebSearch", 2, 1)}),
            never_want={},
            low_use_max_calls=2,
        )
        row = next(r for r in report.rows if r.tool == "WebSearch")
        assert row.tier == Tier.LOW_USE

    def test_keep_above_floor(self) -> None:
        report = build_report(
            _summary({"Bash": _usage("Bash", 500, 4)}),
            never_want={},
            low_use_max_calls=2,
        )
        row = next(r for r in report.rows if r.tool == "Bash")
        assert row.tier == Tier.KEEP

    def test_unknown_observed_tool_is_reported_without_a_cost(self) -> None:
        """An MCP or future tool outside the measured table still shows up —
        with no token estimate rather than a fabricated one."""
        report = build_report(
            _summary({"mcp__github__search": _usage("mcp__github__search", 9, 3)}),
            never_want={},
            low_use_max_calls=2,
        )
        row = next(r for r in report.rows if r.tool == "mcp__github__search")
        assert row.schema_tokens is None
        assert row.tier == Tier.KEEP

    def test_rows_ranked_by_schema_tokens_descending(self) -> None:
        report = build_report(_summary({}), never_want={}, low_use_max_calls=2)
        tokens = [r.schema_tokens for r in report.rows if r.schema_tokens is not None]
        assert tokens == sorted(tokens, reverse=True)
        assert report.rows[0].tool == "Artifact"


class TestRendering:
    """Markdown + JSON outputs."""

    def test_markdown_contains_table_and_measurement_caveat(self) -> None:
        report = build_report(
            _summary({"Bash": _usage("Bash", 500, 4)}),
            never_want={"Artifact": "never published"},
            low_use_max_calls=2,
        )
        markdown = render_markdown(report)
        assert "| Tool" in markdown
        assert "estimate" in markdown.lower()
        assert "/context" in markdown
        assert "never enforces" in markdown.lower() or "recommend" in markdown.lower()

    def test_markdown_names_the_disable_route_for_never_wants(self) -> None:
        report = build_report(
            _summary({}),
            never_want={"Artifact": "never published"},
            low_use_max_calls=2,
        )
        markdown = render_markdown(report)
        assert "enableArtifact" in markdown

    def test_json_round_trips_rows(self, tmp_path: Path) -> None:
        report = build_report(
            _summary({"Bash": _usage("Bash", 500, 4)}),
            never_want={},
            low_use_max_calls=2,
        )
        payload = report_to_json(report)
        parsed = json.loads(json.dumps(payload))
        tools = {row["tool"] for row in parsed["rows"]}
        assert "Bash" in tools
        assert parsed["sessions_scanned"] == 4


_DBF_COST = PluginListingCost(
    plugin_id="defence-before-fix@defence-before-fix",
    skills_listed=1,
    skills_hidden=0,
    agents_listed=2,
    skill_chars=400,
    agent_chars=700,
)


class TestPluginListingCosts:
    """Plan 00468 G15: the report sums each enabled Claude Code plugin's
    always-on listing cost, beside the per-tool schema costs."""

    def test_the_report_carries_the_plugin_costs(self) -> None:
        report = build_report(
            _summary({}), never_want={}, low_use_max_calls=2, plugin_costs=(_DBF_COST,)
        )
        assert report.plugin_costs == (_DBF_COST,)

    def test_markdown_has_a_row_per_plugin(self) -> None:
        report = build_report(
            _summary({}), never_want={}, low_use_max_calls=2, plugin_costs=(_DBF_COST,)
        )
        markdown = render_markdown(report)
        assert "## Enabled Claude Code plugins" in markdown
        assert "| defence-before-fix@defence-before-fix | 1 | 0 | 2 | 1100 | 275 |" in markdown
        assert "MCP" in markdown

    def test_markdown_says_so_when_no_plugin_is_enabled(self) -> None:
        report = build_report(_summary({}), never_want={}, low_use_max_calls=2)
        assert "No enabled Claude Code plugins" in render_markdown(report)

    def test_json_carries_the_plugin_costs(self) -> None:
        report = build_report(
            _summary({}), never_want={}, low_use_max_calls=2, plugin_costs=(_DBF_COST,)
        )
        (row,) = report_to_json(report)["plugins"]
        assert row == {
            "plugin_id": "defence-before-fix@defence-before-fix",
            "skills_listed": 1,
            "skills_hidden": 0,
            "agents_listed": 2,
            "skill_chars": 400,
            "agent_chars": 700,
            "total_chars": 1100,
            "estimated_tokens": 275,
        }
