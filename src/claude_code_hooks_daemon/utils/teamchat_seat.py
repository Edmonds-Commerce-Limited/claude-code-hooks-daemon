"""Which teamchat teams this session holds a seat in, and its role in each (Plan 00631).

The ONE module that knows where seat and role facts come from. Every
role-aware behaviour (umbrella Plan 00630) asks this module and nothing else,
so a change in teamchat's layout touches this file only. teamchat v2 is the
only source: there is no other bus generation, adapter or fallback here.

Three states, kept apart in the types because they mean different things:

- ``ABSENT``: no membership signal (or detection is off). The session is not
  in a team and nothing changes: no subprocess, no file probe, no log line.
- ``UNRESOLVED``: a membership signal is set but the facts could not be read
  (path missing or unreadable, ``teamchat`` missing, timeout, non-zero exit,
  bad JSON, unknown version or shape, no seats). Every team answers
  ``RoleKind.UNKNOWN`` and guards stay armed, so a broken state file can never
  silently disarm a seat.
- ``RESOLVED``: the per-team seats ``teamchat whoami --json`` declared.

Roles are PER TEAM and an OPEN set: a role is passed through as declared, and a
role this daemon attaches no behaviour to switches nothing on. There is no
session-wide role; callers ask :meth:`SeatContext.role_for_team` for the team
the action concerns.

The whoami JSON shape is ASSUMED (``{"v": 1, "seats": [{"team", "handle",
"role", "duty"}]}``) until fedora-desktop's merged shape is read; the fixtures in
``tests/support/teamchat.py`` carry the same caveat. Parsing is tolerant:
unknown fields are ignored and never stored, and a version or shape this parser
does not know answers ``UNRESOLVED`` rather than raising.

Secrets: the member credential file is never opened, and the probe refuses a
membership path naming it. Log lines carry a reason category only, never the
command's output, which is untrusted and could carry anything.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess  # nosec B404 - fixed argv list, no shell
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.utils.path_predicates import path_exists

_LOGGER = logging.getLogger(__name__)

MEMBERSHIP_ENV_VAR: Final[str] = "TEAMCHAT_MEMBERSHIP"
WHOAMI_COMMAND: Final[tuple[str, ...]] = ("teamchat", "whoami", "--json")
SUPPORTED_VERSIONS: Final[frozenset[int]] = frozenset({1})
DEFAULT_TTL_SECONDS: Final[float] = 60.0
#: The member credential file's name. Named only so the probe can refuse it.
_CREDENTIAL_FILE_NAME: Final[str] = "token"

#: Team, role and duty names: untrusted text bounded to a plain token grammar.
_NAME: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
#: Handles carry ``@``, ``+`` and ``:`` (``@repo.1+local.kind:server``).
_HANDLE: Final[re.Pattern[str]] = re.compile(r"@?[A-Za-z0-9][A-Za-z0-9._@:+-]{0,127}")


class SeatState(StrEnum):
    ABSENT = "absent"
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"


class ProbeReason(StrEnum):
    """Why a :class:`SeatContext` is in its state. A category, never data."""

    RESOLVED = "resolved"
    NO_MEMBERSHIP_SIGNAL = "no_membership_signal"
    DETECTION_OFF = "detection_off"
    MEMBERSHIP_NOT_A_PATH = "membership_not_a_path"
    MEMBERSHIP_MISSING = "membership_missing"
    MEMBERSHIP_UNREADABLE = "membership_unreadable"
    CREDENTIAL_PATH_REFUSED = "credential_path_refused"
    COMMAND_NOT_FOUND = "command_not_found"
    COMMAND_TIMEOUT = "command_timeout"
    COMMAND_FAILED = "command_failed"
    NOT_JSON = "not_json"
    VERSION_MISMATCH = "version_mismatch"
    SHAPE_MISMATCH = "shape_mismatch"
    NO_SEATS = "no_seats"


class RoleKind(StrEnum):
    """The kind of answer :meth:`SeatContext.role_for_team` gives."""

    NO_TEAM = "no_team"  # session is in no team: no behaviour change
    NO_SEAT = "no_seat"  # resolved, and this team is not one of the session's
    UNKNOWN = "unknown"  # a team is configured but this role could not be read
    DECLARED = "declared"  # teamchat declared a role (any string, open set)


class CommandStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    FAILED = "failed"


class PathState(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class CommandOutcome:
    status: CommandStatus
    stdout: str = ""


#: ``(argv, env_overlay, timeout_seconds) -> outcome``. Never raises.
CommandRunner = Callable[[Sequence[str], Mapping[str, str], float], CommandOutcome]
#: ``path -> state``. Never raises; EACCES is ``UNREADABLE``, never ``MISSING``.
PathProbe = Callable[[Path], PathState]


@dataclass(frozen=True)
class TeamSeat:
    """One seat as declared. ``role`` is ``""`` when ``role_kind`` is UNKNOWN."""

    team: str
    role_kind: RoleKind
    role: str = ""
    handle: str = ""
    duty: str = ""


@dataclass(frozen=True)
class TeamRoleAnswer:
    """The answer for one team. Ask :meth:`holds_role`, not ``role ==``."""

    team: str
    kind: RoleKind
    role: str = ""
    duty: str = ""

    def holds_role(self, name: str) -> bool:
        """True only for a DECLARED role equal to ``name`` (case-insensitive)."""
        return self.kind is RoleKind.DECLARED and self.role.casefold() == name.casefold()

    @property
    def guards_armed(self) -> bool:
        """Whether a guard keyed on this team should stay on.

        A declared role or an unreadable one keeps guards armed (an unreadable
        state must never disarm a seat). No team, or no seat in this team, does
        not. What each guard does when armed is the caller's decision.
        """
        return self.kind in (RoleKind.DECLARED, RoleKind.UNKNOWN)


@dataclass(frozen=True)
class SeatContext:
    state: SeatState
    reason: ProbeReason
    seats: tuple[TeamSeat, ...] = ()

    @classmethod
    def absent(cls, reason: ProbeReason) -> SeatContext:
        return cls(SeatState.ABSENT, reason)

    @classmethod
    def unresolved(cls, reason: ProbeReason) -> SeatContext:
        return cls(SeatState.UNRESOLVED, reason)

    def teams_held(self) -> tuple[str, ...]:
        return tuple(seat.team for seat in self.seats)

    def role_for_team(self, team: str) -> TeamRoleAnswer:
        if self.state is SeatState.ABSENT:
            return TeamRoleAnswer(team, RoleKind.NO_TEAM)
        if self.state is SeatState.UNRESOLVED:
            return TeamRoleAnswer(team, RoleKind.UNKNOWN)
        for seat in self.seats:
            if seat.team == team:
                return TeamRoleAnswer(team, seat.role_kind, seat.role, seat.duty)
        return TeamRoleAnswer(team, RoleKind.NO_SEAT)


# --- parsing -----------------------------------------------------------------


def _name(value: object) -> str:
    """``value`` if it is a well-formed name, else ``""``."""
    if isinstance(value, str) and _NAME.fullmatch(value):
        return value
    return ""


def _handle(value: object) -> str:
    if isinstance(value, str) and _HANDLE.fullmatch(value):
        return value
    return ""


@dataclass(frozen=True)
class _Row:
    team: str
    role: str  # "" == unreadable
    handle: str
    duty: str


def _rows(document: object) -> list[object] | ProbeReason:
    """The seat rows of ``document``, or why there are none we can trust."""
    if isinstance(document, list):
        return document
    if not isinstance(document, dict):
        return ProbeReason.SHAPE_MISMATCH
    if "v" in document:
        version = document["v"]
        if isinstance(version, bool) or version not in SUPPORTED_VERSIONS:
            return ProbeReason.VERSION_MISMATCH
    seats = document.get("seats")
    if not isinstance(seats, list):
        return ProbeReason.SHAPE_MISMATCH
    return seats


def _row(raw: object) -> _Row | ProbeReason:
    if not isinstance(raw, dict):
        return ProbeReason.SHAPE_MISMATCH
    team = _name(raw.get("team"))
    if not team:
        # A row we cannot attribute to a team could be any team's: the whole
        # answer becomes unknown rather than silently dropping it.
        return ProbeReason.SHAPE_MISMATCH
    return _Row(team, _name(raw.get("role")), _handle(raw.get("handle")), _name(raw.get("duty")))


def _merge(team: str, rows: list[_Row]) -> TeamSeat:
    """One team's rows -> one seat. Disagreement on the role is UNKNOWN."""
    roles = {row.role for row in rows}
    duties = {row.duty for row in rows}
    handles = {row.handle for row in rows}
    duty = duties.pop() if len(duties) == 1 else ""
    handle = handles.pop() if len(handles) == 1 else ""
    if len(roles) != 1 or "" in roles:
        return TeamSeat(team, RoleKind.UNKNOWN, "", handle, duty)
    return TeamSeat(team, RoleKind.DECLARED, roles.pop(), handle, duty)


