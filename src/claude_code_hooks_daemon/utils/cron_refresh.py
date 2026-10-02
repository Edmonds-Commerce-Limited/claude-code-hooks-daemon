"""Refresh a declared cron before the 7-day expiry kills it (Plan 00470 Task 2.2).

The Stop and SubagentStop enforcers share this one judgement. A recurring cron
dies 7 days after creation; in an always-on session whose jobs were all created
together, every one dies at once and nothing is left to produce the Stop that
would notice. So the enforcers also deny a stop while a LIVE declared job is
older than ``refresh_after``, naming the ``CronDelete`` + ``CronCreate`` that
refreshes it, while ticks are still arriving.

Age comes from ``cron_records`` (the Stop payload has none). **A job with no
record is stamped, never denied**: it predates the record keeper or its record
was lost, and denying on an age the daemon does not know would refresh a young
job for nothing. The stamp starts its clock at the first Stop that sees it, so
the worst case is a refresh one ``refresh_after`` late.

**Deferring to what already pauses an enforcer.** A usage-paused session never
reaches here (the handlers' ``matches()`` stands down, Plan 00479). A job paused
with ``hooks-daemon cron-pause`` is not refreshed: it was cancelled on purpose.
The ``[awaiting-human]`` marker is deliberately NOT consulted. It silences cron
TICKS, which is exactly when a job ages toward expiry unnoticed, and a refresh
costs one turn per ``refresh_after``, so deferring would let a long human wait
expire every job. One deny per stop chain still holds (``stop_hook_active``).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import PersistentCronConfig
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.result_types import BlockingResult
from claude_code_hooks_daemon.utils.cron_enforcement import (
    SessionCron,
    declared_tick_prompt,
    find_missing_crons,
    matching_session_crons,
    parse_session_crons,
    verdict_for_missing_crons,
)
from claude_code_hooks_daemon.utils.cron_pause import load_live_pauses
from claude_code_hooks_daemon.utils.cron_records import (
    CRON_EXPIRY_SECONDS,
    DEFAULT_REFRESH_AFTER_DAYS,
    SECONDS_PER_DAY,
    CronRecord,
    forget_missing,
    prompt_fingerprint,
    read_records,
    record_cron,
)
from claude_code_hooks_daemon.utils.stop_hook_helpers import is_stop_hook_active

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaleCron:
    """A live declared job whose every copy is past ``refresh_after``."""

    job: PersistentCronConfig
    cron_ids: tuple[str, ...]
    age_seconds: float


def refresh_days_to_seconds(days: float) -> float:
    """The handler option ``refresh_after_days`` in seconds.

    A value that cannot work is replaced by the default, with a warning, rather
    than raised: this runs inside the Stop chain, and an option that is zero,
    negative, or at or past the expiry would either deny every stop or never
    deny at all.
    """
    seconds = days * SECONDS_PER_DAY
    if 0 < seconds < CRON_EXPIRY_SECONDS:
        return seconds
    logger.warning(
        "cron refresh_after_days=%s must be above 0 and below 7 (the cron expiry); using %s",
        days,
        DEFAULT_REFRESH_AFTER_DAYS,
    )
    return DEFAULT_REFRESH_AFTER_DAYS * SECONDS_PER_DAY


def _age_of_copies(
    copies: list[SessionCron], known: dict[str, CronRecord], now: float
) -> float | None:
    """The age of the YOUNGEST copy, or None while any copy has no record.

    The youngest decides: one fresh copy keeps the job alive. An unrecorded copy
    is stamped by the caller and counts as young.
    """
    if any(copy.id not in known for copy in copies):
        return None
    return min(now - known[copy.id].created_at for copy in copies)


def find_stale_jobs(
    jobs: list[PersistentCronConfig],
    session_crons: list[SessionCron],
    *,
    session_id: str,
    records_path: Path,
    paused_job_ids: frozenset[str],
    refresh_after: float,
    now: float,
) -> list[StaleCron]:
    """The live declared jobs due a refresh, stamping every unrecorded copy on the way."""
    forget_missing(
        records_path, session_id=session_id, live_ids={cron.id for cron in session_crons}, now=now
    )
    known = {r.cron_id: r for r in read_records(records_path) if r.session_id == session_id}
    stale: list[StaleCron] = []
    for job in jobs:
        copies = matching_session_crons(job, session_crons)
        if job.id in paused_job_ids or not copies:
            continue
        for copy in copies:
            if copy.id not in known:
                record_cron(
                    records_path,
                    CronRecord(
                        session_id, copy.id, job.schedule, prompt_fingerprint(job.prompt), now
                    ),
                    now=now,
                )
        age = _age_of_copies(copies, known, now)
        if age is not None and age >= refresh_after:
            stale.append(StaleCron(job, tuple(copy.id for copy in copies), age))
    return stale


def render_stale_crons_reason(stale: list[StaleCron], refresh_after: float) -> str:
    """The Stop-block reason naming the ``CronDelete`` + ``CronCreate`` that refresh each job."""
    plural = "job" if len(stale) == 1 else "jobs"
    lines = [
        f"DECLARED PERSISTENT CRON{'' if len(stale) == 1 else 'S'} DUE A REFRESH "
        f"({len(stale)} {plural}) -- recurring crons expire "
        f"{CRON_EXPIRY_SECONDS / SECONDS_PER_DAY:.0f} days after creation, and this session's "
        f"{'job is' if len(stale) == 1 else 'jobs are'} past the "
        f"{refresh_after / SECONDS_PER_DAY:.1f}-day refresh point. An expired cron fires no more "
        "ticks, so nothing would ever bring this session back.",
        "",
        "For each job below, CronDelete the old cron and then CronCreate (recurring: true) "
        "it again with the schedule and prompt exactly as given:",
        "",
    ]
    for item in stale:
        lines.append(
            f"  • {item.job.id} -- {item.age_seconds / SECONDS_PER_DAY:.1f} days old; "
            f"CronDelete {', '.join(item.cron_ids)}"
        )
        lines.append(f"    CronCreate schedule (recurring): {item.job.schedule}")
        lines.append("    prompt:")
        lines.extend(f"      {line}" for line in declared_tick_prompt(item.job).splitlines())
    lines.append("")
    lines.append("Once every job above is re-created, stopping is safe again.")
    return "\n".join(lines)


def judge_declared_crons(
    jobs: list[PersistentCronConfig],
    hook_input: dict[str, Any],
    *,
    pauses_path: Path | None,
    records_path: Path | None,
    should_advise: Callable[[str], bool],
    refresh_after_seconds: float,
    now: float | None = None,
) -> BlockingResult:
    """The Stop/SubagentStop verdict for the declared ``jobs``.

    A job missing from ``session_crons`` is judged first, exactly as before
    (``verdict_for_missing_crons``). Only when nothing is missing-and-unpaused is
    the age of the live jobs considered.
    """
    session_crons = parse_session_crons(hook_input)
    if session_crons is None:
        return BlockingResult(decision=Decision.ALLOW)
    when = time.time() if now is None else now

    missing = find_missing_crons(jobs, session_crons)
    verdict = (
        verdict_for_missing_crons(
            missing, hook_input, pauses_path=pauses_path, should_advise=should_advise, now=when
        )
        if missing
        else BlockingResult(decision=Decision.ALLOW)
    )
    session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
    if verdict.decision is Decision.DENY or records_path is None or not session_id:
        return verdict

    paused = frozenset(load_live_pauses(pauses_path, session_id=session_id, now=when))
    stale = find_stale_jobs(
        jobs,
        session_crons,
        session_id=session_id,
        records_path=records_path,
        paused_job_ids=paused,
        refresh_after=refresh_after_seconds,
        now=when,
    )
    if not stale:
        return verdict
    if is_stop_hook_active(hook_input):
        logger.warning(
            "declared cron(s) past the refresh point on stop re-entry, allowing the stop: %s",
            ", ".join(item.job.id for item in stale),
        )
        return verdict
    return BlockingResult.deny(render_stale_crons_reason(stale, refresh_after_seconds))
