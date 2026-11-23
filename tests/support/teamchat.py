"""Synthetic ``teamchat whoami --json`` outputs for the role probe (Plan 00631).

ASSUMED SHAPE, to be reconciled with fedora-desktop's merged JSON. The shape
below comes from the coordinator's summary of fedora-desktop Plan 00209's
seat-kinds proposal, which this repository cannot read: per held seat, the
fields ``team``, ``handle``, ``role`` and ``duty``, and no secrets. The
top-level ``v`` version key and the ``seats`` wrapper are this plan's guess.
When the real JSON lands, change these fixtures first and let the tests say
what the parser must change.

Handles and teams are synthetic. No fixture carries a real roster, address or
room id: the tracker is public.
"""

from __future__ import annotations

import json
from typing import Any, Final


def _dump(document: Any) -> str:
    return json.dumps(document)


def seat(team: str, role: Any, *, handle: str = "", duty: Any = "work") -> dict[str, Any]:
    """One seat row as whoami is assumed to print it."""
    row: dict[str, Any] = {"team": team, "role": role, "duty": duty}
    row["handle"] = handle or f"@example.1+local.container:{team}.test"
    return row


def whoami(*rows: dict[str, Any], version: Any = 1, **extra: Any) -> str:
    """A whoami document: ``{"v": version, "seats": [...], **extra}``."""
    document: dict[str, Any] = {"v": version, "seats": list(rows), **extra}
    return _dump(document)


WORKER_ONLY: Final[str] = whoami(seat("alpha", "worker"))
COORDINATOR_ONLY: Final[str] = whoami(seat("alpha", "coordinator"))
#: Coordinator in one team, worker in another: roles are per team.
MULTI_TEAM: Final[str] = whoami(seat("alpha", "coordinator"), seat("beta", "worker"))
#: A role this daemon attaches no behaviour to (declared roles are an open set).
UNKNOWN_ROLE: Final[str] = whoami(seat("alpha", "deployer", duty="host"))
#: A future version this parser has never seen.
FUTURE_VERSION: Final[str] = whoami(seat("alpha", "coordinator"), version=99)
#: Unknown fields at every level, including one named like a secret.
EXTRA_FIELDS: Final[str] = _dump(
    {
        "v": 1,
        "generated_ms": 1,
        "token": "SYNTHETIC-SECRET-VALUE",
        "seats": [
            {**seat("alpha", "coordinator"), "liveness": "live", "token": "SYNTHETIC-SECRET-VALUE"}
        ],
    }
)
#: Two rows for one team that disagree on the role.
CONFLICTING_ROWS: Final[str] = whoami(seat("alpha", "coordinator"), seat("alpha", "worker"))
NO_SEATS: Final[str] = whoami()
NOT_JSON: Final[str] = "teamchat: not a json document"
SEATS_NOT_A_LIST: Final[str] = _dump({"v": 1, "seats": {"team": "alpha"}})
ROW_WITHOUT_TEAM: Final[str] = _dump({"v": 1, "seats": [{"role": "coordinator"}]})
ROLE_NOT_A_STRING: Final[str] = whoami(seat("alpha", ["coordinator"]))
ROLE_WITH_CONTROL_CHARACTERS: Final[str] = whoami(seat("alpha", "coord\ninator"))
