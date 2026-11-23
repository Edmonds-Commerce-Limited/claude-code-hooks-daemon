"""Which teamchat teams this session holds a seat in, and its role and duty in each (Plan 00631).

The ONE module that knows where seat facts come from. Every role-aware
behaviour (umbrella Plan 00630) asks this module and nothing else, so a change
in teamchat's contract touches this file only. teamchat v2 is the only source:
there is no other bus generation, adapter or fallback here.

The source is ``$TEAMCHAT_KIT/bin/teamchat whoami --json`` run with the
session's ``TEAMCHAT_RUNTIME`` (DESIGN.md sections 3-6). The contract::

    {"v": 1, "teams": [{"team", "handle", "role", "duty"}]}

``v`` is required; unknown keys are ignored and never stored. Exit 69 means
"no session here" (outside a session, or before the seat link exists).

Three states, kept apart in the types because they mean different things:

- ``ABSENT``: no team. No ``TEAMCHAT_RUNTIME`` (nothing runs, nothing is
  logged), detection off, ``whoami`` exit 69, or an empty ``teams`` list.
  Today's behaviour, unchanged.
- ``UNRESOLVED``: a team is signalled but the probe gave no answer
  (``TEAMCHAT_KIT`` unset, binary missing, timeout, exit 65 or any other
  non-zero, malformed JSON, unknown ``v``). Role and duty are unknown and
  guards stay armed, so a broken probe can never silently disarm a seat.
- ``RESOLVED``: the per-team seats ``whoami`` declared.

Role and duty are PER TEAM; there is no session-wide role. Role is the wire
set ``coordinator | worker | probe`` (``null`` is unknown); a well-formed role
outside it is carried as declared and switches nothing on. Duty is an open set
(``null`` is unknown). Team, role and duty names are compared stripped and
case folded (:func:`normalise_name`); a name with odd characters is unknown.
A coordinator role stands only beside a readable duty that is not ``host``:
a host duty, an unreadable one, or rows that disagree make it unknown, so a
seat that is (or might be) a host is never a coordinator here. Rows for one
team merge to the most restrictive reading (see ``_merge``).

Invariant 5: nothing under teamchat's seat store, state root or run directory
is opened or statted; the only act is running the binary. Log lines carry a
reason category only, never the command's output, which is untrusted.
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
from typing import TYPE_CHECKING, Final

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.constants.protocol import HookInputField

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import TeamSeatConfig

_LOGGER = logging.getLogger(__name__)

RUNTIME_ENV_VAR: Final[str] = "TEAMCHAT_RUNTIME"
KIT_ENV_VAR: Final[str] = "TEAMCHAT_KIT"
WHOAMI_ARGS: Final[tuple[str, ...]] = ("whoami", "--json")
SUPPORTED_VERSIONS: Final[frozenset[int]] = frozenset({1})
DEFAULT_TTL_SECONDS: Final[float] = 60.0
#: ``whoami`` exit code: no session here (outside one, or before the seat link).
EXIT_NO_SESSION: Final[int] = 69
#: ``whoami`` exit code: the seat could not be read or failed strict decode.
EXIT_UNREADABLE: Final[int] = 65
#: The value :meth:`SeatContext.role_in` / ``duty_in`` give when unreadable.
UNKNOWN: Final[str] = "unknown"
#: Most ``whoami`` output read or parsed; more reads as unknown (review F1/F5).
MAX_OUTPUT_BYTES: Final[int] = 64 * 1024
#: Deepest container nesting decoded. The contract needs 3; extra keys get slack.
MAX_JSON_DEPTH: Final[int] = 32
#: The only daemon environment variables the probe subprocess inherits (review
#: F3): enough to locate an interpreter, a home and the per-user runtime dir.
PROBE_ENV_ALLOWLIST: Final[tuple[str, ...]] = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "XDG_RUNTIME_DIR",
)
ROLE_COORDINATOR: Final[str] = "coordinator"
DUTY_HOST: Final[str] = "host"

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
    NO_RUNTIME_SIGNAL = "no_runtime_signal"
    DETECTION_OFF = "detection_off"
    NO_SESSION = "no_session"
    NO_TEAMS = "no_teams"
    KIT_MISSING = "kit_missing"
    SIGNAL_NOT_A_PATH = "signal_not_a_path"
    COMMAND_NOT_FOUND = "command_not_found"
    COMMAND_TIMEOUT = "command_timeout"
    SEAT_UNREADABLE = "seat_unreadable"
    COMMAND_FAILED = "command_failed"
    NOT_JSON = "not_json"
    OUTPUT_TOO_LARGE = "output_too_large"
    VERSION_MISMATCH = "version_mismatch"
    SHAPE_MISMATCH = "shape_mismatch"


class RoleKind(StrEnum):
    """The kind of answer :meth:`SeatContext.role_for_team` gives."""

    NO_TEAM = "no_team"  # session is in no team: no behaviour change
    NO_SEAT = "no_seat"  # resolved, and this team is not one of the session's
    UNKNOWN = "unknown"  # a team is signalled but this role could not be read
    DECLARED = "declared"  # teamchat declared a role


class CommandStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    EXITED = "exited"  # ran and exited non-zero; ``exit_code`` says how


@dataclass(frozen=True)
class CommandOutcome:
    status: CommandStatus
    stdout: str = ""
    exit_code: int | None = None


#: ``(argv, env_overlay, timeout_seconds) -> outcome``. Never raises.
CommandRunner = Callable[[Sequence[str], Mapping[str, str], float], CommandOutcome]


@dataclass(frozen=True)
class SessionSignals:
    """The session's teamchat environment, as stamped on the payload or read in-session.

    ``runtime`` is passed to the subprocess only, never opened. An empty
    ``runtime`` means no team.
    """

    runtime: str = ""
    kit: str = ""

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> SessionSignals:
        """Read the signals from ``environ`` (the SESSION's, never the daemon's own)."""
        return cls(
            runtime=environ.get(RUNTIME_ENV_VAR, "").strip(),
            kit=environ.get(KIT_ENV_VAR, "").strip(),
        )

    @classmethod
    def from_hook_input(cls, hook_input: object) -> SessionSignals:
        """Read the signals the transport stamped on a payload; never raises.

        A non-dict payload or a non-string value reads as unset.
        """
        if not isinstance(hook_input, dict):
            return cls()
        runtime = hook_input.get(HookInputField.TEAMCHAT_RUNTIME)
        kit = hook_input.get(HookInputField.TEAMCHAT_KIT)
        return cls(
            runtime=runtime.strip() if isinstance(runtime, str) else "",
            kit=kit.strip() if isinstance(kit, str) else "",
        )


@dataclass(frozen=True)
class TeamSeat:
    """One team as declared. ``role``/``duty`` are ``""`` when unreadable."""

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
    #: Teams ``whoami`` listed more than once (an advisory condition).
    duplicate_teams: tuple[str, ...] = ()

    @classmethod
    def absent(cls, reason: ProbeReason) -> SeatContext:
        return cls(SeatState.ABSENT, reason)

    @classmethod
    def unresolved(cls, reason: ProbeReason) -> SeatContext:
        return cls(SeatState.UNRESOLVED, reason)

    def teams_held(self) -> tuple[str, ...]:
        return tuple(seat.team for seat in self.seats)

    def _seat(self, team: str) -> TeamSeat | None:
        """The seat for ``team``, matched in :func:`normalise_name` form."""
        wanted = normalise_name(team)
        if not wanted:
            return None
        for seat in self.seats:
            if seat.team == wanted:
                return seat
        return None

    def role_for_team(self, team: str) -> TeamRoleAnswer:
        if self.state is SeatState.ABSENT:
            return TeamRoleAnswer(team, RoleKind.NO_TEAM)
        if self.state is SeatState.UNRESOLVED:
            return TeamRoleAnswer(team, RoleKind.UNKNOWN)
        seat = self._seat(team)
        if seat is None:
            return TeamRoleAnswer(team, RoleKind.NO_SEAT)
        return TeamRoleAnswer(team, seat.role_kind, seat.role, seat.duty)

    def role_in(self, team: str) -> str | None:
        """The role in ``team``: a name, :data:`UNKNOWN`, or None when no seat there."""
        answer = self.role_for_team(team)
        if answer.kind is RoleKind.DECLARED:
            return answer.role
        if answer.kind is RoleKind.UNKNOWN:
            return UNKNOWN
        return None

    def duty_in(self, team: str) -> str | None:
        """The duty in ``team``: a name, :data:`UNKNOWN`, or None when no seat there."""
        if self.state is SeatState.ABSENT:
            return None
        if self.state is SeatState.UNRESOLVED:
            return UNKNOWN
        seat = self._seat(team)
        if seat is None:
            return None
        return seat.duty or UNKNOWN

    def any_duty(self, value: str) -> bool:
        """Whether any held team declares duty ``value``. Unknown is never a match."""
        wanted = value.casefold()
        return any(seat.duty and seat.duty.casefold() == wanted for seat in self.seats)

    def duty_unknown(self) -> bool:
        """Whether a team is signalled but some duty could not be read."""
        if self.state is SeatState.UNRESOLVED:
            return True
        return any(not seat.duty for seat in self.seats)


# --- parsing -----------------------------------------------------------------


def normalise_name(value: object) -> str:
    """A team, role or duty name in its one comparable form, or ``""`` (unknown).

    Surrounding whitespace is stripped and case folded. A value that then fails
    the plain token grammar (null, a non-string, odd characters) is ``""``.
    """
    if not isinstance(value, str):
        return ""
    stripped = value.strip()
    if _NAME.fullmatch(stripped):
        return stripped.casefold()
    return ""


def _handle(value: object) -> str:
    if isinstance(value, str) and _HANDLE.fullmatch(value):
        return value
    return ""


@dataclass(frozen=True)
class _Row:
    team: str
    role: str  # "" == unknown
    handle: str
    duty: str  # "" == unknown


def _rows(document: object) -> list[object] | ProbeReason:
    """The seat rows of ``document``, or why there are none we can trust."""
    if not isinstance(document, dict):
        return ProbeReason.SHAPE_MISMATCH
    version = document.get("v")
    if isinstance(version, bool) or version not in SUPPORTED_VERSIONS:
        return ProbeReason.VERSION_MISMATCH
    teams = document.get("teams")
    if not isinstance(teams, list):
        return ProbeReason.SHAPE_MISMATCH
    return teams


def _row(raw: object) -> _Row | ProbeReason:
    if not isinstance(raw, dict):
        return ProbeReason.SHAPE_MISMATCH
    team = normalise_name(raw.get("team"))
    if not team:
        # A row we cannot attribute to a team could be any team's: the whole
        # answer becomes unknown rather than silently dropping it.
        return ProbeReason.SHAPE_MISMATCH
    return _Row(
        team,
        normalise_name(raw.get("role")),
        _handle(raw.get("handle")),
        normalise_name(raw.get("duty")),
    )


def _merged_duty(duties: set[str]) -> str:
    """Host if any row says host; else the one agreed duty; else unknown."""
    if DUTY_HOST in duties:
        return DUTY_HOST
    return duties.pop() if len(duties) == 1 else ""


def _merge(team: str, rows: list[_Row]) -> TeamSeat:
    """One team's rows -> one seat, at the most restrictive reading.

    Restrictiveness, most first: ``host > unknown > worker > coordinator``.

    - Duty: any row declaring host makes the team host. Otherwise an
      unreadable duty on any row, or rows that disagree, is unknown.
    - Role: an unreadable role on any row, or rows that disagree, is unknown.
      A conflict is itself an unknown reading, and unknown outranks both
      worker and coordinator, so coordinator-plus-worker rows are unknown.
    - A coordinator stands only with a positively readable duty that is not
      host; anything else reads as unknown, so a seat whose duty is (or might
      be) host is never a coordinator here.
    """
    roles = {row.role for row in rows}
    duties = {row.duty for row in rows}
    handles = {row.handle for row in rows}
    duty = _merged_duty(duties)
    handle = handles.pop() if len(handles) == 1 else ""
    role = roles.pop() if len(roles) == 1 else ""
    coordinator_unproven = role == ROLE_COORDINATOR and duty in ("", DUTY_HOST)
    if not role or coordinator_unproven:
        return TeamSeat(team, RoleKind.UNKNOWN, "", handle, duty)
    return TeamSeat(team, RoleKind.DECLARED, role, handle, duty)


def _nesting_exceeds(text: str, limit: int) -> bool:
    """Whether ``text`` opens more than ``limit`` JSON containers at once.

    Brackets inside string literals do not count. Checked before decoding so a
    hostile document can never drive the recursive decoder to its limit.
    """
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > limit:
                return True
        elif char in "]}":
            depth -= 1
    return False


def parse_whoami(text: str) -> SeatContext:
    """Parse ``teamchat whoami --json`` output (exit 0). Never raises.

    Oversized output, a document nested past :data:`MAX_JSON_DEPTH` and any
    decoder failure (including ``RecursionError``) all read as unknown.
    """
    if len(text) > MAX_OUTPUT_BYTES:
        return SeatContext.unresolved(ProbeReason.OUTPUT_TOO_LARGE)
    if _nesting_exceeds(text, MAX_JSON_DEPTH):
        return SeatContext.unresolved(ProbeReason.NOT_JSON)
    try:
        document: object = json.loads(text)
    except (ValueError, RecursionError, MemoryError) as exc:
        # json.JSONDecodeError is a ValueError; the text itself is not logged.
        _LOGGER.debug("teamchat seat probe: output not decodable (%s)", type(exc).__name__)
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
        return SeatContext.absent(ProbeReason.NO_TEAMS)
    seats = tuple(_merge(team, team_rows) for team, team_rows in by_team.items())
    duplicates = tuple(team for team, team_rows in by_team.items() if len(team_rows) > 1)
    return SeatContext(SeatState.RESOLVED, ProbeReason.RESOLVED, seats, duplicates)


# --- default runner --------------------------------------------------------------


def probe_environment(env_overlay: Mapping[str, str]) -> dict[str, str]:
    """The probe subprocess's environment: an allowlist, then ``env_overlay``.

    Only :data:`PROBE_ENV_ALLOWLIST` is copied from the daemon's own
    environment. The daemon may have been started inside a teamchat session,
    so any ``TEAMCHAT_*`` it inherited belongs to some OTHER seat; the only
    teamchat variable the probe sees is the one the resolver deliberately sets
    in ``env_overlay`` (``TEAMCHAT_RUNTIME``).
    """
    env = {name: os.environ[name] for name in PROBE_ENV_ALLOWLIST if name in os.environ}
    env.update(env_overlay)
    return env


def default_command_runner(
    args: Sequence[str], env_overlay: Mapping[str, str], timeout: float
) -> CommandOutcome:
    """Run ``args`` (no shell) in :func:`probe_environment` of ``env_overlay``."""
    env = probe_environment(env_overlay)
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
        return CommandOutcome(CommandStatus.NOT_FOUND)
    if completed.returncode != 0:
        return CommandOutcome(CommandStatus.EXITED, exit_code=completed.returncode)
    return CommandOutcome(CommandStatus.OK, completed.stdout, 0)


# --- probe -----------------------------------------------------------------------


def whoami_argv(kit: str) -> tuple[str, ...]:
    """The argv for ``whoami``: the kit's own binary, never a bare name from PATH."""
    return (f"{kit.rstrip('/')}/bin/teamchat", *WHOAMI_ARGS)


