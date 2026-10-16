"""``hooks-daemon tiers``: which model each subagent ran on, and why (Plan 00472 Task 3.4).

Joins the session's agent transcripts (through the shared offset cache, as
``hooks-daemon spend`` reads them) with the dispatch rows of the spend ledger by
``tool_use_id`` (``meta.json``'s ``toolUseId``), and prints 472-B section 2's
tables: agents and ite by source, by model family and by role (or by
``subagent_type``). Below them:

- the ``CLAUDE_CODE_SUBAGENT_MODEL`` line, read from the project
  ``settings.json`` env block (ruling D1: reported and recommended, not set);
- the share of agents that inherited their spawner's tier;
- every agent whose per-request models show a mid-run swap, with the counts.

An agent with no dispatch row (spawned before the ledger, or by a Workflow
script) is listed under the source ``unrecorded``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from claude_code_hooks_daemon.daemon.spend_report import collect_session_spend
from claude_code_hooks_daemon.utils.dispatch_tier import (
    INHERITING_SOURCES,
    classify_role,
    read_env_subagent_model,
)
from claude_code_hooks_daemon.utils.model_tiers import resolve_model_family
from claude_code_hooks_daemon.utils.spend_ledger import read_agent_meta, read_dispatch_rows
from claude_code_hooks_daemon.utils.transcript_spend import TranscriptSpendCache

GroupBy = Literal["source", "type", "role"]

UNRECORDED: Final[str] = "unrecorded"
_UNKNOWN_FAMILY: Final[str] = "unknown"
_TOTAL: Final[str] = "TOTAL"
_LABEL_WIDTH: Final[int] = 22
_INHERITING: Final[frozenset[str]] = frozenset(source.value for source in INHERITING_SOURCES)
_DOCS_PAGE: Final[str] = "docs/guides/SUBAGENT_MODEL_TIERS.md"
_TITLES: Final[dict[str, str]] = {
    "source": "source",
    "type": "subagent_type",
    "role": "role",
    "model": "model",
}


@dataclass(frozen=True)
class AgentTier:
    """One agent's tier row: how its model was chosen and what it ran on."""

    agent_id: str
    name: str
    subagent_type: str
    source: str
    role: str
    family: str
    ite: float
    per_model_requests: dict[str, int]

    @property
    def label(self) -> str:
        return self.name or self.agent_id

    @property
    def swapped(self) -> bool:
        """More than one model served this agent's requests: a mid-run swap."""
        return len(self.per_model_requests) > 1


@dataclass
class TierReport:
    """One session's tier report."""

    session_id: str
    env_model: str
    unjoined: int
    agents: list[AgentTier] = field(default_factory=list)


def _family(model: str) -> str | None:
    resolved = resolve_model_family(model)
    return resolved[0] if resolved is not None else None


def collect_tiers(
    subagents: Path,
    *,
    session_id: str,
    untracked: Path,
    cache: TranscriptSpendCache,
    project_root: Path,
) -> TierReport:
    """Join the session's agents with its dispatch rows.

    Raises:
        OSError: ``subagents`` exists but cannot be listed.
    """
    rows = read_dispatch_rows(untracked, session_id)
    by_id = {str(row["tool_use_id"]): row for row in rows}
    unjoined = sum(
        1 for row in rows if row.get("pre_recorded") is not True or not row.get("resolved_model")
    )
    report = TierReport(
        session_id=session_id,
        env_model=read_env_subagent_model(project_root),
        unjoined=unjoined,
    )
    spend = collect_session_spend(subagents, session_id=session_id, cache=cache, unmeasured=0)
    for agent in spend.agents:
        meta = read_agent_meta(subagents / f"agent-{agent.agent_id}.jsonl")
        row = by_id.get(meta.tool_use_id, {})
        totals = agent.totals
        busiest = max(totals.per_model_requests, key=totals.per_model_requests.__getitem__, default="")
        family = (
            _family(str(row.get("resolved_model") or ""))
            or _family(totals.resolved_model)
            or _family(busiest)
            or str(row.get("predicted_family") or "")
            or _UNKNOWN_FAMILY
        )
        subagent_type = str(row.get("subagent_type") or meta.agent_type)
        report.agents.append(
            AgentTier(
                agent_id=agent.agent_id,
                name=agent.name,
                subagent_type=subagent_type,
                source=str(row.get("source") or UNRECORDED),
                role=str(row.get("role") or classify_role(subagent_type, agent.name, "").value),
                family=family,
                ite=totals.ite,
                per_model_requests=dict(totals.per_model_requests),
            )
        )
    return report


