"""Background-process harvester core (Plan 00142, Layer B).

Pure, process-free logic for the ``harvest-background`` CLI subcommand. Parses
``ps`` output into :class:`ProcessRecord`s and evaluates them against resource
budgets to surface RUNAWAYS — long-lived, CPU-pinning, or orphaned child
processes like the ``ugrep -rl … /`` that ran ~115 min at >1000% CPU in the
incident behind this plan.

**The harvester NEVER kills.** It detects and reports a breach with a
ready-to-run ``kill -- -<pgid>`` command; the *agent* decides whether to reap,
scope down, or justify keeping the process (owner steer: every kill decision
belongs to the reasoning loop, see Plan 00142 Decision 1).

Budget model:

- **CPU breach** (applies to ALL processes, so reparented orphans are caught
  even when nothing was tracked at spawn): ``%CPU >= max_cpu_percent`` sustained
  for at least ``min_cpu_runtime_seconds``. The min-runtime gate stops a
  momentary compile spike from being flagged.
- **Wall-TTL breach** (applies ONLY to ``tracked_pgids`` — process groups the
  agent registered as backgrounded): ``elapsed >= max_wall_seconds``. Scoping
  this to tracked groups avoids nagging about legitimate long-lived processes
  (dev servers, system daemons) that were never registered.
"""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404 - used only to call the trusted system ``ps`` with fixed args
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# A non-negative integer or simple decimal (for the %CPU column). Used to
# validate ``ps`` columns up front so parsing skips the header/junk rows WITHOUT
# exception-driven control flow.
_FLOAT_RE: Final[re.Pattern[str]] = re.compile(r"\d+(?:\.\d+)?")

# ``ps`` column order the CLI requests; the harvester parses exactly these.
PS_FORMAT: Final[str] = "pid,pgid,etimes,pcpu,args"


@dataclass(frozen=True)
class ProcessRecord:
    """A single process as reported by ``ps``."""

    pid: int
    pgid: int
    etimes: int
    pcpu: float
    args: str


@dataclass(frozen=True)
class Breach:
    """A process that exceeded a resource budget — surfaced, never killed."""

    record: ProcessRecord
    reasons: tuple[str, ...]

    @property
    def kill_command(self) -> str:
        """The command the AGENT may run to reap the whole process group.

        Targets the process GROUP (``-<pgid>``), not just the pid, because the
        incident runaway was a ``bash -c`` parent with a ``ugrep`` child —
        killing one leaks the other.
        """
        return f"kill -- -{self.record.pgid}"


def parse_ps_output(text: str) -> list[ProcessRecord]:
    """Parse ``ps -eo pid,pgid,etimes,pcpu,args`` output into records.

    The header line and any malformed/blank lines are skipped. ``args`` (the
    final column) may contain spaces and is preserved verbatim.
    """
    records: list[ProcessRecord] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(maxsplit=4)
        if len(parts) < 5:
            continue
        pid_s, pgid_s, etimes_s, pcpu_s, args = parts
        # Validate the numeric columns up front so the header row
        # ("PID PGID ELAPSED %CPU COMMAND") and any junk are skipped without
        # relying on exception-driven control flow.
        if not (
            pid_s.isdigit()
            and pgid_s.isdigit()
            and etimes_s.isdigit()
            and _FLOAT_RE.fullmatch(pcpu_s)
        ):
            continue
        records.append(
            ProcessRecord(
                pid=int(pid_s),
                pgid=int(pgid_s),
                etimes=int(etimes_s),
                pcpu=float(pcpu_s),
                args=args,
            )
        )
    return records


