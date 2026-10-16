"""SpawnRateAdvisorHandler - name the load before another agent starts (Plan 00471 L4, L5).

Neither lever saves total tokens; both cut the RATE, which is what keeps a run
under the five-hour limit. Measured: 86.5 % of subagent spend ran while more
than three agents were active, and the peak minute had 22.

On a spawn (``Agent``/``Task``) and on a SendMessage that cold-resumes a stopped
agent (in cost terms a spawn: a mean 336k cache write), it advises:

- **Concurrency** (``max_concurrent``): at or above the cap it names the live
  agents (:mod:`utils.session_load`), so the coordinator can wait for one.
- **Five-hour limit** (``advise_pct``): at or above it, "serialise now", with
  the reset time, from the context sidecar's ``rate_limits.five_hour``. A
  sidecar older than ``max_age_seconds`` is unknown and draws nothing.

**Advisory only, by ruling.** A stale live count that DENIED would lock the
coordinator out of spawning, the one outcome worse than the inferno while the
owner is away; deny modes wait for ledger evidence that the count is accurate.
Every fired advisory is a ledger event, which is that evidence. Each call also
refreshes the live snapshot the status segment reads.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    SUBAGENT_DISPATCH_TOOL_NAMES,
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, GatingResult, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.handlers.pre_tool_use.resume_guard import (
    DEFAULT_WARM_SECONDS,
    ResumeGuardHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_context_budget import int_or_none
from claude_code_hooks_daemon.utils.session_load import (
    DEFAULT_LIVENESS_SECONDS,
    finished_agents,
    live_agents,
    read_five_hour,
    write_live_snapshot,
)
from claude_code_hooks_daemon.utils.spend_ledger import append_event
from claude_code_hooks_daemon.utils.transcript_tail import read_tail, subagents_dir

DEFAULT_ADVISE_PCT: Final[int] = 80
DEFAULT_MAX_AGE_SECONDS: Final[int] = 300

#: How many live agents the advisory names before summarising the rest.
_NAMED_AGENTS: Final[int] = 8


class SpawnRateAdvisorHandler(PreToolUseHandlerBase):
    """Advise at the live-agent cap and near the five-hour limit; never deny."""

    _max_concurrent: int | None = None
    _liveness_seconds: int | None = DEFAULT_LIVENESS_SECONDS
    _advise_pct: int | float | None = DEFAULT_ADVISE_PCT
    _max_age_seconds: int | None = DEFAULT_MAX_AGE_SECONDS

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SPAWN_RATE_ADVISOR,
            priority=Priority.SPAWN_RATE_ADVISOR,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        self._untracked_override: Path | None = None

    def _untracked_dir(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    def _pct(self) -> float | None:
        value = self._advise_pct
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return None
        return float(value)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A spawn or a SendMessage, while either lever is on."""
        if int_or_none(self._max_concurrent) is None and self._pct() is None:
            return False
        tool = hook_input.get(HookInputField.TOOL_NAME)
        return tool in SUBAGENT_DISPATCH_TOOL_NAMES or tool == ToolName.SEND_MESSAGE

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Measure the load and advise; always ALLOW."""
        if hook_input.get(
            HookInputField.TOOL_NAME
        ) == ToolName.SEND_MESSAGE and not self._cold_resume(hook_input):
            return GatingResult(decision=Decision.ALLOW)
        session = str(hook_input.get(HookInputField.SESSION_ID) or "")
        untracked = self._untracked_dir()
        advice: list[str] = []

        directory = subagents_dir(
            str(hook_input.get(HookInputField.TRANSCRIPT_PATH) or ""), session
        )
        if directory is not None:
            live = live_agents(
                directory,
                liveness_seconds=int_or_none(self._liveness_seconds) or DEFAULT_LIVENESS_SECONDS,
                finished=finished_agents(untracked, session),
            )
            write_live_snapshot(untracked, session, live)
            cap = int_or_none(self._max_concurrent)
            if cap is not None and len(live) >= cap:
                named = ", ".join(
                    f"{agent.label} ({agent.context_tokens:,})" for agent in live[:_NAMED_AGENTS]
                )
                more = f" and {len(live) - _NAMED_AGENTS} more" if len(live) > _NAMED_AGENTS else ""
                advice.append(
                    f"CONCURRENCY: {len(live)} agents are live (cap {cap}): {named}{more}. "
                    "Every live agent re-reads its context per call, so the session's rate "
                    "is their sum. Consider waiting for a completion notification, or "
                    "TaskStop an idle one whose work you have harvested, before starting another."
                )
                append_event(
                    untracked,
                    session,
                    {"kind": "concurrency-advisory", "live": len(live), "cap": cap},
                )

        threshold = self._pct()
        five_hour = read_five_hour(
            untracked,
            session,
            max_age_seconds=int_or_none(self._max_age_seconds) or DEFAULT_MAX_AGE_SECONDS,
        )
        if threshold is not None and five_hour is not None and five_hour.pct >= threshold:
            resets = (
                datetime.fromtimestamp(five_hour.resets_at, UTC).strftime("%H:%M UTC")
                if five_hour.resets_at is not None
                else "an unknown time"
            )
            advice.append(
                f"FIVE-HOUR LIMIT: {five_hour.pct:.0f}% of the five-hour usage limit is used "
                f"(advise at {threshold:.0f}%). Serialise now: let running agents finish before "
                f"starting more. The window resets at {resets}."
            )
            append_event(untracked, session, {"kind": "five-hour-advisory", "pct": five_hour.pct})

        if advice:
            return GatingResult(decision=Decision.ALLOW, context=advice)
        return GatingResult(decision=Decision.ALLOW)

    @staticmethod
    def _cold_resume(hook_input: Mapping[str, Any]) -> bool:
        """Whether this SendMessage resumes a stopped agent past the cache TTL."""
        transcript = ResumeGuardHandler.target_transcript(hook_input)
        if transcript is None:
            return False
        try:
            reading = read_tail(transcript)
            idle = time.time() - transcript.stat().st_mtime
        except OSError:
            return False
        return reading is not None and reading.stopped and idle >= DEFAULT_WARM_SECONDS

    def get_claude_md(self) -> str | None:
        """Advisory whose message arrives with the spawn it is about; nothing standing to hold."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One case, harness-undrivable: the count comes from real live transcripts."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="spawn rate advisor - names the live agents at the cap",
                command="Dispatch an Agent while four teammates are working",
                description=(
                    "The dispatch is allowed with additionalContext naming the live agents; "
                    "unit tests in tests/unit/handlers/pre_tool_use/test_spawn_rate_advisor.py "
                    "cover the concurrency and five-hour matrix."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"CONCURRENCY"],
                safety_notes="Advisory only; never denies a spawn.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "The live count is read from real agent transcripts in the session "
                    "directory, which the harness cannot fabricate."
                ),
            )
        ]
