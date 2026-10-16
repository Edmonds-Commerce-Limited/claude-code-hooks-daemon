"""How many agents a session has live right now (Plan 00471 L4).

``background_tasks[]`` reaches only Stop and SubagentStop, not PreToolUse, so
the count is measured from the transcripts: an agent is live when its
transcript moved within ``liveness_seconds`` and its last conversational record
is not an ``end_turn``. Each Stop and SubagentStop records which
subagent/teammate tasks Claude Code reports as no longer running, and an agent
named there is not counted however recently it wrote. The count only ever
feeds an advisory: a stale count must never lock anyone out.

The five-hour limit (L5) is not read here: the daemon's shared usage snapshot
(:func:`core.data_layer.latest_usage`) holds it.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.spend_ledger import (
    read_state,
    session_dir,
    unmeasured_count,
    write_state,
)
from claude_code_hooks_daemon.utils.transcript_tail import (
    NoUsageInTail,
    agent_name_of,
    read_tail,
    subagents_dir,
)

logger = logging.getLogger(__name__)

#: An agent whose transcript moved this recently, and whose turn is open, is live.
DEFAULT_LIVENESS_SECONDS: Final[int] = 120

_BACKGROUND_FILE: Final[str] = "background-tasks.json"
_LIVE_FILE: Final[str] = "live.json"
_AGENT_TASK_TYPES: Final[frozenset[str]] = frozenset({"subagent", "teammate"})
_RUNNING: Final[str] = "running"


@dataclass(frozen=True)
class LiveAgent:
    """One agent counted as live."""

    agent_id: str
    name: str
    context_tokens: int
    idle_seconds: float
    model: str = ""

    @property
    def label(self) -> str:
        return self.name or self.agent_id


#: Model families the status segment counts live agents by (Plan 00472 T2).
_FAMILIES: Final[tuple[str, ...]] = ("fable", "opus", "sonnet", "haiku")
_OTHER_FAMILY: Final[str] = "other"


def model_family(model: str) -> str:
    """The family a model id belongs to, or ``other``."""
    lowered = model.lower()
    return next((family for family in _FAMILIES if family in lowered), _OTHER_FAMILY)


def live_agents(
    directory: Path,
    *,
    liveness_seconds: float,
    now: float | None = None,
    finished: frozenset[str] = frozenset(),
) -> list[LiveAgent]:
    """Agents in ``directory`` that wrote recently and have not ended their turn.

    ``finished`` holds agent ids or names Claude Code reported as no longer
    running; they are excluded. A recent transcript that cannot be read is
    counted live with an unknown (zero) context. Ordered by idle time, most
    recent first.
    """
    moment = time.time() if now is None else now
    found: list[LiveAgent] = []
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return []
    for entry in entries:
        if not (entry.name.startswith("agent-") and entry.name.endswith(".jsonl")):
            continue
        try:
            idle = moment - entry.stat().st_mtime
        except OSError as exc:
            log_and_continue(
                logger,
                exc,
                reason="a transcript that vanished or cannot be stat'ed after the directory scan has no write time, so it is not counted live",
                level=logging.DEBUG,
            )
            continue
        if idle > liveness_seconds:
            continue
        path = Path(entry.path)
        agent_id = entry.name.removeprefix("agent-").removesuffix(".jsonl")
        name = agent_name_of(path)
        if agent_id in finished or (name and name in finished):
            continue
        try:
            reading = read_tail(path)
        except (OSError, NoUsageInTail) as exc:
            log_and_continue(
                logger,
                exc,
                reason="a transcript written inside the liveness window but unreadable or usage-free is counted live with an unknown context, the safe direction for an advisory",
                level=logging.DEBUG,
            )
            reading = None
        if reading is not None and reading.stopped:
            continue
        found.append(
            LiveAgent(
                agent_id=agent_id,
                name=name,
                context_tokens=reading.context_tokens if reading is not None else 0,
                idle_seconds=idle,
                model=reading.model if reading is not None else "",
            )
        )
    return sorted(found, key=lambda agent: (agent.idle_seconds, agent.label))


def record_background_tasks(untracked: Path, session_id: str, tasks: object) -> None:
    """Record which agent tasks a Stop/SubagentStop reports as no longer running.

    An absent or malformed list is "unknown" (the contract says so) and leaves
    the previous record untouched. Each finished task contributes its ``id``
    and its ``description``, either of which may be what names the agent.
    """
    if not isinstance(tasks, list):
        return
    finished: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict) or task.get("type") not in _AGENT_TASK_TYPES:
            continue
        if task.get("status") == _RUNNING:
            continue
        for key in ("id", "description"):
            value = task.get(key)
            if isinstance(value, str) and value:
                finished.add(value)
    write_state(
        session_dir(untracked, session_id) / _BACKGROUND_FILE,
        {"ts": time.time(), "finished": sorted(finished)},
    )


def finished_agents(untracked: Path, session_id: str) -> frozenset[str]:
    """The agent ids and names last reported as no longer running."""
    state = read_state(session_dir(untracked, session_id) / _BACKGROUND_FILE)
    finished = state.get("finished")
    if not isinstance(finished, list):
        return frozenset()
    return frozenset(item for item in finished if isinstance(item, str))


def live_snapshot_path(untracked: Path, session_id: str) -> Path:
    """Where the last live count is kept for the status line."""
    return session_dir(untracked, session_id) / _LIVE_FILE


def write_live_snapshot(untracked: Path, session_id: str, agents: list[LiveAgent]) -> Path:
    """Persist the live count so the status line reads it without a scan.

    It also carries the per-family live counts and the session's unmeasured
    count, so one mtime-gated read gives the status segment everything.
    """
    path = live_snapshot_path(untracked, session_id)
    families: dict[str, int] = {}
    for agent in agents:
        family = model_family(agent.model)
        families[family] = families.get(family, 0) + 1
    write_state(
        path,
        {
            "ts": time.time(),
            "count": len(agents),
            "largest_context": max((agent.context_tokens for agent in agents), default=0),
            "agents": [agent.label for agent in agents],
            "families": families,
            "unmeasured": unmeasured_count(untracked, session_id),
        },
    )
    return path


def refresh_live_snapshot(
    untracked: Path,
    session_id: str,
    transcript_path: str,
    *,
    liveness_seconds: float = DEFAULT_LIVENESS_SECONDS,
) -> Path | None:
    """Recount the session's live agents and persist the snapshot; None without a session dir."""
    directory = subagents_dir(transcript_path, session_id)
    if directory is None:
        return None
    live = live_agents(
        directory,
        liveness_seconds=liveness_seconds,
        finished=finished_agents(untracked, session_id),
    )
    return write_live_snapshot(untracked, session_id, live)


def read_live_snapshot(path: Path) -> dict[str, Any]:
    """The snapshot :func:`write_live_snapshot` wrote, or ``{}``."""
    return read_state(path)
