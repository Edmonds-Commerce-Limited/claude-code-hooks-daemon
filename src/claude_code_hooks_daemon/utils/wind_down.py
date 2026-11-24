"""The wind-down note: a stop around running background agents (Plan 00636 Task 2.4, s8).

A coordinator that dispatched background agents ends turns while they run.
Each such stop without a ``STOPPING BECAUSE:`` line is refused by
``auto_continue_stop``, and the refusal never said that waiting on its own
agents is a reason it may simply declare. This module reads the Stop payload's
``background_tasks`` list and renders a note that names the running tasks and
the one stop line that passes.

Reading rules (fail closed, never raises):

- An absent, malformed or empty list is no information: ``None``.
- Only a dict entry whose ``status`` is exactly ``running`` counts.
- An id is echoed only when it is a plain string of safe characters, truncated
  to ``MAX_ID_CHARS``; at most ``MAX_LISTED_IDS`` are listed. Any other id is
  counted but never pasted into context.

"Reported as running" is not "in flight": a finished, idle teammate is still
listed as running (``teammate_reap_advisor``), so the note points at
``ListAgents`` and ``TaskStop`` rather than claiming the work is live.

The suggested stop line deliberately carries no waiting-on-a-human wording, so
it arms neither the awaiting-human marker nor ``owner_wait_stop_guard``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from claude_code_hooks_daemon.constants import HookInputField

#: Most ids the note lists; the rest are counted as "and N more".
MAX_LISTED_IDS: Final[int] = 5
#: Longest id echoed into context.
MAX_ID_CHARS: Final[int] = 64

WIND_DOWN_HEADING: Final[str] = "WIND-DOWN: background tasks are reported as running."

#: The stop line the note offers. ``{count}`` is the number reported running.
SUGGESTED_STOP_LINE: Final[str] = (
    "STOPPING BECAUSE: {count} background tasks are still running; "
    "their completion notices resume this session."
)

_TASK_STATUS_KEY: Final[str] = "status"
_TASK_ID_KEY: Final[str] = "id"
_TASK_RUNNING: Final[str] = "running"
_SAFE_ID_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9._:@/-]+")


@dataclass(frozen=True)
class RunningTasks:
    """How many tasks the payload reports as running, and the ids safe to echo."""

    count: int
    ids: tuple[str, ...]


def _safe_id(value: object) -> str | None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        return None
    return value[:MAX_ID_CHARS]


def running_background_ids(hook_input: Mapping[str, Any]) -> RunningTasks | None:
    """The running background tasks this Stop payload reports, or None for none or unknown."""
    tasks = hook_input.get(HookInputField.BACKGROUND_TASKS)
    if not isinstance(tasks, list):
        return None
    count = 0
    ids: list[str] = []
    for task in tasks:
        if not isinstance(task, dict) or task.get(_TASK_STATUS_KEY) != _TASK_RUNNING:
            continue
        count += 1
        task_id = _safe_id(task.get(_TASK_ID_KEY))
        if task_id is not None and len(ids) < MAX_LISTED_IDS:
            ids.append(task_id)
    if count == 0:
        return None
    return RunningTasks(count=count, ids=tuple(ids))


def wind_down_note(running: RunningTasks) -> str:
    """The note appended to a no-reason stop refusal. Names ids only, never task text."""
    plural = "task" if running.count == 1 else "tasks"
    listed = ", ".join(f"`{task_id}`" for task_id in running.ids)
    unlisted = running.count - len(running.ids)
    if listed and unlisted > 0:
        listed = f"{listed} and {unlisted} more"
    named = f" ({listed})" if listed else ""
    return (
        f"{WIND_DOWN_HEADING} This stop reports {running.count} background {plural}"
        f"{named} with status `running`. If you are only letting them finish, say so "
        "and the stop passes:\n\n"
        f"    {SUGGESTED_STOP_LINE.format(count=running.count)}\n\n"
        "Do not sleep or poll for them. A finished teammate is still listed as running, "
        "so run `ListAgents` first and `TaskStop` any whose work you have already "
        "harvested; if work you could do now remains, do it instead of stopping."
    )