def find_breaches(
    records: Iterable[ProcessRecord],
    *,
    max_wall_seconds: int,
    max_cpu_percent: float,
    min_cpu_runtime_seconds: int,
    tracked_pgids: Iterable[int] = (),
    exclude_pgids: Iterable[int] = (),
) -> list[Breach]:
    """Return the processes that breached a budget (CPU runaway or tracked TTL).

    Args:
        records: Parsed process records.
        max_wall_seconds: Wall-time TTL applied to tracked process groups.
        max_cpu_percent: Sustained %CPU ceiling (e.g. 400 == 4 cores).
        min_cpu_runtime_seconds: Minimum elapsed time before a CPU breach counts
            (filters momentary spikes).
        tracked_pgids: Process groups the agent registered as backgrounded; only
            these are eligible for the wall-TTL breach.
        exclude_pgids: Process groups to never flag (e.g. the harvester's own).

    Returns:
        A list of :class:`Breach`, one per breaching process, never killing.
    """
    tracked = set(tracked_pgids)
    excluded = set(exclude_pgids)
    breaches: list[Breach] = []
    for record in records:
        if record.pgid in excluded:
            continue
        reasons: list[str] = []
        if record.pcpu >= max_cpu_percent and record.etimes >= min_cpu_runtime_seconds:
            reasons.append(
                f"{record.pcpu:.0f}% CPU sustained for {record.etimes}s "
                f"(ceiling {max_cpu_percent:.0f}%)"
            )
        if record.pgid in tracked and record.etimes >= max_wall_seconds:
            reasons.append(f"tracked process running {record.etimes}s (TTL {max_wall_seconds}s)")
        if reasons:
            breaches.append(Breach(record=record, reasons=tuple(reasons)))
    return breaches


def read_tracked_pgids(state_file: Path) -> list[int]:
    """Read process-group ids recorded in the tracker's JSONL state file.

    Each line is a JSON object; lines carrying an integer ``pgid`` contribute it.
    A missing file yields ``[]``. Malformed lines are skipped explicitly (not
    blanket-suppressed) — the state file is best-effort and a corrupt line must
    not abort the whole harvest.
    """
    if not state_file.exists():
        return []
    pgids: list[int] = []
    for line in state_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        pgid = record.get("pgid") if isinstance(record, dict) else None
        if isinstance(pgid, int):
            pgids.append(pgid)
    return pgids


def build_report(
    records: Iterable[ProcessRecord],
    *,
    max_wall_seconds: int,
    max_cpu_percent: float,
    min_cpu_runtime_seconds: int,
    tracked_pgids: Iterable[int] = (),
    exclude_pgids: Iterable[int] = (),
) -> dict[str, Any]:
    """Evaluate budgets and build a report dict for the ``harvest-background`` CLI.

    Returns a dict with ``has_breaches`` (bool), ``breaches`` (JSON-serialisable
    list), and ``text`` (human-readable report). The caller chooses whether to
    print ``text`` or the ``breaches`` JSON. The report only SUGGESTS
    ``kill -- -<pgid>`` commands — it never performs or reports a kill.
    """
    breaches = find_breaches(
        records,
        max_wall_seconds=max_wall_seconds,
        max_cpu_percent=max_cpu_percent,
        min_cpu_runtime_seconds=min_cpu_runtime_seconds,
        tracked_pgids=tracked_pgids,
        exclude_pgids=exclude_pgids,
    )
    serialised = [
        {
            "pid": b.record.pid,
            "pgid": b.record.pgid,
            "etimes": b.record.etimes,
            "pcpu": b.record.pcpu,
            "args": b.record.args,
            "reasons": list(b.reasons),
            "kill_command": b.kill_command,
        }
        for b in breaches
    ]

    if not breaches:
        text = "NO RUNAWAYS DETECTED — all sampled processes are within budget."
    else:
        lines = [
            f"⚠️ {len(breaches)} runaway process group(s) detected. "
            "The daemon does NOT kill — review each and decide:",
            "",
        ]
        for b in breaches:
            lines.append(
                f"  PID {b.record.pid} (PGID {b.record.pgid})  "
                f"{b.record.pcpu:.0f}% CPU  {b.record.etimes}s"
            )
            lines.append(f"    cmd: {b.record.args}")
            for reason in b.reasons:
                lines.append(f"    breach: {reason}")
            lines.append(f"    reap whole group (if not a wanted long task): {b.kill_command}")
            lines.append('    keep it: record KEEP_RUNNING_BECAUSE="reason" and move on')
            lines.append("")
        text = "\n".join(lines).rstrip()

    return {"has_breaches": bool(breaches), "breaches": serialised, "text": text}


def run_ps() -> str:
    """Return ``ps`` output for harvesting (the only impure part).

    SECURITY (B603/B607): invoked as an argument list with no shell, calling the
    trusted system ``ps`` binary with a fixed, non-user-controlled format. No
    untrusted input is interpolated.
    """
    completed = subprocess.run(  # nosec B603 B607 - trusted ps, fixed args, no shell
        ["ps", "-eo", PS_FORMAT],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout
