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
  Through :class:`SeatContextResolver` this state needs positive evidence
  (owner ruling D3): only a session that resolved a seat earlier stays
  UNRESOLVED; one that never did reads ABSENT (``TEAM_UNCONFIRMED``), because
  the runtime variable alone does not prove a team.
- ``RESOLVED``: the per-team seats ``whoami`` declared.

Role and duty are PER TEAM; there is no session-wide role. Role is the wire
set ``coordinator | worker | probe`` (``null`` is unknown); a well-formed role
outside it is carried as declared and switches nothing on. Duty is an open,
OPTIONAL set: ``null``, an absent key or an unreadable value is undeclared and
arms nothing (owner ruling D1). Team, role and duty names are compared
stripped and case folded (:func:`normalise_name`); a role with odd characters
is unknown. A coordinator role stands unless a row declares duty ``host`` (D2),
so a host seat is never a coordinator here. Rows for one team merge to the
most restrictive reading (see ``_merge``).

Invariant 5: nothing under teamchat's seat store, state root or run directory
is opened or statted; the only act is running the binary. Log lines carry a
reason category only, never the command's output, which is untrusted.
"""

from __future__ import annotations

import json
import logging
import os
import re
import selectors
import signal
import stat
import subprocess  # nosec B404 - fixed argv list, no shell
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core.relevance import Relevance
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to
from claude_code_hooks_daemon.utils.safe_signal import (
    RefusedSignalTarget,
    signal_own_session_group,
)

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import TeamSeatConfig
    from claude_code_hooks_daemon.core.relevance import RelevanceContext

_LOGGER = logging.getLogger(__name__)

RUNTIME_ENV_VAR: Final[str] = "TEAMCHAT_RUNTIME"
KIT_ENV_VAR: Final[str] = "TEAMCHAT_KIT"
WHOAMI_ARGS: Final[tuple[str, ...]] = ("whoami", "--json")
SUPPORTED_VERSIONS: Final[frozenset[int]] = frozenset({1})
DEFAULT_TTL_SECONDS: Final[float] = 60.0
#: Most sessions :class:`SeatContextResolver` remembers at once (review F8).
MAX_CACHE_ENTRIES: Final[int] = 256
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
    KIT_UNTRUSTED = "kit_untrusted"
    COMMAND_NOT_FOUND = "command_not_found"
    COMMAND_TIMEOUT = "command_timeout"
    SEAT_UNREADABLE = "seat_unreadable"
    COMMAND_FAILED = "command_failed"
    NOT_JSON = "not_json"
    OUTPUT_TOO_LARGE = "output_too_large"
    VERSION_MISMATCH = "version_mismatch"
    SHAPE_MISMATCH = "shape_mismatch"
    #: The probe gave no answer and this session never resolved a seat (D3).
    TEAM_UNCONFIRMED = "team_unconfirmed"


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
    TOO_LARGE = "too_large"  # stdout passed MAX_OUTPUT_BYTES; the group was killed
    UNTRUSTED = "untrusted"  # binary relative, outside its kit, or world-writable


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
        """Whether a team is signalled but the probe gave no answer at all.

        Duty is a teams-only, optional field: in a RESOLVED seat a null, absent
        or unreadable duty is undeclared and arms nothing (owner ruling D1).
        """
        return self.state is SeatState.UNRESOLVED


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
    duty: str  # "" == undeclared or unreadable
    #: A non-null duty that fails the grammar: it might be a garbled ``host``.
    duty_malformed: bool = False


def _rows(document: object) -> list[object] | ProbeReason:
    """The seat rows of ``document``, or why there are none we can trust."""
    if not isinstance(document, dict):
        return ProbeReason.SHAPE_MISMATCH
    version = document.get("v")
    # ``type() is int``: a bool or a float (``1.0 == 1``) is not a version.
    if type(version) is not int or version not in SUPPORTED_VERSIONS:
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
    raw_duty = raw.get("duty")
    duty = normalise_name(raw_duty)
    return _Row(
        team,
        normalise_name(raw.get("role")),
        _handle(raw.get("handle")),
        duty,
        duty_malformed=raw_duty is not None and not duty,
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
    - A coordinator stands unless a row declares duty host, or carries a
      malformed duty that might be a garbled host (review F2). Duty is
      optional (owner ruling D2), so a null or absent duty does not unmake a
      coordinator; a host seat is never one here.
    """
    roles = {row.role for row in rows}
    duties = {row.duty for row in rows}
    handles = {row.handle for row in rows}
    duty = _merged_duty(duties)
    handle = handles.pop() if len(handles) == 1 else ""
    role = roles.pop() if len(roles) == 1 else ""
    maybe_host = duty == DUTY_HOST or any(row.duty_malformed for row in rows)
    coordinator_unproven = role == ROLE_COORDINATOR and maybe_host
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


