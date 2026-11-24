"""Read a GitHub CI state from ``gh`` output already printed (Plan 00636 Task 2.3, s5).

The coordinator retrospective (00630 DESIGN.md section 19, s5) recorded a run
GitHub reported as "queued" being told to the team as stuck. Queued means no
runner has picked the run up yet, which is normal for a while; it becomes
"stuck" only once it has waited past a threshold. This module tells the two
apart from the output a ``gh`` command already printed. It runs no command and
makes no network call: the reading is only as fresh as that output.

Readable shapes (``gh`` 2.105, non-TTY):

- ``gh run list``: nine tab-separated columns, status first and the current
  attempt's start time (``startedAt``, ISO 8601, UTC) last.
- ``--json`` output of ``gh run list`` / ``gh run view``: objects carrying
  ``status`` and ``startedAt`` or ``createdAt``. A re-run keeps the first
  attempt's ``createdAt`` and moves ``startedAt`` (checked on real runs), so
  the age is taken from ``startedAt`` and falls back to ``createdAt`` only
  when ``startedAt`` is missing or unreadable.
- ``gh pr checks`` (rows or ``--json``): its ``pending`` bucket folds queued and
  running checks together, so it can never say which; the reading points at the
  ``gh run list --json`` command that can.

Unknown stays unknown: a queued run whose start time is missing,
unparseable, zone-less, before 2000 (a Go zero time) or in the future (a
readable future ``startedAt`` is never replaced by ``createdAt``), a
not-started status other than
``queued``, and output reshaped by ``--jq`` / ``--template`` are UNKNOWN, never
"queued, fine" and never "stuck".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from claude_code_hooks_daemon.utils.simple_commands import simple_commands

_GH: Final[str] = "gh"
_RESHAPE_OPTIONS: Final[frozenset[str]] = frozenset({"--jq", "-q", "--template", "-t"})
_RESHAPE_SHORT_OPTIONS: Final[tuple[str, ...]] = ("-q", "-t")
_JSON_OPTION: Final[str] = "--json"
_REPO_SHORT: Final[str] = "-R"
_REPO_LONG: Final[str] = "--repo"
_REPO_FLAGS: Final[frozenset[str]] = frozenset({_REPO_SHORT, _REPO_LONG})
#: gh marshals an unset Go time.Time as 0001-01-01; no real run predates this year.
_EARLIEST_YEAR: Final[int] = 2000
_LABEL_MAX_CHARS: Final[int] = 120
_ELLIPSIS: Final[str] = "..."

#: Statuses GitHub gives a run that no runner has started.
_QUEUED: Final[str] = "queued"
_NOT_STARTED_DETAIL: Final[dict[str, str]] = {
    "pending": "is pending (not yet queued for a runner)",
    "requested": "is requested (not yet queued for a runner)",
    "waiting": "is waiting on an environment approval or protection rule, not on a runner",
}
_RUN_LIST_COLUMNS: Final[int] = 9
_RUN_STATUS_COLUMN: Final[int] = 0
_RUN_WORKFLOW_COLUMN: Final[int] = 3
_RUN_ID_COLUMN: Final[int] = 6
_RUN_CREATED_COLUMN: Final[int] = 8
_CHECK_MIN_COLUMNS: Final[int] = 2
_CHECK_NAME_COLUMN: Final[int] = 0
_CHECK_BUCKET_COLUMN: Final[int] = 1
_PENDING_BUCKET: Final[str] = "pending"
_KNOWN_RUN_STATUSES: Final[frozenset[str]] = frozenset(
    {_QUEUED, "in_progress", "completed", *_NOT_STARTED_DETAIL}
)
_NOT_STARTED_WORD: Final[re.Pattern[str]] = re.compile(
    r"\b(queued|pending|requested|waiting)\b", re.IGNORECASE
)
_SECONDS_PER_MINUTE: Final[int] = 60
_RESHAPED_LABEL: Final[str] = "reshaped output"
_SPLIT_COMMAND: Final[str] = (
    "gh run list --branch <branch> --json databaseId,workflowName,status,startedAt,createdAt"
)


class CiCommandKind(StrEnum):
    """A ``gh`` command whose output this module can read (or knows it cannot)."""

    RUN_LIST = "run_list"
    RUN_VIEW_JSON = "run_view_json"
    PR_CHECKS = "pr_checks"
    RESHAPED = "reshaped"


class CiState(StrEnum):
    """What the output says about a run that has not finished starting."""

    QUEUED = "queued"
    STUCK = "stuck"
    PENDING_UNSPLIT = "pending_unsplit"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CiReading:
    """One run or check the output shows as not started (or not readable)."""

    state: CiState
    label: str
    run_id: str = ""
    age_seconds: int | None = None
    detail: str = ""


def _skip_repo_flags(operands: tuple[str, ...]) -> tuple[str, ...] | None:
    """``operands`` past any leading ``-R``/``--repo`` flag; None for another leading flag.

    Only the repo flag is skipped because its value arity is known. Any other
    leading flag (``--hostname h``) might or might not take a value, so the noun
    cannot be located without guessing; that command is left unrecognised
    (the advisory is silent, never wrong).
    """
    index = 0
    while index < len(operands) and operands[index].startswith("-"):
        word = operands[index]
        if word in _REPO_FLAGS:
            index += 2
        elif word.startswith(f"{_REPO_LONG}=") or (
            word.startswith(_REPO_SHORT) and len(word) > len(_REPO_SHORT)
        ):
            index += 1
        else:
            return None
    return operands[index:]


def _is_reshape_option(word: str) -> bool:
    """``--jq x``, ``--jq=x``, ``-q x`` or an attached ``-q.`` / ``-t{{.}}``."""
    if word in _RESHAPE_OPTIONS or word.split("=", 1)[0] in _RESHAPE_OPTIONS:
        return True
    return any(
        word.startswith(short) and len(word) > len(short) for short in _RESHAPE_SHORT_OPTIONS
    )


def ci_commands(command: str) -> list[CiCommandKind]:
    """The CI-reading ``gh`` commands ``command`` runs, in order.

    ``gh`` must be in command position (``echo "gh run list"`` is no reading).
    The text form of ``gh run view`` has no status column and is not read.
    A leading ``-R``/``--repo`` is skipped to find the noun (see
    ``_skip_repo_flags`` for why other leading flags are not).
    """
    kinds: list[CiCommandKind] = []
    for run in simple_commands(command, known_verbs=frozenset({_GH})):
        if run.verb != _GH:
            continue
        operands = _skip_repo_flags(run.operands)
        if operands is None or len(operands) < 2:
            continue
        noun, verb = operands[0], operands[1]
        options = set(operands[2:])
        reshaped = any(_is_reshape_option(word) for word in options)
        json_output = any(
            word == _JSON_OPTION or word.startswith(f"{_JSON_OPTION}=") for word in options
        )
        kind: CiCommandKind | None = None
        if (noun, verb) == ("run", "list"):
            kind = CiCommandKind.RUN_LIST
        elif (noun, verb) == ("run", "view") and json_output:
            kind = CiCommandKind.RUN_VIEW_JSON
        elif (noun, verb) == ("pr", "checks"):
            kind = CiCommandKind.PR_CHECKS
        if kind is not None:
            kinds.append(CiCommandKind.RESHAPED if reshaped else kind)
    return kinds


def _parse_time(value: object) -> datetime | None:
    """A zone-aware ISO 8601 time from year 2000 on; None when unreadable.

    A Go zero time (``0001-01-01T00:00:00Z``, how gh marshals an unset time) or
    any earlier-than-2000 value is no real run time and is unreadable.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.year < _EARLIEST_YEAR:
        return None
    return parsed


def _parse_created(value: object, now: datetime) -> int | None:
    """Age in seconds of an ISO 8601 creation time; None when unreadable or in the future."""
    created = _parse_time(value)
    if created is None:
        return None
    age = int((now - created).total_seconds())
    return age if age >= 0 else None


def _label(value: object, default: str) -> str:
    """``value`` as a bounded label; ``default`` when it is not a non-empty string."""
    if not isinstance(value, str) or not value:
        return default
    if len(value) <= _LABEL_MAX_CHARS:
        return value
    return value[: _LABEL_MAX_CHARS - len(_ELLIPSIS)] + _ELLIPSIS


def _run_reading(
    status: str, label: str, run_id: str, created: object, now: datetime, threshold: int
) -> CiReading | None:
    """The reading for one run, or None when it has started (running or done)."""
    if status in _NOT_STARTED_DETAIL:
        return CiReading(CiState.UNKNOWN, label, run_id, detail=_NOT_STARTED_DETAIL[status])
    if status != _QUEUED:
        return None
    age = _parse_created(created, now)
    if age is None:
        return CiReading(
            CiState.UNKNOWN, label, run_id, detail="is queued, but its creation time is unreadable"
        )
    state = CiState.STUCK if age >= threshold else CiState.QUEUED
    return CiReading(state, label, run_id, age_seconds=age)


def _run_id(value: object) -> str:
    """A run id from an int or digit string; empty for anything else."""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.isdigit():
        return value[:_LABEL_MAX_CHARS]
    return ""