def _from_outcome(outcome: CommandOutcome) -> SeatContext:
    if outcome.status is CommandStatus.OK:
        return parse_whoami(outcome.stdout)
    if outcome.status is CommandStatus.NOT_FOUND:
        return SeatContext.unresolved(ProbeReason.COMMAND_NOT_FOUND)
    if outcome.status is CommandStatus.TIMEOUT:
        return SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
    if outcome.exit_code == EXIT_NO_SESSION:
        return SeatContext.absent(ProbeReason.NO_SESSION)
    if outcome.exit_code == EXIT_UNREADABLE:
        return SeatContext.unresolved(ProbeReason.SEAT_UNREADABLE)
    return SeatContext.unresolved(ProbeReason.COMMAND_FAILED)


def _probe(signals: SessionSignals, runner: CommandRunner, timeout: float) -> SeatContext:
    if not signals.kit:
        return SeatContext.unresolved(ProbeReason.KIT_MISSING)
    if not (signals.runtime.startswith("/") and signals.kit.startswith("/")):
        return SeatContext.unresolved(ProbeReason.SIGNAL_NOT_A_PATH)
    outcome = runner(whoami_argv(signals.kit), {RUNTIME_ENV_VAR: signals.runtime}, timeout)
    return _from_outcome(outcome)