class _DuplicateKeyError(Exception):
    """An object in ``whoami`` output repeats a key (review F4)."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document = dict(pairs)
    if len(document) != len(pairs):
        raise _DuplicateKeyError
    return document


def decode_json_document(text: str, *, max_bytes: int = MAX_OUTPUT_BYTES) -> object | ProbeReason:
    """Strictly decode one teamchat CLI JSON answer, or say why not. Never raises.

    Text longer than ``max_bytes`` characters, a document nested past
    :data:`MAX_JSON_DEPTH`, a repeated key and any decoder failure (including
    ``RecursionError``) are each a reason, never a partial document. A caller
    decoding its own file names its own cap; CLI output keeps the runner's.
    """
    if len(text) > max_bytes:
        return ProbeReason.OUTPUT_TOO_LARGE
    if _nesting_exceeds(text, MAX_JSON_DEPTH):
        return ProbeReason.NOT_JSON
    try:
        document: object = json.loads(text, object_pairs_hook=_unique_keys)
    except _DuplicateKeyError:
        # json keeps the LAST duplicate silently, so a repeated key could change
        # the answer; a document that says two things is no answer.
        return ProbeReason.SHAPE_MISMATCH
    except (ValueError, RecursionError, MemoryError) as exc:
        # json.JSONDecodeError is a ValueError; the text itself is not logged.
        _LOGGER.debug("teamchat CLI: output not decodable (%s)", type(exc).__name__)
        return ProbeReason.NOT_JSON
    return document


def parse_whoami(text: str) -> SeatContext:
    """Parse ``teamchat whoami --json`` output (exit 0). Never raises.

    Anything :func:`decode_json_document` refuses reads as unknown.
    """
    document = decode_json_document(text)
    if isinstance(document, ProbeReason):
        return SeatContext.unresolved(document)
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


def _binary_trust(binary: str) -> CommandStatus | None:
    """Why ``binary`` (``<kit>/bin/<name>``) must not run, or None when it may.

    Review F6: the binary must be absolute, must resolve (symlinks followed) to
    a path inside its own kit, and neither it, its directory nor the kit may be
    world-writable. A missing binary is NOT_FOUND.
    """
    given = Path(binary)
    if not given.is_absolute():
        return CommandStatus.UNTRUSTED
    real_binary = given.resolve()
    real_kit = given.parent.parent.resolve()
    if not path_is_relative_to(real_binary, real_kit):
        return CommandStatus.UNTRUSTED
    for path in (real_binary, real_binary.parent, real_kit):
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            return CommandStatus.NOT_FOUND
        except OSError as exc:
            _LOGGER.debug("teamchat seat probe: kit not inspectable (%s)", type(exc).__name__)
            return CommandStatus.UNTRUSTED
        if mode & stat.S_IWOTH:
            return CommandStatus.UNTRUSTED
    return None


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    """SIGKILL ``process``'s whole group, then reap the leader.

    Called only before the leader is reaped, so the group id is still its own
    even when the leader has already exited and a grandchild holds the pipe.
    A refused target is logged and the caller still answers TIMEOUT.
    """
    try:
        signal_own_session_group(process, signal.SIGKILL)
    except ProcessLookupError as exc:
        log_and_continue(
            _LOGGER,
            exc,
            reason="teamchat seat probe: process group already gone, only the reap remains",
            level=logging.DEBUG,
        )
    except RefusedSignalTarget as exc:
        log_and_continue(
            _LOGGER,
            exc,
            reason="teamchat seat probe: group kill refused, the caller still answers TIMEOUT",
            level=logging.DEBUG,
        )
    process.wait()


def _read_capped(process: subprocess.Popen[bytes], deadline: float) -> bytes | CommandStatus:
    """Stdout up to EOF, or TIMEOUT at ``deadline``, or TOO_LARGE past the cap."""
    stdout = process.stdout
    if stdout is None:  # pragma: no cover - Popen was given stdout=PIPE
        return b""
    chunks: list[bytes] = []
    size = 0
    with selectors.DefaultSelector() as selector:
        selector.register(stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                return CommandStatus.TIMEOUT
            chunk = os.read(stdout.fileno(), MAX_OUTPUT_BYTES + 1 - size)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_OUTPUT_BYTES:
                return CommandStatus.TOO_LARGE


def default_command_runner(
    args: Sequence[str], env_overlay: Mapping[str, str], timeout: float
) -> CommandOutcome:
    """Run ``args`` (no shell) in :func:`probe_environment` of ``env_overlay``.

    ``args[0]`` must pass :func:`_binary_trust` first, or nothing runs.

    Review F5: the command gets no stdin (``/dev/null``) and no terminal, runs
    in its own session, and its stdout is read to :data:`MAX_OUTPUT_BYTES`
    only. On timeout or over-cap output the whole process group is killed, so
    no grandchild outlives the probe.
    """
    deadline = time.monotonic() + timeout
    refused = _binary_trust(args[0]) if args else CommandStatus.NOT_FOUND
    if refused is not None:
        return CommandOutcome(refused)
    try:
        process = subprocess.Popen(  # nosec B603 - fixed argv, no shell
            list(args),
            env=probe_environment(env_overlay),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        return CommandOutcome(CommandStatus.NOT_FOUND)
    except OSError as exc:
        _LOGGER.debug("teamchat seat probe: command could not start (%s)", type(exc).__name__)
        return CommandOutcome(CommandStatus.NOT_FOUND)
    with process:
        output = _read_capped(process, deadline)
        if isinstance(output, CommandStatus):
            _kill_group(process)
            return CommandOutcome(output)
        try:
            returncode = process.wait(max(deadline - time.monotonic(), 0.0))
        except subprocess.TimeoutExpired:
            _kill_group(process)
            return CommandOutcome(CommandStatus.TIMEOUT)
    if returncode != 0:
        return CommandOutcome(CommandStatus.EXITED, exit_code=returncode)
    return CommandOutcome(CommandStatus.OK, output.decode("utf-8", errors="replace"), 0)


# --- probe -----------------------------------------------------------------------


def kit_argv(kit: str, args: Sequence[str]) -> tuple[str, ...]:
    """The argv for a teamchat verb: the kit's own binary, never a bare name from PATH."""
    return (f"{kit.rstrip('/')}/bin/teamchat", *args)


def whoami_argv(kit: str) -> tuple[str, ...]:
    """The argv for ``whoami``."""
    return kit_argv(kit, WHOAMI_ARGS)


def _from_outcome(outcome: CommandOutcome) -> SeatContext:
    if outcome.status is CommandStatus.OK:
        return parse_whoami(outcome.stdout)
    if outcome.status is CommandStatus.NOT_FOUND:
        return SeatContext.unresolved(ProbeReason.COMMAND_NOT_FOUND)
    if outcome.status is CommandStatus.TIMEOUT:
        return SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
    if outcome.status is CommandStatus.TOO_LARGE:
        return SeatContext.unresolved(ProbeReason.OUTPUT_TOO_LARGE)
    if outcome.status is CommandStatus.UNTRUSTED:
        return SeatContext.unresolved(ProbeReason.KIT_UNTRUSTED)
    if outcome.exit_code == EXIT_NO_SESSION:
        return SeatContext.absent(ProbeReason.NO_SESSION)
    if outcome.exit_code == EXIT_UNREADABLE:
        return SeatContext.unresolved(ProbeReason.SEAT_UNREADABLE)
    return SeatContext.unresolved(ProbeReason.COMMAND_FAILED)


def _is_plain_absolute(path: str) -> bool:
    """Absolute, already normal (no ``..``, ``.`` or ``//``), no control characters.

    A trailing ``/`` is allowed. Review F6: the kit names the binary that runs.
    """
    trimmed = path.rstrip("/")
    if not trimmed.startswith("/") or any(ord(char) < 0x20 or char == "\x7f" for char in path):
        return False
    return os.path.normpath(trimmed) == trimmed


def run_kit_command(
    signals: SessionSignals,
    args: Sequence[str],
    *,
    runner: CommandRunner,
    timeout: float,
) -> CommandOutcome | ProbeReason:
    """Run ``$TEAMCHAT_KIT/bin/teamchat <args>`` for the session ``signals`` describe.

    The only environment the command gets from the session is its
    ``TEAMCHAT_RUNTIME``. A missing kit, or a runtime or kit that is not a
    plain absolute path, runs nothing and answers the reason. Never raises.
    """
    if not signals.kit:
        return ProbeReason.KIT_MISSING
    if not (_is_plain_absolute(signals.runtime) and _is_plain_absolute(signals.kit)):
        return ProbeReason.SIGNAL_NOT_A_PATH
    return runner(kit_argv(signals.kit, args), {RUNTIME_ENV_VAR: signals.runtime}, timeout)


def _probe(signals: SessionSignals, runner: CommandRunner, timeout: float) -> SeatContext:
    outcome = run_kit_command(signals, WHOAMI_ARGS, runner=runner, timeout=timeout)
    if isinstance(outcome, ProbeReason):
        return SeatContext.unresolved(outcome)
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

    The cache holds at most ``max_entries`` sessions. Storing a new session in
    a full cache first drops every expired answer, then the oldest live one.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        runner: CommandRunner = default_command_runner,
        timeout: float = Timeout.TEAMCHAT_WHOAMI,
        max_entries: int = MAX_CACHE_ENTRIES,
    ) -> None:
        if max_entries < 1:
            raise ValueError(f"max_entries must be at least 1, got {max_entries}")
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._clock = clock
        self._runner = runner
        self._timeout = timeout
        self._lock = threading.Lock()
        self._cache: dict[SessionSignals, tuple[float, SeatContext]] = {}
        #: Runtimes that resolved a seat, oldest first; outlives the TTL cache.
        self._confirmed: dict[str, None] = {}
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
        context = self._confirmed_reading(
            signals, probe_seat_context(signals, runner=self._runner, timeout=self._timeout)
        )
        self._store(signals, now, context)
        return context

    def _confirmed_reading(self, signals: SessionSignals, context: SeatContext) -> SeatContext:
        """Arm on evidence (owner ruling D3), remembered per session runtime.

        A resolved seat confirms the session is in a team; a definitive no-team
        answer clears that. A probe with no answer stays UNRESOLVED (armed) only
        for a confirmed session; otherwise it reads as no team, with one log line.
        """
        runtime = signals.runtime
        with self._lock:
            if context.state is SeatState.RESOLVED:
                self._confirmed.pop(runtime, None)
                self._confirmed[runtime] = None
                while len(self._confirmed) > self._max_entries:
                    del self._confirmed[next(iter(self._confirmed))]
                return context
            if context.state is SeatState.ABSENT:
                self._confirmed.pop(runtime, None)
                return context
            confirmed = runtime in self._confirmed
        if confirmed:
            return context
        _LOGGER.info(
            "teamchat seat probe: no answer (%s) and no seat resolved yet this session; "
            "treated as no team",
            context.reason.value,
        )
        return SeatContext.absent(ProbeReason.TEAM_UNCONFIRMED)

    def team_confirmed(self, signals: SessionSignals) -> bool:
        """Whether this session (by runtime) resolved a seat and has not since left."""
        with self._lock:
            return bool(signals.runtime) and signals.runtime in self._confirmed

    def confirmed_count(self) -> int:
        """How many sessions are remembered as confirmed team seats."""
        with self._lock:
            return len(self._confirmed)

    def cache_size(self) -> int:
        """How many sessions the cache currently holds."""
        with self._lock:
            return len(self._cache)

    def _store(self, signals: SessionSignals, now: float, context: SeatContext) -> None:
        """Cache one answer, evicting to stay within ``max_entries``, under the lock."""
        with self._lock:
            if signals not in self._cache and len(self._cache) >= self._max_entries:
                expired = [
                    key for key, (stamp, _) in self._cache.items() if now - stamp >= self._ttl
                ]
                for key in expired:
                    del self._cache[key]
                while len(self._cache) >= self._max_entries:
                    oldest = min(self._cache, key=lambda key: self._cache[key][0])
                    del self._cache[oldest]
            self._cache[signals] = (now, context)