def _json_readings(data: object, now: datetime, threshold: int) -> list[CiReading]:
    items = data if isinstance(data, list) else [data]
    readings: list[CiReading] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        bucket = item.get("bucket")
        if bucket == _PENDING_BUCKET:
            readings.append(CiReading(CiState.PENDING_UNSPLIT, _label(item.get("name"), "check")))
            continue
        status = item.get("status")
        if not isinstance(status, str):
            continue
        run_id = _run_id(item.get("databaseId"))
        name = _label(item.get("workflowName"), "") or _label(item.get("name"), "run")
        label = f"{name} #{run_id}" if run_id else name
        started = item.get("startedAt")
        # A readable startedAt is this attempt's, even when it is ahead of the clock
        # (skew): it is aged as such (a future time reads UNKNOWN), never replaced by
        # the first attempt's createdAt, which would read a fresh re-run as STUCK.
        since = started if _parse_time(started) is not None else item.get("createdAt")
        reading = _run_reading(status.lower(), label, run_id, since, now, threshold)
        if reading is not None:
            readings.append(reading)
    return readings


def _row_readings(output: str, now: datetime, threshold: int) -> list[CiReading]:
    readings: list[CiReading] = []
    for line in output.splitlines():
        columns = line.split("\t")
        if len(columns) == _RUN_LIST_COLUMNS and columns[_RUN_STATUS_COLUMN] in _KNOWN_RUN_STATUSES:
            run_id = _run_id(columns[_RUN_ID_COLUMN])
            name = _label(columns[_RUN_WORKFLOW_COLUMN], "run")
            label = f"{name} #{run_id}" if run_id else name
            reading = _run_reading(
                columns[_RUN_STATUS_COLUMN],
                label,
                run_id,
                columns[_RUN_CREATED_COLUMN],
                now,
                threshold,
            )
            if reading is not None:
                readings.append(reading)
        elif (
            len(columns) >= _CHECK_MIN_COLUMNS and columns[_CHECK_BUCKET_COLUMN] == _PENDING_BUCKET
        ):
            readings.append(
                CiReading(CiState.PENDING_UNSPLIT, _label(columns[_CHECK_NAME_COLUMN], "check"))
            )
    return readings


def read_ci_output(
    output: str, *, now: datetime, stuck_after_seconds: int, reshaped: bool = False
) -> list[CiReading]:
    """Every not-started run or pending check ``output`` shows.

    Args:
        output: The stdout a ``gh`` CI command printed.
        now: The current time (timezone-aware), injected so tests are exact.
        stuck_after_seconds: A queued run at or past this age is STUCK.
        reshaped: The output was reshaped by ``--jq``/``--template``; no shape is
            trusted, and any not-started word gives one UNKNOWN reading.

    Returns:
        The readings in output order; empty when nothing is waiting to start.
    """
    if reshaped:
        if _NOT_STARTED_WORD.search(output):
            return [
                CiReading(
                    CiState.UNKNOWN,
                    _RESHAPED_LABEL,
                    detail="was reshaped by --jq/--template, so its status and age are not read",
                )
            ]
        return []
    stripped = output.strip()
    if stripped[:1] in ("[", "{"):
        try:
            data = json.loads(stripped)
        except (ValueError, RecursionError):
            # Not JSON (or nested past the parser's depth): read it as rows instead.
            return _row_readings(output, now, stuck_after_seconds)
        return _json_readings(data, now, stuck_after_seconds)
    return _row_readings(output, now, stuck_after_seconds)


def _minutes(seconds: int) -> int:
    return seconds // _SECONDS_PER_MINUTE


def _line(reading: CiReading, threshold_minutes: int) -> str:
    if reading.state is CiState.QUEUED:
        return (
            f"- {reading.label}: QUEUED {_minutes(reading.age_seconds or 0)} min. GitHub has not "
            f"given it a runner yet; under the {threshold_minutes} min threshold this is "
            "normal waiting, not stuck."
        )
    if reading.state is CiState.STUCK:
        return (
            f"- {reading.label}: STUCK, queued {_minutes(reading.age_seconds or 0)} min (threshold "
            f"{threshold_minutes} min). Check why no runner took it before saying so: "
            f"`gh run view {reading.run_id or '<run-id>'} --json "
            "databaseId,status,attempt,startedAt,createdAt,jobs` (runner labels, "
            "a concurrency group, an outage)."
        )
    if reading.state is CiState.PENDING_UNSPLIT:
        return (
            f"- {reading.label}: PENDING. `gh pr checks` folds queued and running together, so "
            f"this output cannot tell queued from stuck; `{_SPLIT_COMMAND}` can."
        )
    return f"- {reading.label}: UNKNOWN. It {reading.detail}; this is evidence of neither queued nor stuck."


def render_ci_readings(readings: list[CiReading], *, stuck_after_seconds: int) -> str:
    """The advisory text for ``readings``; empty when there are none."""
    if not readings:
        return ""
    threshold_minutes = _minutes(stuck_after_seconds)
    lines = [
        "CI STATE READING (from the output above; a reading, not a verification anyone can cite):",
        *(_line(reading, threshold_minutes) for reading in readings),
        "Never tell the team what another seat's code does, or why its CI is red or stuck, "
        "without asking that seat on the bus first.",
    ]
    return "\n".join(lines)
