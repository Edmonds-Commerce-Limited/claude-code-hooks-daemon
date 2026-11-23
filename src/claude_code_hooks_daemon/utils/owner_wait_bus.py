"""The one adapter between ``owner_wait_stop_guard`` and the team bus (Plan 00636 Task 2.1a).

00630 DESIGN.md 20 puts every bus read and the bump command behind one
adapter, so a change in teamchat's contract touches this file only.

Status of the contract (unverified here, Plan 00636 Task 1.2):

- ``pingbus history --help`` (v1) lists only ``--team``, ``--limit`` and
  ``--room``; no per-entry notify flag, author kind or ``m.thread`` relation
  is documented, and there is no machine-readable output.
- teamchat v2 history and ``teamchat bump`` (fedora-desktop request 00209
  R11) are relayed text only; no teamchat binary is in this checkout.

So :meth:`TeamchatOwnerWaitBus.read` runs nothing and reports the history
unreadable, which the guard treats as fail-open with a loud log line. It
never opens teamchat's seat store, state root or run directory, and never
reads a password file. Replace :meth:`read` once teamchat documents a JSON
history carrying the notify flag and the thread relation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from claude_code_hooks_daemon.utils.owner_wait_check import BusSnapshot, printable_thread_id
from claude_code_hooks_daemon.utils.teamchat_seat import SessionSignals

#: The R11 multi-thread bump (unverified: relayed, not yet seen in a teamchat build).
BUMP_PROGRAM: Final[str] = "teamchat bump"
#: R11's form that bumps every open thread the seat asked.
BUMP_ALL_WAITING: Final[str] = f"{BUMP_PROGRAM} --waiting"
NO_HISTORY_CONTRACT: Final[str] = (
    "no teamchat history contract exposing the notify flag and the m.thread relation "
    "is verified yet (Plan 00636 Task 1.2), so the questions history is unverified "
    "and is not read"
)


@dataclass(frozen=True)
class BusUnreadable:
    """The history could not be read. ``reason`` is a category, never bus text."""

    reason: str


class OwnerWaitBus(Protocol):
    """What the guard needs from the bus."""

    def read(self, team: str, signals: SessionSignals) -> BusSnapshot | BusUnreadable:
        """The questions room's threads and posts for ``team``, as this seat sees them."""
        ...

    def bump_command(self, team: str, thread_ids: Sequence[str]) -> str:
        """The ONE command that re-pings every thread in ``thread_ids``, notifying."""
        ...


class TeamchatOwnerWaitBus:
    """The production adapter (see the module docstring for what is unverified)."""

    def read(self, team: str, signals: SessionSignals) -> BusSnapshot | BusUnreadable:
        """Unreadable until teamchat documents the fields; runs nothing."""
        return BusUnreadable(NO_HISTORY_CONTRACT)

    def bump_command(self, team: str, thread_ids: Sequence[str]) -> str:
        """``teamchat bump <ids>``; ``--waiting`` when an id is not safe to print."""
        printable = [printable_thread_id(thread_id) for thread_id in thread_ids]
        if not printable or any(item is None for item in printable):
            return BUMP_ALL_WAITING
        return " ".join([BUMP_PROGRAM, *(item for item in printable if item is not None)])