def parse_whoami(text: str) -> SeatContext:
    """Parse ``teamchat whoami --json`` output. Never raises."""
    try:
        document: object = json.loads(text)
    except ValueError:
        # json.JSONDecodeError is a ValueError; the text itself is not logged.
        return SeatContext.unresolved(ProbeReason.NOT_JSON)
    rows = _rows(document)
    if isinstance(rows, ProbeReason):
        return SeatContext.unresolved(rows)
    by_team: dict[str, list[_Row]] = {}
    for raw in rows:
        row = _row(raw)
        if isinstance(row, ProbeReason):
            return SeatContext.unresolved(row)
        by_team.setdefault(row.team, []).append(row)
    if not by_team:
        return SeatContext.unresolved(ProbeReason.NO_SEATS)
    seats = tuple(_merge(team, team_rows) for team, team_rows in by_team.items())
    return SeatContext(SeatState.RESOLVED, ProbeReason.RESOLVED, seats)


# --- default seams -------------------------------------------------------------


def default_command_runner(
    args: Sequence[str], env_overlay: Mapping[str, str], timeout: float
) -> CommandOutcome:
    """Run ``args`` (no shell) with ``env_overlay`` over the daemon's environment."""
    env = {**os.environ, **env_overlay}
    try:
        completed = subprocess.run(  # nosec B603 - fixed argv, no shell
            list(args),
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return CommandOutcome(CommandStatus.NOT_FOUND)
    except subprocess.TimeoutExpired:
        return CommandOutcome(CommandStatus.TIMEOUT)
    except OSError as exc:
        _LOGGER.debug("teamchat seat probe: command could not start (%s)", type(exc).__name__)
        return CommandOutcome(CommandStatus.FAILED)
    if completed.returncode != 0:
        return CommandOutcome(CommandStatus.FAILED)
    return CommandOutcome(CommandStatus.OK, completed.stdout)


def default_path_probe(path: Path) -> PathState:
    """EACCES-safe existence probe: an unstattable path is UNREADABLE, not MISSING."""
    answer = path_exists(path, unreadable_means=PathState.UNREADABLE)
    if isinstance(answer, PathState):
        return answer
    return PathState.PRESENT if answer else PathState.MISSING


# --- probe -----------------------------------------------------------------------

_COMMAND_REASONS: Final[Mapping[CommandStatus, ProbeReason]] = {
    CommandStatus.NOT_FOUND: ProbeReason.COMMAND_NOT_FOUND,
    CommandStatus.TIMEOUT: ProbeReason.COMMAND_TIMEOUT,
    CommandStatus.FAILED: ProbeReason.COMMAND_FAILED,
}
_PATH_REASONS: Final[Mapping[PathState, ProbeReason]] = {
    PathState.MISSING: ProbeReason.MEMBERSHIP_MISSING,
    PathState.UNREADABLE: ProbeReason.MEMBERSHIP_UNREADABLE,
}


def membership_from_environ(environ: Mapping[str, str]) -> str:
    """The membership signal in ``environ`` (``""`` when unset).

    The daemon's own environment is not the session's: pass the environment
    of the session being asked about (the payload stamp), not ``os.environ``.
    """
    return environ.get(MEMBERSHIP_ENV_VAR, "")


def _probe(
    membership: str, runner: CommandRunner, path_probe: PathProbe, timeout: float
) -> SeatContext:
    path = Path(membership)
    if not path.is_absolute():
        return SeatContext.unresolved(ProbeReason.MEMBERSHIP_NOT_A_PATH)
    if _CREDENTIAL_FILE_NAME in path.parts:
        return SeatContext.unresolved(ProbeReason.CREDENTIAL_PATH_REFUSED)
    path_state = path_probe(path)
    if path_state is not PathState.PRESENT:
        return SeatContext.unresolved(_PATH_REASONS[path_state])
    outcome = runner(WHOAMI_COMMAND, {MEMBERSHIP_ENV_VAR: membership}, timeout)
    if outcome.status is not CommandStatus.OK:
        return SeatContext.unresolved(_COMMAND_REASONS[outcome.status])
    return parse_whoami(outcome.stdout)


def probe_seat_context(
    membership: str,
    *,
    detection_enabled: bool = True,
    runner: CommandRunner = default_command_runner,
    path_probe: PathProbe = default_path_probe,
    timeout: float = Timeout.TEAMCHAT_WHOAMI,
) -> SeatContext:
    """Resolve the seat context for the session whose membership signal is ``membership``.

    Never raises. Absent costs one string check and logs nothing.
    """
    membership = membership.strip()
    if not membership:
        return SeatContext.absent(ProbeReason.NO_MEMBERSHIP_SIGNAL)
    if not detection_enabled:
        return SeatContext.absent(ProbeReason.DETECTION_OFF)
    context = _probe(membership, runner, path_probe, timeout)
    if context.state is SeatState.UNRESOLVED:
        _LOGGER.info("teamchat seat probe: role unknown (%s)", context.reason.value)
    return context


class SeatContextResolver:
    """:func:`probe_seat_context` behind a short per-membership TTL cache.

    Roles can change while a session runs, so an answer is reused for at most
    ``ttl_seconds``: a role change takes effect within one TTL. An unresolved
    answer is cached too, so a missing ``teamchat`` costs one timeout per TTL,
    not one per hook call.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        runner: CommandRunner = default_command_runner,
        path_probe: PathProbe = default_path_probe,
        timeout: float = Timeout.TEAMCHAT_WHOAMI,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._runner = runner
        self._path_probe = path_probe
        self._timeout = timeout
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, SeatContext]] = {}

    def resolve(self, membership: str, *, detection_enabled: bool = True) -> SeatContext:
        key = membership.strip()
        if not key or not detection_enabled:
            return probe_seat_context(key, detection_enabled=detection_enabled)
        now = self._clock()
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None and now - cached[0] < self._ttl:
            return cached[1]
        context = probe_seat_context(
            key, runner=self._runner, path_probe=self._path_probe, timeout=self._timeout
        )
        with self._lock:
            self._cache[key] = (now, context)
        return context
