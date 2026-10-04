"""LimitRebriefHandler - re-brief after a usage-limit resume, and name agents a limit killed (Plan 00470 Task 3.2).

Two jobs, one handler, because both end in the same instruction to the model: work
that was in flight when a usage limit hit has died, nothing re-dispatches it, so
re-brief it from what is on disk.

**Re-brief after a resume.** ``quota_resume_recorder`` (Notification) records how a
usage-limit wait ended. A Notification hook cannot speak to the model, so this
handler delivers the re-brief at the session's next prompt -- a one-shot, then the
event is marked delivered. It points at what exists today (the worktrees, the
active plan's JOURNAL, the last recorded limit hit), lists the agents the durable
work queue (Plan 00470 Task 3.3) records as still running, and lists any agent
recorded as killed.

**Name a killed background or teammate agent.** ``agent_terminated_early_failure_detector``
covers a FOREGROUND dispatch, whose death arrives as a tool result. A background
agent or a teammate that a session or weekly limit kills reports its death through
a prompt-borne notification instead, so it reaches this handler as the prompt:

* a prompt opening with ``<task-notification`` (a background task finishing --
  ``origin.kind`` ``task-notification`` in the transcript, Plan 00474 N274), or
* a prompt opening with ``<teammate-message`` carrying an ``idle_notification`` whose
  ``idleReason`` is ``failed`` (the shape Plan 00315's transcript miner observed,
  with ``failureReason`` quoting the limit).

and, in both, the harness's own limit sentence (``You've hit your session|weekly
limit · resets ...``, quoted in the same evidence). The markup INSIDE a
``<task-notification>`` is not documented in this repository's vendored docs. The
shape observed in a live session is ``task-id``, ``tool-use-id``, ``output-file``,
``status`` and ``summary`` elements; only ``summary`` is read, and optionally: the
agent is named by it, or by the whole notification's text with markup stripped when
it is absent. A teammate is named by the ``teammate_id`` attribute the repository's
fixtures show. A human prompt that merely quotes the sentence does not open with
either marker and is ignored.

Whether Claude Code fires ``UserPromptSubmit`` for these machine-sent turns is not
documented either; if it does not, the death is simply not seen here and the
resume re-brief still lists the worktrees. Never denies; fails open.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.utils.limit_events import (
    KIND_AGENT_KILLED,
    RESUME_KINDS,
    LimitEvent,
    default_events_path,
    mark_delivered,
    pending_events,
    record_event,
)
from claude_code_hooks_daemon.utils.stop_failure_records import (
    StopFailureRecord,
    read_records,
)
from claude_code_hooks_daemon.utils.stop_failure_records import (
    default_records_path as default_stop_failures_path,
)
from claude_code_hooks_daemon.utils.work_queue import default_queue_path, queue_briefing

logger = logging.getLogger(__name__)

_TASK_NOTIFICATION_MARKER: Final[str] = "<task-notification"
_TEAMMATE_MARKER: Final[str] = "<teammate-message"

#: The harness's own sentence for a usage-limit rejection, in both spellings the
#: repository's evidence quotes ("session" and "weekly"), up to the "resets" that
#: always follows it. The apostrophe may be straight or typographic, so any one
#: non-word character stands in for it.
_LIMIT_RE: Final[re.Pattern[str]] = re.compile(
    r"You\Wve hit your (?:session|weekly) limit\W{0,6}resets"
)

#: A teammate that stopped because it failed, as its idle notification reports it.
_TEAMMATE_FAILED_RE: Final[re.Pattern[str]] = re.compile(r"idleReason\W{1,6}failed")
_TEAMMATE_ID_RE: Final[re.Pattern[str]] = re.compile(r'teammate_id="([^"]+)"')
_MARKUP_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]*>")
#: The one element of a task notification that says WHAT ended, in the shape this
#: repository has observed (``task-id``, ``tool-use-id``, ``output-file``,
#: ``status``, ``summary``). It is optional: without it the whole text is used.
_SUMMARY_RE: Final[re.Pattern[str]] = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)

#: How much of a notification's text names the agent.
_EXCERPT_CHARS: Final[int] = 200

_RESUME_MEANING: Final[dict[str, str]] = {
    "quota_auto_resume_fired": "Claude Code resumed the task the usage limit paused.",
    "quota_auto_resume_stale": (
        "the usage limit reset while the machine slept, and Claude Code is waiting for "
        "Enter instead of continuing."
    ),
    "quota_auto_resume_disabled": (
        "Claude Code ended the wait and did NOT continue the task, so nothing resumed on "
        "its own."
    ),
}

#: Where to look for what was in flight, in the order to look. The durable work queue
#: (Plan 00470 Task 3.3) heads it: it holds the brief, which no other place does.
_REBRIEF_PLACES: Final[tuple[str, ...]] = (
    "`bin/hooks-daemon work-queue list`, the durable queue of dispatched agents "
    "(worktree, branch, brief, last sha) listed below",
    "`git worktree list`, then `git status` and `git log -1` inside each worktree that "
    "held in-flight work",
    "the newest entries of the active plan's JOURNAL/ day-file",
)


def _is_limit_text(text: str) -> bool:
    return _LIMIT_RE.search(text) is not None


def dead_agent_identity(prompt: str) -> str | None:
    """Who the prompt says a usage limit killed, or None when it says no such thing.

    Only a prompt that OPENS with a notification marker counts, so a human quoting
    the limit sentence is ignored.
    """
    text = prompt.lstrip()
    if text.startswith(_TASK_NOTIFICATION_MARKER) and _is_limit_text(text):
        summary = _SUMMARY_RE.search(text)
        plain = " ".join(_MARKUP_RE.sub(" ", summary.group(1) if summary else text).split())
        return f"background task notification: {plain[:_EXCERPT_CHARS]}"
    if (
        text.startswith(_TEAMMATE_MARKER)
        and "idle_notification" in text
        and _TEAMMATE_FAILED_RE.search(text)
        and _is_limit_text(text)
    ):
        found = _TEAMMATE_ID_RE.search(text)
        return f"teammate {found.group(1)}" if found else "a teammate"
    return None


def _utc_clock(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%H:%M UTC")


def _agent_notice(identity: str) -> str:
    return (
        f"BACKGROUND OR TEAMMATE AGENT KILLED BY A USAGE LIMIT ({identity!r})\n\n"
        "The harness reports this agent died on a session or weekly limit. You MUST tell "
        "the user it died mid-task, not that it finished. Its output (if any) is PARTIAL: "
        "do NOT treat the assignment as done, and do NOT retry it immediately. Once the "
        "limit resets, RE-BRIEF the same assignment to a fresh agent, starting from the "
        "state its worktree holds (`git status`, `git log -1`)."
    )


def _last_limit_hit(records: list[StopFailureRecord], session_id: str) -> StopFailureRecord | None:
    """The newest recorded limit hit of the session, resolved or not."""
    mine = [r for r in records if r.session_id == session_id]
    return max(mine, key=lambda r: r.recorded_at, default=None)


def _rebrief(
    resumes: list[LimitEvent],
    agents: list[LimitEvent],
    last_hit: StopFailureRecord | None,
    queue_lines: list[str],
) -> str:
    lines = ["USAGE LIMIT: RE-BRIEF WHAT WAS IN FLIGHT", ""]
    for event in resumes:
        meaning = _RESUME_MEANING[event.kind]
        lines.append(f"- {event.kind} at {_utc_clock(event.recorded_at)}: {meaning}")
    if last_hit is not None:
        lines.append(
            f"- Last recorded limit hit: {last_hit.error} at {_utc_clock(last_hit.recorded_at)}."
        )
    lines += [
        "",
        "Anything running when the limit hit may have died with it, and nothing "
        "re-dispatches it for you. Before carrying on, rebuild the picture from disk:",
    ]
    lines += [f"{number}. {place}" for number, place in enumerate(_REBRIEF_PLACES, start=1)]
    if queue_lines:
        lines += ["", *queue_lines]
    if agents:
        lines += ["", "Agents recorded as killed by a limit (re-brief each to a fresh agent):"]
        lines += [f"- {event.detail}" for event in agents]
    else:
        lines += [
            "",
            "No agent was recorded as killed by a limit. That does not mean none was: a "
            "background agent's death is only seen when its notification reaches a prompt, "
            "so check each worktree.",
        ]
    lines += [
        "",
        "Re-brief each lost assignment as a fresh dispatch from its worktree state. Do not "
        "assume it finished.",
    ]
    return "\n".join(lines)


class LimitRebriefHandler(UserPromptSubmitHandlerBase):
    """Re-brief after a usage-limit resume; name a background or teammate agent a limit killed."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.LIMIT_REBRIEF,
            priority=Priority.LIMIT_REBRIEF,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )

    def _events_path(self) -> Path | None:
        """Where the events live; None without a project context."""
        return default_events_path()

    def _stop_failures_path(self) -> Path | None:
        """Where the StopFailure records live; None without a project context."""
        return default_stop_failures_path()

    def _queue_path(self) -> Path | None:
        """Where the durable work queue lives; None without a project context."""
        return default_queue_path()

    def _now(self) -> float:
        return time.time()

    @staticmethod
    def _prompt(hook_input: dict[str, Any]) -> str:
        prompt = hook_input.get(HookInputField.PROMPT)
        return prompt if isinstance(prompt, str) else ""

    @staticmethod
    def _session_id(hook_input: dict[str, Any]) -> str:
        return str(hook_input.get(HookInputField.SESSION_ID) or "")

    def _pending(self, hook_input: dict[str, Any]) -> list[LimitEvent]:
        """This session's undelivered events; empty without a project context or session."""
        path = self._events_path()
        session_id = self._session_id(hook_input)
        if path is None or not session_id:
            return []
        return pending_events(path, session_id)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A prompt reporting a limit-killed agent, or any prompt while a resume is unannounced."""
        if dead_agent_identity(self._prompt(hook_input)) is not None:
            return True
        return any(e.kind in RESUME_KINDS for e in self._pending(hook_input))

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Name a limit-killed agent and/or deliver the pending re-brief; always ALLOW."""
        path = self._events_path()
        session_id = self._session_id(hook_input)
        context: list[str] = []

        # Read what is pending BEFORE recording this prompt's death: the notice below
        # already names it, so the re-brief lists only earlier ones.
        pending = self._pending(hook_input)
        resumes = [e for e in pending if e.kind in RESUME_KINDS]
        agents = [e for e in pending if e.kind == KIND_AGENT_KILLED]

        identity = dead_agent_identity(self._prompt(hook_input))
        if identity is not None:
            context.append(_agent_notice(identity))
            if path is not None and session_id:
                record_event(
                    path,
                    LimitEvent(
                        session_id=session_id,
                        kind=KIND_AGENT_KILLED,
                        recorded_at=self._now(),
                        detail=identity,
                    ),
                )

        if path is not None and session_id and resumes:
            stop_failures = self._stop_failures_path()
            last_hit = (
                _last_limit_hit(read_records(stop_failures), session_id)
                if stop_failures is not None
                else None
            )
            queue_lines = queue_briefing(self._queue_path(), now=self._now())
            context.append(_rebrief(resumes, agents, last_hit, queue_lines))
            mark_delivered(path, session_id, now=self._now())
        return BlockingResult(decision=Decision.ALLOW, context=context)

    def get_claude_md(self) -> str | None:
        """No resident guidance: never denies, and each message is delivered in full at fire time."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One case: the prompts that trigger it are machine-sent, which the harness cannot send."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="limit_rebrief names a background agent a usage limit killed",
                command=(
                    "Deliver a prompt opening with <task-notification> whose text quotes "
                    '"You\'ve hit your session limit · resets 9:50am (UTC)" and verify a '
                    "re-brief advisory naming the agent is injected."
                ),
                harness_cannot_produce=(
                    "The trigger is a prompt the harness itself sends when a background "
                    "agent or teammate dies on a real usage limit (or a Notification of "
                    "type quota_auto_resume_* followed by any prompt); an agent under test "
                    "cannot cause either. Covered by "
                    "tests/unit/handlers/user_prompt_submit/test_limit_rebrief.py."
                ),
                description=(
                    "A prompt opening with a task-notification or a failed teammate idle "
                    "notification that quotes the harness's usage-limit sentence injects an "
                    "advisory naming the dead agent and demanding a re-brief; a recorded "
                    "quota_auto_resume_* event injects a one-shot re-brief at the next prompt."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"KILLED BY A USAGE LIMIT", r"RE-BRIEF"],
                safety_notes="Advisory only; writes at most two records to the daemon's untracked dir.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
