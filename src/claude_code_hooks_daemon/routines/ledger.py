"""The per-year run ledger (Plan 00412 Task 2.3, D4/D10).

One file per year under a routine's ``RUNS/``, one row per EVENT — not per run.
That shape is forced by D10's five states, and specifically by ``failed``,
which means "started and did not finish":

- nothing can WRITE a ``failed`` row, because whatever would have written it
  died with the run. So ``failed`` is DERIVED, from a start with no terminal
  event. A ledger recording only what a run chose to say about itself could
  never report an abandoned run, and an abandoned run would read exactly like
  one that was never attempted;
- a row-per-run ledger would have to go back and EDIT the row when the run
  finished, and an append-only file that gets edited in place is just a file.

``no record`` stays outside this module, for the same reason it stays outside
:mod:`routines.intervals`: a routine that never ran has nothing here to read.
Something that knows the routine EXISTS has to assert the absence.

The on-disk form is a markdown table, because ``CLAUDE/Routine/`` is a
documentation tree that humans read. The parser therefore treats cell padding
as presentation and strips it — this project auto-aligns markdown tables on
edit, so a ledger someone has opened comes back with different whitespace and
the same data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.routines.intervals import RunInterval

#: Subdirectory of a routine folder holding the year files.
RUNS_DIRNAME: Final[str] = "RUNS"

_COLUMNS: Final[tuple[str, ...]] = ("run", "at", "event", "from", "to", "note")
_HEADER: Final[str] = "| " + " | ".join(_COLUMNS) + " |"
_DIVIDER: Final[str] = "|" + "|".join(" --- " for _ in _COLUMNS) + "|"
#: Written for an absent value. A literal dash reads as "nothing here" in the
#: rendered table, where an empty cell reads as an oversight.
_EMPTY: Final[str] = "-"


class LedgerEvent(StrEnum):
    """What a row records. The vocabulary that is WRITTEN."""

    #: A run began. Paired with a terminal event, or it derives to FAILED.
    STARTED = "started"
    #: Ran, found nothing. Recorded as distinctly as a run that found something.
    CLEAN = "clean"
    #: Ran, found something.
    FINDINGS = "findings"
    #: Deliberately not run, with the reason recorded. Covered nothing, and
    #: says so — the honest alternative to a silent absence.
    SKIPPED = "skipped"


class RunState(StrEnum):
    """What a run IS, once its events are composed. D10's vocabulary.

    ``no record`` is deliberately absent: it is the absence of a key in
    :func:`run_states`, never a value, so nothing can accidentally report a
    routine that never ran as though it had a state.
    """

    CLEAN = "clean"
    FINDINGS = "findings"
    #: Started and did not finish. Derived, never written.
    FAILED = "failed"
    SKIPPED = "skipped-with-reason"


#: Terminal events that must carry the span they covered. SKIPPED is exempt
#: because it genuinely covered nothing, which is the point of recording it.
_NEEDS_INTERVAL: Final[frozenset[LedgerEvent]] = frozenset(
    {LedgerEvent.CLEAN, LedgerEvent.FINDINGS}
)

_STATE_FOR_EVENT: Final[dict[LedgerEvent, RunState]] = {
    LedgerEvent.CLEAN: RunState.CLEAN,
    LedgerEvent.FINDINGS: RunState.FINDINGS,
    LedgerEvent.SKIPPED: RunState.SKIPPED,
}


@dataclass(frozen=True, slots=True)
class RunEvent:
    """One row: something that happened to one run, at one moment."""

    run_id: str
    event: LedgerEvent
    at: datetime
    interval: RunInterval | None = None
    note: str = ""

    def __post_init__(self) -> None:
        """Refuse a row that would be unreadable or misleading downstream.

        Raises:
            ValueError: A terminal outcome carries no interval, or a skip
                carries no reason.
        """
        if self.event in _NEEDS_INTERVAL and self.interval is None:
            raise ValueError(
                f"a {self.event} event must carry the interval it covered — "
                "a terminal row without one silently breaks gap detection"
            )
        if self.event is LedgerEvent.SKIPPED and not self.note.strip():
            raise ValueError(
                "a skipped event must carry its reason — without one this is "
                "an unexplained absence, which is what the state exists to avoid"
            )


def ledger_path(routine_dir: Path, year: int) -> Path:
    """The year file for ``year`` inside ``routine_dir``.

    Args:
        routine_dir: A scaffolded routine folder.
        year: Calendar year the events were recorded in.

    Returns:
        The path, which may not exist yet.
    """
    return routine_dir / RUNS_DIRNAME / f"{year}.md"


def append_event(routine_dir: Path, event: RunEvent) -> Path:
    """Append one row, filed under the year the event HAPPENED in.

    A run that straddles new year therefore writes its two events to two files.
    That is deliberate: filing both under the start year makes a year file a
    poor index of itself, and filing both under the end year would rewrite
    history that is supposed to be append-only.

    Args:
        routine_dir: A scaffolded routine folder.
        event: The row to write.

    Returns:
        The year file that was appended to.
    """
    path = ledger_path(routine_dir, event.at.year)
    path.parent.mkdir(parents=True, exist_ok=True)

    prelude = "" if path.exists() else f"{_HEADER}\n{_DIVIDER}\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(prelude + _render_row(event) + "\n")
    return path


def read_events(routine_dir: Path) -> list[RunEvent]:
    """Every event across every year file, oldest year first.

    Args:
        routine_dir: A scaffolded routine folder.

    Returns:
        The events in chronological order. Empty when the routine has never
        run — which is not an error, and is not the same as a state.
    """
    runs_dir = routine_dir / RUNS_DIRNAME
    if not runs_dir.is_dir():
        return []

    events: list[RunEvent] = []
    for path in sorted(runs_dir.glob("*.md")):
        events.extend(_parse_file(path))
    return events


def run_states(events: list[RunEvent]) -> dict[str, RunState]:
    """Compose events into one state per run.

    Args:
        events: Events as returned by :func:`read_events`.

    Returns:
        ``run_id -> state``. A run whose start has no terminal event is
        :data:`RunState.FAILED`. A run absent from ``events`` is absent from
        the result — never a state.
    """
    states: dict[str, RunState] = {}
    for event in events:
        if event.event is LedgerEvent.STARTED:
            states.setdefault(event.run_id, RunState.FAILED)
        else:
            states[event.run_id] = _STATE_FOR_EVENT[event.event]
    return states


def next_run_id(events: list[RunEvent], now: datetime) -> str:
    """The id for a run starting at ``now``.

    Readable and ordered rather than opaque: ``<year>-<NNN>``, so a reader can
    place a run in time without a lookup, and the year prefix disambiguates the
    sequence restarting each January.

    Args:
        events: Events as returned by :func:`read_events`.
        now: When the new run starts.

    Returns:
        The next unused id for ``now``'s year.
    """
    started_this_year = sum(
        1 for event in events if event.event is LedgerEvent.STARTED and event.at.year == now.year
    )
    return f"{now.year}-{started_this_year + 1:03d}"


def _render_row(event: RunEvent) -> str:
    """One markdown table row for ``event``."""
    from_ref = event.interval.from_ref if event.interval else _EMPTY
    to_ref = event.interval.to_ref if event.interval else _EMPTY
    cells = (
        event.run_id,
        event.at.isoformat(),
        str(event.event),
        from_ref,
        to_ref,
        event.note or _EMPTY,
    )
    return "| " + " | ".join(_escaped(cell) for cell in cells) + " |"


def _escaped(cell: str) -> str:
    """A cell value that cannot break out of its column.

    A pipe in a note would otherwise shift every later column by one, which
    corrupts the row silently rather than loudly.
    """
    return cell.replace("|", "\\|")


def _unescaped(cell: str) -> str:
    """Inverse of :func:`_escaped`."""
    return cell.replace("\\|", "|")


def _parse_file(path: Path) -> list[RunEvent]:
    """Every data row in one year file, in file order.

    Header and divider rows are skipped by shape rather than by position, so a
    file someone has annotated above the table still parses.
    """
    events: list[RunEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = _split_row(line)
        if cells is None:
            continue
        events.append(_event_from_cells(cells))
    return events


def _split_row(line: str) -> list[str] | None:
    """The stripped cells of a data row, or None when ``line`` is not one.

    Padding is presentation: this project auto-aligns markdown tables on edit,
    so a ledger a human has opened comes back with different whitespace and
    identical data.
    """
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = [cell.strip() for cell in stripped[1:-1].split("|")]
    if len(cells) != len(_COLUMNS):
        return None
    if cells[0] == _COLUMNS[0] or set(cells[0]) <= {"-", ":"}:
        return None
    return cells


def _event_from_cells(cells: list[str]) -> RunEvent:
    """Rebuild a :class:`RunEvent` from one parsed row."""
    run_id, at, event, from_ref, to_ref, note = (_unescaped(cell) for cell in cells)
    interval = (
        None
        if from_ref == _EMPTY or to_ref == _EMPTY
        else RunInterval(from_ref=from_ref, to_ref=to_ref)
    )
    return RunEvent(
        run_id=run_id,
        event=LedgerEvent(event),
        at=_parse_timestamp(at),
        interval=interval,
        note="" if note == _EMPTY else note,
    )


def _parse_timestamp(value: str) -> datetime:
    """A timezone-aware datetime from a written cell.

    A naive value is read as UTC rather than rejected: the ledger is written
    by this module, which always writes an offset, so a naive one has been
    hand-edited and the useful response is to keep reading.
    """
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
