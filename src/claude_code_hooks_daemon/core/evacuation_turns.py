"""Evacuations remembered for the current turn (Plan 00558 DESIGN section 13, Task 4.5).

The same-turn half of evacuate-then-destroy: a PostToolUse recorder notes each
evacuation here, and ``destructive_git`` denies a later destruction of the same
worktree or branch. The record is per identity (the main thread, or one
sub-agent) in the session's spend-ledger state, and it is bounded: it holds the
current turn only. The main thread's turn is a counter that the UserPromptSubmit
marker advances; a sub-agent's turn is its lifetime, so its record needs no
expiry. An evacuation whose source worktree cannot be placed is not recorded,
because a record that cannot be matched would deny every destruction.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.core.evacuation import Evacuation
from claude_code_hooks_daemon.utils.spend_ledger import read_state, state_path, write_state

_RECORD_KIND: Final[str] = "evacuation_record"
_TURN_KIND: Final[str] = "evacuation_turn"
_TURN_KEY: Final[str] = "main"
_TURN: Final[str] = "turn"
_WORKS: Final[str] = "works"
#: The most evacuations one turn keeps; the oldest are dropped.
MAX_RECORDS: Final[int] = 50
_MAIN_IDENTITY: Final[str] = "main"


def _current_turn(untracked: Path, session_id: str, agent_id: str | None) -> str:
    """The turn key: the agent id in a sub-agent, else the main thread's prompt counter."""
    if agent_id:
        return f"agent:{agent_id}"
    count = read_state(state_path(untracked, session_id, _TURN_KIND, _TURN_KEY)).get(_TURN, 0)
    return f"turn:{count if isinstance(count, int) else 0}"


def _record_path(untracked: Path, session_id: str, agent_id: str | None) -> Path:
    return state_path(untracked, session_id, _RECORD_KIND, agent_id or _MAIN_IDENTITY)


def advance_turn(untracked: Path, session_id: str) -> None:
    """Start a new main-thread turn; the records of the previous one stop counting."""
    path = state_path(untracked, session_id, _TURN_KIND, _TURN_KEY)
    count = read_state(path).get(_TURN, 0)
    write_state(path, {_TURN: (count if isinstance(count, int) else 0) + 1})


def _to_row(work: Evacuation) -> dict[str, Any]:
    return {
        "text": work.text,
        "landing": work.landing,
        "toplevel": str(work.toplevel),
        "branches": sorted(work.branches),
    }


def _from_row(row: object) -> Evacuation | None:
    if not isinstance(row, dict):
        return None
    text, landing, toplevel = row.get("text"), row.get("landing"), row.get("toplevel")
    branches = row.get("branches")
    if not (isinstance(text, str) and isinstance(landing, str) and isinstance(toplevel, str)):
        return None
    if not isinstance(branches, list):
        return None
    return Evacuation(
        text=text,
        landing=landing,
        toplevel=Path(toplevel),
        branches=frozenset(str(branch) for branch in branches),
    )


def recorded_evacuations(
    untracked: Path, session_id: str, agent_id: str | None
) -> list[Evacuation]:
    """The evacuations recorded in this identity's current turn; none from an older one."""
    state = read_state(_record_path(untracked, session_id, agent_id))
    rows = state.get(_WORKS)
    if state.get(_TURN) != _current_turn(untracked, session_id, agent_id):
        return []
    if not isinstance(rows, list):
        return []
    works = (_from_row(row) for row in rows)
    return [work for work in works if work is not None]


def record_evacuations(
    untracked: Path, session_id: str, agent_id: str | None, works: Iterable[Evacuation]
) -> None:
    """Add placeable evacuations to this identity's record for the current turn."""
    placed = [work for work in works if work.toplevel is not None]
    if not placed:
        return
    kept = recorded_evacuations(untracked, session_id, agent_id)
    rows = [_to_row(work) for work in [*kept, *placed]][-MAX_RECORDS:]
    write_state(
        _record_path(untracked, session_id, agent_id),
        {_TURN: _current_turn(untracked, session_id, agent_id), _WORKS: rows},
    )
