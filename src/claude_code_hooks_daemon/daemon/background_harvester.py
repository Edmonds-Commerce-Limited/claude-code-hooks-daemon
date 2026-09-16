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
- **Wall-TTL breach** (applies ONLY to ``tracked_commands`` — the commands the
  agent registered as backgrounded): ``elapsed >= max_wall_seconds``. Scoping
  this to tracked work avoids nagging about legitimate long-lived processes
  (dev servers, system daemons) that were never registered.

Why the tracked set is keyed by COMMAND TEXT and not by pgid (Plan 00236): the
tracker is a PostToolUse handler running inside the daemon, in a different
process tree from the command it observes. It never learns a pid, so the
``pgid`` key the reader originally looked for was one no writer could ever
supply — the wall-TTL branch was dead from the day it was written. What the
tracker DOES hold is the command string, and a background Bash call reaches
``ps`` as a wrapper shell that ``eval``s that string verbatim, so the recorded
text appears in the process's ``args``. Correlating there costs nothing on the
hook path: the harvester already samples ``ps``.

The honest limit of that correlation: it resolves for ``run_in_background``
calls, whose full command survives into ``args``. A shell-``&`` command whose
parent has exited leaves only a child whose ``args`` are a fragment, so it
matches nothing and gets no wall-TTL — the same coverage it had before, with
the CPU ceiling (which applies to every process, tracked or not) still behind
it.
"""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404 - used only to call the trusted system ``ps`` with fixed args
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# A non-negative integer or simple decimal (for the %CPU column). Used to
# validate ``ps`` columns up front so parsing skips the header/junk rows WITHOUT
# exception-driven control flow.
_FLOAT_RE: Final[re.Pattern[str]] = re.compile(r"\d+(?:\.\d+)?")

# ``ps`` column order the CLI requests; the harvester parses exactly these.
#
# ``ppid`` is here because a process GROUP is not the unit of work. A shell that
# launches a background job is in its own group, and an interpreter it execs
# starts a NEW group, so the group containing the tracked process can hold only
# the idle waiter while every busy descendant sits in a sibling group. Linking
# parent to child is the only way to see the whole job.
PS_FORMAT: Final[str] = "pid,ppid,pgid,etimes,pcpu,args"


@dataclass(frozen=True)
class ProcessRecord:
    """A single process as reported by ``ps``."""

    pid: int
    ppid: int
    pgid: int
    etimes: int
    pcpu: float
    args: str


@dataclass(frozen=True)
class Breach:
    """A process that exceeded a resource budget — surfaced, never killed.

    Two fields describe the breaching process's whole DESCENDANT TREE rather
    than the process itself, because on a wall-TTL breach the process itself is
    the least informative thing in the job.

    ``tree_pcpu`` — the record's own ``pcpu`` answers the wrong question. The
    tracked process is the wrapper shell background work is launched through; it
    blocks in ``wait`` and reads 0% however hard its children are working. An
    agent deciding whether to run the suggested ``kill`` is asking whether the
    JOB is doing anything, and `0%` reads as "hung, safe to reap".

    ``tree_pgids`` — and it cannot be answered by summing the process GROUP
    either. A shell is in its own group and an interpreter it execs starts a NEW
    one, so the tracked process is routinely alone in its group while every busy
    descendant sits in a sibling group. That also makes a single ``-<pgid>``
    reap INCOMPLETE for exactly this shape: it signals the idle waiter and
    leaves the real work running and orphaned.
    """

    record: ProcessRecord
    reasons: tuple[str, ...]
    tree_pcpu: float = 0.0
    tree_pgids: tuple[int, ...] = ()

    @property
    def kill_command(self) -> str:
        """The command the AGENT may run to reap the whole job.

        Targets process GROUPS (``-<pgid>``), not bare pids, because the
        incident runaway was a ``bash -c`` parent with a ``ugrep`` child —
        killing one leaks the other. Every group the descendant tree spans is
        named, for the same reason one level up: a job that crosses a group
        boundary is still one job, and reaping half of it is the failure this
        command exists to prevent.
        """
        pgids = self.tree_pgids or (self.record.pgid,)
        return "kill -- " + " ".join(f"-{pgid}" for pgid in pgids)


def parse_ps_output(text: str) -> list[ProcessRecord]:
    """Parse ``ps -eo pid,ppid,pgid,etimes,pcpu,args`` output into records.

    The header line and any malformed/blank lines are skipped. ``args`` (the
    final column) may contain spaces and is preserved verbatim.
    """
    records: list[ProcessRecord] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(maxsplit=5)
        if len(parts) < 6:
            continue
        pid_s, ppid_s, pgid_s, etimes_s, pcpu_s, args = parts
        # Validate the numeric columns up front so the header row
        # ("PID PPID PGID ELAPSED %CPU COMMAND") and any junk are skipped
        # without relying on exception-driven control flow.
        if not (
            pid_s.isdigit()
            and ppid_s.isdigit()
            and pgid_s.isdigit()
            and etimes_s.isdigit()
            and _FLOAT_RE.fullmatch(pcpu_s)
        ):
            continue
        records.append(
            ProcessRecord(
                pid=int(pid_s),
                ppid=int(ppid_s),
                pgid=int(pgid_s),
                etimes=int(etimes_s),
                pcpu=float(pcpu_s),
                args=args,
            )
        )
    return records


def _is_tracked(args: str, tracked_commands: Iterable[str]) -> bool:
    """Return True if ``args`` contains any registered backgrounded command.

    Blank entries are skipped deliberately: ``"" in args`` is True for every
    process, so one empty ``command`` field would silently put the whole
    process table under the wall TTL.
    """
    return any(command and command in args for command in tracked_commands)


def find_breaches(
    records: Iterable[ProcessRecord],
    *,
    max_wall_seconds: int,
    max_cpu_percent: float,
    min_cpu_runtime_seconds: int,
    tracked_commands: Iterable[str] = (),
    exclude_pgids: Iterable[int] = (),
) -> list[Breach]:
    """Return the processes that breached a budget (CPU runaway or tracked TTL).

    Args:
        records: Parsed process records.
        max_wall_seconds: Wall-time TTL applied to tracked commands.
        max_cpu_percent: Sustained %CPU ceiling (e.g. 400 == 4 cores).
        min_cpu_runtime_seconds: Minimum elapsed time before a CPU breach counts
            (filters momentary spikes).
        tracked_commands: Commands the agent registered as backgrounded; only
            processes whose ``args`` contain one are eligible for the wall-TTL
            breach.
        exclude_pgids: Process groups to never flag (e.g. the harvester's own).

    Returns:
        A list of :class:`Breach`, one per breaching process, never killing.
    """
    tracked = list(tracked_commands)
    excluded = set(exclude_pgids)
    sampled = list(records)
    breaches: list[Breach] = []
    for record in sampled:
        if record.pgid in excluded:
            continue
        reasons: list[str] = []
        if record.pcpu >= max_cpu_percent and record.etimes >= min_cpu_runtime_seconds:
            reasons.append(
                f"{record.pcpu:.0f}% CPU sustained for {record.etimes}s "
                f"(ceiling {max_cpu_percent:.0f}%)"
            )
        if record.etimes >= max_wall_seconds and _is_tracked(record.args, tracked):
            reasons.append(f"tracked process running {record.etimes}s (TTL {max_wall_seconds}s)")
        if reasons:
            tree = _descendants(sampled, record.pid)
            breaches.append(
                Breach(
                    record=record,
                    reasons=tuple(reasons),
                    tree_pcpu=sum(r.pcpu for r in tree),
                    tree_pgids=tuple(sorted({r.pgid for r in tree})),
                )
            )
    return breaches


def _descendants(records: Sequence[ProcessRecord], root_pid: int) -> list[ProcessRecord]:
    """``root_pid``'s record and every process descended from it.

    Walked breadth-first over ppid links with a seen-set, so a malformed sample
    that reports a cycle (or a pid that is its own parent, as ``ps`` shows for
    pid 1 on some systems) terminates instead of spinning.
    """
    children: dict[int, list[ProcessRecord]] = {}
    for record in records:
        children.setdefault(record.ppid, []).append(record)

    found = [r for r in records if r.pid == root_pid]
    seen = {r.pid for r in found}
    queue = list(found)
    while queue:
        current = queue.pop()
        for child in children.get(current.pid, ()):
            if child.pid in seen:
                continue
            seen.add(child.pid)
            found.append(child)
            queue.append(child)
    return found


def read_tracked_commands(state_file: Path) -> list[str]:
    """Read the backgrounded commands recorded in the tracker's JSONL state file.

    Each line is a JSON object; lines carrying a non-blank string ``command``
    contribute it. A missing file yields ``[]``. Malformed lines are skipped
    explicitly (not blanket-suppressed) — the state file is best-effort and a
    corrupt line must not abort the whole harvest.
    """
    if not state_file.exists():
        return []
    commands: list[str] = []
    for line in state_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        command = record.get("command") if isinstance(record, dict) else None
        if isinstance(command, str) and command.strip():
            commands.append(command)
    return commands


def build_report(
    records: Iterable[ProcessRecord],
    *,
    max_wall_seconds: int,
    max_cpu_percent: float,
    min_cpu_runtime_seconds: int,
    tracked_commands: Iterable[str] = (),
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
        tracked_commands=tracked_commands,
        exclude_pgids=exclude_pgids,
    )
    serialised = [
        {
            "pid": b.record.pid,
            "pgid": b.record.pgid,
            "etimes": b.record.etimes,
            "pcpu": b.record.pcpu,
            "tree_pcpu": b.tree_pcpu,
            "tree_pgids": list(b.tree_pgids),
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
                f"{b.tree_pcpu:.0f}% CPU (whole tree)  {b.record.etimes}s"
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