_SHARED_LOCK: Final[threading.Lock] = threading.Lock()
_SHARED: dict[tuple[float, bool], SeatContextResolver] = {}


def shared_resolver(config: TeamSeatConfig | None) -> SeatContextResolver:
    """The ONE resolver for a ``team_seat`` config, shared by every team handler (R4).

    One ``whoami`` per session per TTL instead of one per handler, and one
    memory of which sessions resolved a seat (D3). ``None`` is the defaults.
    """
    from claude_code_hooks_daemon.config.models import TeamSeatConfig

    resolved = config if config is not None else TeamSeatConfig()
    key = (float(resolved.resolve_ttl_seconds), resolved.detection_enabled)
    with _SHARED_LOCK:
        resolver = _SHARED.get(key)
        if resolver is None:
            resolver = SeatContextResolver.from_config(resolved)
            _SHARED[key] = resolver
        return resolver


def reset_shared_resolvers() -> None:
    """Forget every shared resolver (tests, and a daemon config reload)."""
    with _SHARED_LOCK:
        _SHARED.clear()


def teams_declared(config: TeamSeatConfig | None) -> bool:
    """Whether the project declares teamchat seats (Plan 00474, ruling D4).

    True only for ``team_seat.teams_in_use: true`` with detection on: with
    detection off no team handler can ever fire, so its guidance would state a
    policy the project does not have. Guidance is generated at daemon start
    with no session, so this is a static, declared fact, never a probe.
    """
    return config is not None and config.teams_in_use and config.detection_enabled


def team_seat_relevance(declared: bool) -> Relevance:
    """The relevance verdict shared by every team-only handler."""
    return Relevance.when(
        declared,
        present="the project declares teamchat seats (team_seat.teams_in_use)",
        absent="no teamchat seats declared (team_seat.teams_in_use is false or detection is off)",
    )


class TeamOnlyGuidance:
    """Mixin for a team-only handler that emits guidance (Plan 00474 R5).

    List it BEFORE the handler base so its ``get_relevance`` wins. The
    handler declares ``_team_seat`` itself (the registry injects by
    ``hasattr``), so this mixin only annotates the attribute. Guidance is
    read from the injected config; the optimise review reads the context,
    because it builds handlers bare.
    """

    _team_seat: TeamSeatConfig | None

    def guidance_relevant(self) -> bool:
        """Whether this project declares the teams this handler's guidance is for."""
        return teams_declared(self._team_seat)

    def get_relevance(self, context: RelevanceContext) -> Relevance:
        """Relevant only where the project declares teamchat seats."""
        return team_seat_relevance(context.teams_declared)