def _key(agent: AgentTier, by: str) -> str:
    if by == "type":
        return agent.subagent_type or "-"
    if by == "model":
        return agent.family
    return agent.source if by == "source" else agent.role


def _row(label: str, agents: int, ite: float, total_ite: float, models: str) -> str:
    share = 100.0 * ite / total_ite if total_ite else 0.0
    return (
        f"{label:<{_LABEL_WIDTH}}{agents:>7}{round(ite):>12,}{share:>7.1f}%  {models}"
    ).rstrip()


def _table(report: TierReport, by: str) -> list[str]:
    total_ite = sum(agent.ite for agent in report.agents)
    groups: dict[str, list[AgentTier]] = {}
    for agent in report.agents:
        groups.setdefault(_key(agent, by), []).append(agent)
    lines = [f"{_TITLES[by]:<{_LABEL_WIDTH}}{'agents':>7}{'ite':>12}{'share':>8}  models"]
    for label in sorted(groups):
        members = groups[label]
        mix = Counter(agent.family for agent in members)
        models = ", ".join(f"{family} {count}" for family, count in sorted(mix.items()))
        lines.append(_row(label, len(members), sum(a.ite for a in members), total_ite, models))
    lines.append(_row(_TOTAL, len(report.agents), total_ite, total_ite, ""))
    return lines


def _env_line(env_model: str) -> str:
    if env_model:
        return f"CLAUDE_CODE_SUBAGENT_MODEL: {env_model} (.claude/settings.json env)"
    return (
        "CLAUDE_CODE_SUBAGENT_MODEL: not set in .claude/settings.json (recommended: sonnet, "
        f"with floors for reviewers; see {_DOCS_PAGE})"
    )


def _inherited_line(report: TierReport) -> str:
    total_ite = sum(agent.ite for agent in report.agents)
    inherited = [agent for agent in report.agents if agent.source in _INHERITING]
    ite = sum(agent.ite for agent in inherited)
    share = 100.0 * ite / total_ite if total_ite else 0.0
    return (
        f"Inherited at the spawner's tier: {len(inherited)} of {len(report.agents)} agents, "
        f"{share:.1f}% of ite"
    )


def render_tiers(report: TierReport, *, by: GroupBy | None) -> str:
    """The human-readable report; ``by`` None prints the source, model and role tables."""
    lines = [
        f"Subagent tiers, session {report.session_id} ({len(report.agents)} agents, "
        f"{report.unjoined} unjoined dispatch rows)",
    ]
    for grouping in ("source", "model", "role") if by is None else (by,):
        lines.append("")
        lines.extend(_table(report, grouping))
    lines.append("")
    lines.append(_env_line(report.env_model))
    lines.append(_inherited_line(report))
    swapped = [agent for agent in report.agents if agent.swapped]
    if swapped:
        lines.append("Downgraded agents (model swapped mid-run):")
        for agent in swapped:
            counts = ", ".join(f"{model} {n}" for model, n in agent.per_model_requests.items())
            lines.append(f"  {agent.label}  {counts}")
    else:
        lines.append("Downgraded agents (model swapped mid-run): none")
    return "\n".join(lines) + "\n"


def tiers_as_dict(report: TierReport) -> dict[str, Any]:
    """The machine-readable report."""
    rows = [
        {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "subagent_type": agent.subagent_type,
            "source": agent.source,
            "role": agent.role,
            "family": agent.family,
            "ite": round(agent.ite),
            "per_model_requests": agent.per_model_requests,
        }
        for agent in report.agents
    ]
    return {
        "session": report.session_id,
        "env_subagent_model": report.env_model,
        "unjoined": report.unjoined,
        "agents": rows,
        "downgraded": [row for row, agent in zip(rows, report.agents, strict=True) if agent.swapped],
    }
