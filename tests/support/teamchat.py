"""Synthetic ``teamchat whoami --json`` outputs for the role probe (Plan 00631).

The shape is fedora-desktop's merged contract (fedora-desktop.1, merged on
their v2 branch at ``fe67f23c3``; umbrella Plan 00630 DESIGN.md section 2)::

    {"v": 1, "teams": [{"team": ..., "handle": ..., "role": ..., "duty": ...}]}

``v`` is required and must be 1. ``role`` is ``coordinator | worker | probe``
or ``null``; ``duty`` is an open set (``coordinator | worker | host`` today) or
``null``. ``whoami`` exits 69 outside a session or before the seat link
exists, which means "no team here", not an error.

Handles and teams are synthetic. No fixture carries a real roster, address or
room id: the tracker is public.
"""

from __future__ import annotations

import json
from typing import Any, Final

#: ``whoami``'s exit code outside a session or before the seat link exists.
EXIT_NO_SESSION: Final[int] = 69
#: ``whoami``'s exit code for an unreadable or undecodable seat (to be confirmed).
EXIT_UNREADABLE: Final[int] = 65


def _dump(document: Any) -> str:
    return json.dumps(document)


def seat(team: str, role: Any, *, handle: str = "", duty: Any = "") -> dict[str, Any]:
    """One seat row with exactly the four contract keys.

    ``duty`` defaults to the duty matching ``role`` for a coordinator or
    worker (``coordinator`` duty equals ``role == coordinator``).
    """
    if duty == "":
        duty = role if role in ("coordinator", "worker") else None
    return {
        "team": team,
        "handle": handle or f"@example.1+local.container:{team}.test",
        "role": role,
        "duty": duty,
    }


def whoami(*rows: dict[str, Any], version: Any = 1, **extra: Any) -> str:
    """A whoami document: ``{"v": version, "teams": [...], **extra}``."""
    document: dict[str, Any] = {"v": version, "teams": list(rows), **extra}
    return _dump(document)


WORKER_ONLY: Final[str] = whoami(seat("alpha", "worker"))
COORDINATOR_ONLY: Final[str] = whoami(seat("alpha", "coordinator"))
#: Coordinator in one team, worker in another: roles are per team.
MULTI_TEAM: Final[str] = whoami(seat("alpha", "coordinator"), seat("beta", "worker"))
#: A host seat in one team, worker in another.
HOST_DUTY: Final[str] = whoami(seat("alpha", "worker", duty="host"), seat("beta", "worker"))
#: A role of ``null``: not yet known.
ROLE_NULL: Final[str] = whoami(seat("alpha", None))
#: The ``probe`` role switches nothing on.
ROLE_PROBE: Final[str] = whoami(seat("alpha", "probe"))
#: A duty this daemon has no behaviour for (duties are an open set).
UNKNOWN_DUTY: Final[str] = whoami(seat("alpha", "worker", duty="reviewer"))
#: Contradiction teamchat's ``declare check`` refuses: a host seat as coordinator.
HOST_AS_COORDINATOR: Final[str] = whoami(seat("alpha", "coordinator", duty="host"))
#: A future version this parser has never seen.
FUTURE_VERSION: Final[str] = whoami(seat("alpha", "coordinator"), version=99)
#: No version key at all.
NO_VERSION: Final[str] = _dump({"teams": [seat("alpha", "worker")]})
#: Unknown keys at every level, including one named like a secret.
EXTRA_FIELDS: Final[str] = _dump(
    {
        "v": 1,
        "generated_ms": 1,
        "password": "SYNTHETIC-SECRET-VALUE",
        "teams": [
            {
                **seat("alpha", "coordinator"),
                "liveness": "live",
                "password": "SYNTHETIC-SECRET-VALUE",
            }
        ],
    }
)
#: One team listed twice, disagreeing on the role.
CONFLICTING_ROWS: Final[str] = whoami(seat("alpha", "coordinator"), seat("alpha", "worker"))
#: Exit 0 with no seats: no team here.
NO_TEAMS: Final[str] = whoami()
NOT_JSON: Final[str] = "teamchat: not a json document"
TEAMS_NOT_A_LIST: Final[str] = _dump({"v": 1, "teams": {"team": "alpha"}})
BARE_LIST: Final[str] = _dump([seat("alpha", "worker")])
ROW_WITHOUT_TEAM: Final[str] = _dump({"v": 1, "teams": [{"role": "coordinator"}]})
ROLE_NOT_A_STRING: Final[str] = whoami(seat("alpha", ["coordinator"]))
ROLE_WITH_CONTROL_CHARACTERS: Final[str] = whoami(seat("alpha", "coord\ninator"))


# --- ``teamchat verify --team <T> <id>`` (Plan 00634) ---------------------------
#
# UNVERIFIED HERE: the questions-room ``verify`` answer is fedora-desktop issue
# 369, which this repository has not seen. The shape below is PROVISIONAL, built
# from the vet's reading of today's record (kind, sender, team, room, text; a
# human line has ``kind == "human"``) plus the ``Q<n>`` the issue promises. The
# verifier that reads it is not the production default until 369 is confirmed.

#: A synthetic questions-room event id (Matrix ids start with ``$``).
HUMAN_ID: Final[str] = "$synthetic-human-approval-0001"


def verify_answer(
    *,
    event_id: str = HUMAN_ID,
    team: str = "alpha",
    room: Any = "questions",
    kind: Any = "human",
    question: Any = "Q7",
    version: Any = 1,
    **extra: Any,
) -> str:
    """A provisional ``verify --json`` answer for one line."""
    document: dict[str, Any] = {
        "v": version,
        "id": event_id,
        "team": team,
        "room": room,
        "kind": kind,
        "sender": "@owner.synthetic:example.test",
        "q": question,
        "text": "yes, go ahead",
        **extra,
    }
    return _dump(document)
