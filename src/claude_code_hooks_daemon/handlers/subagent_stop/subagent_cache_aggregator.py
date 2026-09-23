"""Collect each sub-agent's prompt-cache cost as it stops (Plan 00452).

Sub-agents get no status line of their own, so the coordinator's single bar is
the only place their cache cost can ever appear — and their usage is NOT in the
main transcript, where every record is ``isSidechain: false``. Something has to
collect it at the one moment the agent's transcript and the event are both in
reach, which is its stop. That is the same argument
``subagent_report_size_blocker`` makes about its own check.

It matters because the two halves diverge. Measured in this project: the main
thread ran 98.87% on a 1-hour TTL while a short sub-agent ran 62.17% on a
5-minute one, and a short agent never amortises its mandatory first cache
write. A bar showing only the main figure reports a healthy session while the
expensive half stays invisible.

**One file per agent, and that is a concurrency decision rather than a
convenience.** A single cumulative file would need a read-modify-write, and two
sub-agents finishing in the same instant would lose one of the updates — the
unlocked select-then-delete class Plan 00449 exists for. Per-agent files make
concurrent writers structurally incapable of clobbering each other, so there is
no lock to get wrong. Keying on the agent id also makes a re-fired stop
idempotent: it overwrites its own file rather than double-counting.

This handler is a SENSOR. It renders nothing, injects nothing, and never blocks
a stop — a number that failed to be collected must not strand an agent.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.handler_bases import SubagentStopHandlerBase
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

#: Directory under the daemon's untracked dir holding per-session sub-dirs.
_SIDECAR_SUBDIR: Final[str] = "cache-sidecar"

#: Anything outside this set is replaced before a value reaches a path segment.
_UNSAFE_NAME_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]")

#: Used when an id is empty, so a nameless agent still lands somewhere.
_NAME_FALLBACK: Final[str] = "unknown"

_EMPTY_TOTALS: Final[dict[str, int]] = {
    "requests": 0,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0,
    "ttl_5m_write_tokens": 0,
    "ttl_1h_write_tokens": 0,
}


def _safe_name(value: str) -> str:
    """A filesystem-safe path segment for a session or agent id."""
    if not value:
        return _NAME_FALLBACK
    return _UNSAFE_NAME_CHARS.sub("_", value)


def _as_int(raw: object) -> int:
    """A token count as an int, treating anything unexpected as zero.

    Deliberately total: this runs on every sub-agent stop and a surprising
    payload must cost a wrong number, never an exception on the stop path.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0
    return int(raw)


def _sidecar_dir(session_id: str, root: Path | None = None) -> Path:
    """Directory holding one totals file per sub-agent of ``session_id``."""
    base = root if root is not None else ProjectContext.daemon_untracked_dir()
    return base / _SIDECAR_SUBDIR / _safe_name(session_id)


def read_subagent_cache_totals(session_id: str, root: Path | None = None) -> dict[str, int]:
    """Sum every recorded sub-agent's totals for one session.

    Reads fail-silent by design — this is consumed by the status line, and a
    half-written or hand-mangled file must cost one agent's figures, never the
    whole render. An unknown session reads back as zeroes rather than raising.
    """
    combined = dict(_EMPTY_TOTALS)
    combined["agents_seen"] = 0

    try:
        directory = _sidecar_dir(session_id, root)
        entries = sorted(directory.glob("*.json"))
    except (OSError, RuntimeError) as exc:
        logger.debug("No sub-agent cache sidecar to read: %s", exc)
        return combined

    for entry in entries:
        try:
            payload = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            # One unreadable file must not hide the agents that recorded fine.
            logger.debug("Skipping unreadable sub-agent cache file %s: %s", entry, exc)
            continue
        if not isinstance(payload, dict):
            continue
        combined["agents_seen"] += 1
        for key in _EMPTY_TOTALS:
            combined[key] += _as_int(payload.get(key))

    return combined


