"""``hooks-daemon spend``: the subagent spend ledger of one session (Plan 00471 Task 2.1).

Reads every ``agent-*.jsonl`` of the session through the offset cache, so a
repeat run parses only what the agents appended since, and prints the tables of
the 471-B brainstorm section 1.3: per agent (or per plan) ``requests``,
``max_ctx``, ``mean_ctx``, ite, ``compactions`` and inbound messages. Below them
it prints the ``compact_boundary`` distribution, which is what the owner needs
to revisit the autocompact window (RULINGS-fable.md Q1), and the count of gate
calls that could not measure (Q2).

ite (input-token equivalents) weights input 1, cache write 1.25 (2 for a 1-hour
write), cache read 0.1 and output 5. It is a proxy for the unpublished
subscription weighting: compare its shares, not its absolute value.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from claude_code_hooks_daemon.utils.spend_ledger import read_agent_meta
from claude_code_hooks_daemon.utils.transcript_spend import (
    SpendTotals,
    TranscriptSpendCache,
    plan_key_from,
)

GroupBy = Literal["agent", "plan"]

#: Shown where an agent's plan cannot be told from its branch, cwd or name.
_NO_PLAN: Final[str] = "-"
_TOTAL: Final[str] = "TOTAL"
_LABEL_WIDTH: Final[int] = 22


@dataclass(frozen=True)
class AgentSpend:
    """One agent's ledger row."""

    agent_id: str
    name: str
    plan: str
    totals: SpendTotals

    @property
    def label(self) -> str:
        return self.name or self.agent_id


@dataclass
class _Group:
    label: str
    agents: int = 0
    requests: int = 0
    max_ctx: int = 0
    ctx_sum: int = 0
    ite: float = 0.0
    compactions: int = 0
    inbound: int = 0

    def add(self, totals: SpendTotals) -> None:
        self.agents += 1
        self.requests += totals.requests
        self.max_ctx = max(self.max_ctx, totals.max_ctx)
        self.ctx_sum += totals.ctx_sum
        self.ite += totals.ite
        self.compactions += totals.compactions
        self.inbound += totals.inbound_messages

    @property
    def mean_ctx(self) -> int:
        return round(self.ctx_sum / self.requests) if self.requests else 0

    def as_dict(self, key: str) -> dict[str, Any]:
        return {
            key: self.label,
            "agents": self.agents,
            "requests": self.requests,
            "max_ctx": self.max_ctx,
            "mean_ctx": self.mean_ctx,
            "ite": round(self.ite),
            "compactions": self.compactions,
            "inbound_messages": self.inbound,
        }


@dataclass
class SessionSpend:
    """Every agent of one session, plus what could not be read or measured."""

    session_id: str
    agents: list[AgentSpend] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    unmeasured: int = 0

    @property
    def compact_pre_tokens(self) -> list[int]:
        return sorted(token for agent in self.agents for token in agent.totals.compact_pre_tokens)

    def groups(self, by: GroupBy) -> list[_Group]:
        """Rows for the table, largest ite first (ties by label, for a stable order)."""
        grouped: dict[str, _Group] = {}
        for agent in self.agents:
            label = agent.label if by == "agent" else (agent.plan or _NO_PLAN)
            grouped.setdefault(label, _Group(label)).add(agent.totals)
        return sorted(grouped.values(), key=lambda group: (-group.ite, group.label))

    def total(self) -> _Group:
        total = _Group(_TOTAL)
        for agent in self.agents:
            total.add(agent.totals)
        return total


def collect_session_spend(
    subagents: Path, *, session_id: str, cache: TranscriptSpendCache, unmeasured: int
) -> SessionSpend:
    """Read every agent transcript in ``subagents`` through ``cache``.

    A transcript that cannot be read is listed, not fatal: the report is of
    what could be measured, and says what could not.
    """
    report = SessionSpend(session_id=session_id, unmeasured=unmeasured)
    try:
        transcripts = sorted(subagents.glob("agent-*.jsonl"))
    except OSError:
        transcripts = []
    for transcript in transcripts:
        agent_id = transcript.name.removeprefix("agent-").removesuffix(".jsonl")
        try:
            totals = cache.totals(transcript)
        except OSError:
            report.unreadable.append(agent_id)
            continue
        meta = read_agent_meta(transcript)
        plan = totals.plan_key or plan_key_from(meta.name)
        report.agents.append(
            AgentSpend(agent_id=agent_id, name=meta.name, plan=plan, totals=totals)
        )
    return report


def _row(first: str, second: str, group: _Group) -> str:
    return (
        f"{first:<{_LABEL_WIDTH}}{second:>6}{group.requests:>10,}{group.max_ctx:>9,}"
        f"{group.mean_ctx:>10,}{round(group.ite):>12,}{group.compactions:>13,}{group.inbound:>9,}"
    )


def _compaction_line(pre_tokens: list[int]) -> str:
    prefix = "Compactions (compact_boundary preTokens): "
    if not pre_tokens:
        return prefix + "none"
    return (
        f"{prefix}{len(pre_tokens)}, min {pre_tokens[0]:,}, "
        f"median {round(statistics.median(pre_tokens)):,}, max {pre_tokens[-1]:,}"
    )


def render_report(report: SessionSpend, *, by: GroupBy) -> str:
    """The human-readable report."""
    first, second = ("agent", "plan") if by == "agent" else ("plan", "agents")
    lines = [
        f"Subagent spend, session {report.session_id} ({len(report.agents)} agents)",
        "",
        f"{first:<{_LABEL_WIDTH}}{second:>6}{'requests':>10}{'max_ctx':>9}{'mean_ctx':>10}"
        f"{'ite':>12}{'compactions':>13}{'inbound':>9}",
    ]
    plan_of = {agent.label: agent.plan or _NO_PLAN for agent in report.agents}
    for group in report.groups(by):
        detail = plan_of.get(group.label, _NO_PLAN) if by == "agent" else str(group.agents)
        lines.append(_row(group.label, detail, group))
    lines.append(_row(_TOTAL, "", report.total()))
    lines.append("")
    lines.append(_compaction_line(report.compact_pre_tokens))
    lines.append(f"Unmeasured gate calls (agent, reason): {report.unmeasured}")
    if report.unreadable:
        lines.append(f"Unreadable transcripts: {', '.join(report.unreadable)}")
    return "\n".join(lines) + "\n"


def report_as_dict(report: SessionSpend) -> dict[str, Any]:
    """The machine-readable report: every agent row, both groupings and the extras."""
    return {
        "session": report.session_id,
        "agents": [
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "plan": agent.plan,
                **agent.totals.to_dict(),
            }
            for agent in sorted(report.agents, key=lambda agent: (-agent.totals.ite, agent.label))
        ],
        "by_plan": [group.as_dict("plan") for group in report.groups("plan")],
        "total": report.total().as_dict("label"),
        "compactions": {
            "count": len(report.compact_pre_tokens),
            "pre_tokens": report.compact_pre_tokens,
        },
        "unmeasured": report.unmeasured,
        "unreadable": report.unreadable,
    }
