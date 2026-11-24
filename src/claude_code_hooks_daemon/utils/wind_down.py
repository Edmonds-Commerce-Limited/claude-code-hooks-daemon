"""The wind-down note: a stop around running background agents (Plan 00636 Task 2.4, s8).

A coordinator that dispatched background agents ends turns while they run.
Each such stop without a ``STOPPING BECAUSE:`` line is refused by
``auto_continue_stop``, and the refusal never said that waiting on its own
agents is a reason it may simply declare. This module reads the Stop payload's
``background_tasks`` list and renders a note that names the running tasks and
the one stop line that clears that refusal.

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

from claude_code_hooks_daemon.utils.stop_hook_helpers import running_background_tasks

#: Most ids the note lists; the rest are counted as "and N more".
MAX_LISTED_IDS: Final[int] = 5
#: Longest id echoed into context.
MAX_ID_CHARS: Final[int] = 64

WIND_DOWN_HEADING: Final[str] = "WIND-DOWN: background tasks are reported as running."


def suggested_stop_line(count: int) -> str:
    """The stop line the note offers, singular or plural to match ``count``."""
    if count == 1:
        return (
            "STOPPING BECAUSE: 1 background task is still running; "
            "its completion notice resumes this session."
        )
    return (
        f"STOPPING BECAUSE: {count} background tasks are still running; "
        "their completion notices resume this session."
    )


_TASK_ID_KEY: Final[str] = "id"
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
    running = running_background_tasks(dict(hook_input))
    count = 0
    ids: list[str] = []
    for task in running:
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
    them = "it" if running.count == 1 else "them"
    listed = ", ".join(f"`{task_id}`" for task_id in running.ids)
    unlisted = running.count - len(running.ids)
    if listed and unlisted > 0:
        listed = f"{listed} and {unlisted} more"
    named = f" ({listed})" if listed else ""
    return (
        f"{WIND_DOWN_HEADING} This stop reports {running.count} background {plural}"
        f"{named} with status `running`. If you are only letting {them} finish, say so "
        "and this refusal clears (other stop guards such as branch_stop_guard, "
        "cron_stop_enforcer and the idle-workable gate still apply):\n\n"
        f"    {suggested_stop_line(running.count)}\n\n"
        "Do not sleep or poll for them. A finished teammate is still listed as running, "
        "so run `ListAgents` first and `TaskStop` any whose work you have already "
        "harvested; if work you could do now remains, do it instead of stopping."
    )
