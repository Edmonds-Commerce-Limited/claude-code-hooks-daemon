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
unreadable and :meth:`TeamchatOwnerWaitBus.flags_readable` False; the guard's
``on_unreadable_bus`` option decides what that means (default ``auto``: allow
with an advisory here, refuse once an adapter reports flags readable). It
never opens teamchat's seat store, state root or run directory, and never
reads a password file. Replace :meth:`read` once teamchat documents a JSON
history carrying the notify flag and the thread relation.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from claude_code_hooks_daemon.utils.owner_wait_check import BusSnapshot, printable_thread_id
from claude_code_hooks_daemon.utils.teamchat_seat import SessionSignals

#: The R11 multi-thread bump (unverified: relayed, not yet seen in a teamchat build).
BUMP_PROGRAM: Final[str] = "teamchat bump"
#: v1's notifying thread post (``pingbus thread --help``: ``--ask`` mentions the humans).
NOTIFY_PROGRAM: Final[str] = "pingbus thread"
#: The team slot of a template when the seat probe named no team (left for the coordinator).
TEAM_PLACEHOLDER: Final[str] = "<team>"
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

    def notify_commands(self, team: str) -> tuple[str, str]:
        """The notifying reply, as templates: (open question asked, owner-started message)."""
        ...

    def flags_readable(self) -> bool:
        """Whether this adapter can read the notify flag and thread relation at all.

        ``on_unreadable_bus: auto`` refuses an unreadable wait only when this is
        True; where it is False (pingbus v1) a refusal could never be satisfied.
        """
        ...


class TeamchatOwnerWaitBus:
    """The production adapter (see the module docstring for what is unverified)."""

    def read(self, team: str, signals: SessionSignals) -> BusSnapshot | BusUnreadable:
        """Unreadable until teamchat documents the fields; runs nothing."""
        return BusUnreadable(NO_HISTORY_CONTRACT)

    def flags_readable(self) -> bool:
        """False: no verified history contract carries the notify flag yet (v1)."""
        return False

    def bump_command(self, team: str, thread_ids: Sequence[str]) -> str:
        """``teamchat bump --team <team> <ids>``; ``--waiting`` when an id is not safe to print.

        ``--team`` is always named, so a seat coordinating two teams gets one
        distinct command per team rather than two identical ones.
        """
        prefix = f"{BUMP_PROGRAM} --team {_shown_team(team)}"
        printable = [printable_thread_id(thread_id) for thread_id in thread_ids]
        if not printable or any(item is None for item in printable):
            return f"{prefix} --waiting"
        return " ".join([prefix, *(item for item in printable if item is not None)])

    def notify_commands(self, team: str) -> tuple[str, str]:
        """v1 ``pingbus thread ... --ask`` (``--ask`` mentions the humans, so Element notifies).

        Templates, not runnable lines: the guard could not read which threads
        are open, so ``Q<n>`` and ``<event id>`` are left for the coordinator.
        """
        prefix = f"{NOTIFY_PROGRAM} --team {_shown_team(team)}"
        return (f"{prefix} Q<n> --ask", f"{prefix} --re <event id> --ask")


def _shown_team(team: str) -> str:
    """``team`` shell-quoted, or the placeholder left as a template slot."""
    return team if team == TEAM_PLACEHOLDER else shlex.quote(team)