class SubagentCacheAggregatorHandler(SubagentStopHandlerBase):
    """Record a stopping sub-agent's prompt-cache totals for the status line."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUBAGENT_CACHE_AGGREGATOR,
            priority=Priority.SUBAGENT_CACHE_AGGREGATOR,
            terminal=False,
            tags=[HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Only a stop that names an agent transcript has anything to collect."""
        return bool(hook_input.get("agent_transcript_path"))

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Record this agent's totals, then always ALLOW.

        A sensor on a blocking event: the ALLOW is unconditional by design, so
        a number that could not be collected never strands a stopping agent.
        """
        transcript = Path(str(hook_input.get("agent_transcript_path") or ""))
        self.record(
            session_id=str(hook_input.get("session_id") or ""),
            agent_id=str(hook_input.get("agent_id") or ""),
            transcript=transcript,
        )
        return BlockingResult(decision=Decision.ALLOW)

    def totals_for(self, transcript: Path) -> dict[str, int]:
        """Sum the cache counters across one agent transcript.

        Parsed line by line rather than slurped. The real task directory
        interleaves agent transcripts with plain-text process output, so a
        strict whole-file parse fails on the first non-JSON line; here such a
        line is simply not a usage record.

        **Counted per API request, not per record.** Claude Code writes one
        record per content block, and each carries the whole request's usage,
        so summing records counted every request about twice (measured: 4,276
        records for 2,119 requests). A request is identified by its message
        id. A record without an id cannot be matched against anything and is
        counted on its own, since dropping it would lose real usage.
        """
        totals = dict(_EMPTY_TOTALS)
        try:
            text = transcript.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("No readable agent transcript at %s: %s", transcript, exc)
            return totals

        seen_message_ids: set[str] = set()
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            message = record.get("message") or {}
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue

            message_id = message.get("id")
            if isinstance(message_id, str) and message_id:
                if message_id in seen_message_ids:
                    continue
                seen_message_ids.add(message_id)

            totals["requests"] += 1
            totals["cache_read_tokens"] += _as_int(usage.get("cache_read_input_tokens"))
            totals["cache_write_tokens"] += _as_int(usage.get("cache_creation_input_tokens"))
            creation = usage.get("cache_creation")
            if isinstance(creation, dict):
                totals["ttl_5m_write_tokens"] += _as_int(creation.get("ephemeral_5m_input_tokens"))
                totals["ttl_1h_write_tokens"] += _as_int(creation.get("ephemeral_1h_input_tokens"))

        return totals

    def record(
        self,
        session_id: str,
        agent_id: str,
        transcript: Path,
        root: Path | None = None,
    ) -> None:
        """Write this agent's totals to its own file, atomically.

        Atomicity (tmp write + ``replace``) keeps a concurrent status-line read
        from seeing half a document. Failures are logged and swallowed: a
        missing number must never strand a stopping agent.
        """
        totals = self.totals_for(transcript)
        try:
            directory = _sidecar_dir(session_id, root)
            directory.mkdir(parents=True, exist_ok=True)
            final_path = directory / f"{_safe_name(agent_id)}.json"
            tmp_path = unique_temp_path(final_path)
            tmp_path.write_text(json.dumps(totals), encoding="utf-8")
            tmp_path.replace(final_path)
        except RuntimeError as exc:
            # ProjectContext not initialised (standalone entry point).
            logger.warning("Skipping sub-agent cache sidecar (no project context): %s", exc)
        except OSError as exc:
            logger.warning("Failed to write sub-agent cache sidecar: %s", exc)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="subagent cache aggregator records totals on stop",
                command='echo "test"',
                description=(
                    "Verify a stopping sub-agent's prompt-cache totals are recorded so the "
                    "coordinator's status line can show SUB alongside MAIN. Sensor only: "
                    "renders nothing and never blocks a stop."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Observe-only sensor; failures are logged and never block a stop",
                test_type=TestType.CONTEXT,
                requires_event="SubagentStop event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            )
        ]