def probe_seat_context(
    signals: SessionSignals,
    *,
    detection_enabled: bool = True,
    runner: CommandRunner = default_command_runner,
    timeout: float = Timeout.TEAMCHAT_WHOAMI,
) -> SeatContext:
    """Resolve the seat context for the session whose signals are ``signals``.

    Never raises. No ``TEAMCHAT_RUNTIME`` costs one string check and logs nothing.
    """
    if not signals.runtime:
        return SeatContext.absent(ProbeReason.NO_RUNTIME_SIGNAL)
    if not detection_enabled:
        return SeatContext.absent(ProbeReason.DETECTION_OFF)
    context = _probe(signals, runner, timeout)
    if context.state is SeatState.UNRESOLVED:
        _LOGGER.info("teamchat seat probe: role unknown (%s)", context.reason.value)
    return context


class SeatContextResolver:
    """:func:`probe_seat_context` behind a short per-session TTL cache.

    Roles can change while a session runs, so an answer is reused for at most
    ``ttl_seconds``: a role change takes effect within one TTL. Every answer is
    cached, including no-answer and exit 69, so a missing binary costs one
    timeout per TTL, not one per hook call.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        runner: CommandRunner = default_command_runner,
        timeout: float = Timeout.TEAMCHAT_WHOAMI,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._runner = runner
        self._timeout = timeout
        self._lock = threading.Lock()
        self._cache: dict[SessionSignals, tuple[float, SeatContext]] = {}
        self._detection_enabled = True

    @classmethod
    def from_config(
        cls,
        config: TeamSeatConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
        runner: CommandRunner = default_command_runner,
    ) -> SeatContextResolver:
        """A resolver honouring the ``team_seat`` config block's TTL and detection."""
        resolver = cls(ttl_seconds=float(config.resolve_ttl_seconds), clock=clock, runner=runner)
        resolver._detection_enabled = config.detection_enabled
        return resolver

    def resolve(
        self, signals: SessionSignals, *, detection_enabled: bool | None = None
    ) -> SeatContext:
        if detection_enabled is None:
            detection_enabled = self._detection_enabled
        if not signals.runtime or not detection_enabled:
            return probe_seat_context(signals, detection_enabled=detection_enabled)
        now = self._clock()
        with self._lock:
            cached = self._cache.get(signals)
        if cached is not None and now - cached[0] < self._ttl:
            return cached[1]
        context = probe_seat_context(signals, runner=self._runner, timeout=self._timeout)
        with self._lock:
            self._cache[signals] = (now, context)
        return context
