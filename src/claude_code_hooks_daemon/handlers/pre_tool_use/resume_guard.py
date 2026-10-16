"""ResumeGuardHandler - do not cold-resume a large stopped agent (Plan 00471 L3).

A SendMessage to a finished agent resumes its WHOLE history. Once the agent has
been idle longer than the subagent cache TTL (5 minutes) that history is cold,
so the first resumed request re-writes all of it to the cache. Measured: 46 cold
resumes at 150k+ wrote 15.46 M tokens, a mean of 336k per resume. Spawning a
fresh agent from the stopped one's report or handoff costs a fraction of that.

The guard fires only when all three hold: the target is **stopped** (its last
conversational record is an ``end_turn``), **cold** (transcript untouched for
``warm_seconds``), and **large** (context at or above ``max_resume_tokens``).
A message to a running agent resumes nothing and is never gated; a warm resume
is cache reads only and is allowed. A ``to`` that matches no transcript of this
session (a cross-session peer) fails open; an agent directory or transcript
that cannot be read fails open too, with an ``unmeasured`` record.

``mode: deny`` refuses, naming the fresh-spawn route and the agent's last report
or handoff file when one is found; ``mode: advise`` (the shipped default) allows
with the same text as context. A message starting ``RESUME-LARGE: <reason>`` is
the override: it is allowed and recorded in the spend ledger.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_context_budget import (
    STATE_HANDOFF_PATH,
    STATE_HANDOFF_WRITTEN,
    STATE_KIND,
    int_or_none,
)
from claude_code_hooks_daemon.utils.path_predicates import path_is_file
from claude_code_hooks_daemon.utils.spend_ledger import (
    append_event,
    note_unmeasured,
    read_state,
    state_path,
)
from claude_code_hooks_daemon.utils.subagent_report_paths import (
    DEFAULT_PERSISTED_REPORT_DIR,
    find_persisted_report,
)
from claude_code_hooks_daemon.utils.transcript_tail import (
    agent_name_of,
    find_agent_transcript,
    read_tail,
    subagents_dir,
)

MODE_DENY: Final[str] = "deny"
MODE_ADVISE: Final[str] = "advise"
_MODES: Final[frozenset[str]] = frozenset({MODE_DENY, MODE_ADVISE})

#: The override: the first line of the message starts with this.
OVERRIDE_PREFIX: Final[str] = "RESUME-LARGE:"

DEFAULT_MAX_RESUME_TOKENS: Final[int] = 250_000
#: The subagent prompt-cache TTL (``subagentPromptCacheTtl``, 5 minutes).
DEFAULT_WARM_SECONDS: Final[int] = 300

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.RESUME_COLD_LARGE,
    blocked="a SendMessage that would resume a stopped, cold agent at or above max_resume_tokens",
    why="A cold resume re-writes the agent's whole history to the cache before it does any work",
    fix="Spawn a fresh agent from the stopped one's report or handoff, or prefix the message RESUME-LARGE: <reason>",
    verbose=(
        "WHY BLOCKED:\n"
        "A message to a finished agent resumes its whole history. Idle past the\n"
        "cache TTL, that history is cold, so the first request re-writes all of it\n"
        "(measured mean: 336k tokens per cold resume).\n\n"
        "DO INSTEAD:\n"
        "  1. Spawn a fresh agent, briefed from the stopped agent's report or\n"
        "     handoff file.\n"
        "  2. If the resume is genuinely worth it (a small fix that needs exactly\n"
        "     this context), start the message with `RESUME-LARGE: <reason>`.\n"
        "     It is allowed and recorded."
    ),
)


def target_transcript(hook_input: Mapping[str, Any]) -> Path | None:
    """The transcript of the agent a SendMessage names, or None.

    A module function, not a method: another handler module that imported the
    handler CLASS for it would have the registry discover, and register, the
    guard a second time.

    Raises OSError when the session's agent directory cannot be read.
    """
    tool_input = hook_input.get(HookInputField.TOOL_INPUT)
    target = tool_input.get("to") if isinstance(tool_input, dict) else None
    if not isinstance(target, str):
        return None
    directory = subagents_dir(
        str(hook_input.get(HookInputField.TRANSCRIPT_PATH) or ""),
        str(hook_input.get(HookInputField.SESSION_ID) or ""),
    )
    return find_agent_transcript(directory, target) if directory is not None else None


class ResumeGuardHandler(PreToolUseHandlerBase):
    """Gate a SendMessage that would cold-resume a large stopped agent."""

    _max_resume_tokens: int | None = DEFAULT_MAX_RESUME_TOKENS
    _warm_seconds: int | None = DEFAULT_WARM_SECONDS
    _mode: str | None = MODE_ADVISE

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.RESUME_GUARD,
            priority=Priority.RESUME_GUARD,
            terminal=True,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING],
        )
        self._untracked_override: Path | None = None
        self._project_root: Path | None = None

    @staticmethod
    def validate_options(options: Mapping[str, Any]) -> dict[str, str]:
        """Refuse a malformed option; the handler then runs on its default for it."""
        problems: dict[str, str] = {}
        for key in ("max_resume_tokens", "warm_seconds"):
            if key in options and int_or_none(options[key]) is None:
                problems[key] = f"{key} must be a positive integer"
        if "mode" in options and options["mode"] not in _MODES:
            problems["mode"] = f"mode must be one of {', '.join(sorted(_MODES))}"
        return problems

    def _untracked_dir(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    def _root(self) -> Path:
        return self._project_root or ProjectContext.project_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every SendMessage; whether it resumes anything is judged in handle()."""
        return hook_input.get(HookInputField.TOOL_NAME) == ToolName.SEND_MESSAGE

    def get_rules(self) -> list[Rule]:
        """The rule behind the deny."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny (or advise on) a cold resume of a large stopped agent."""
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        tool_input = tool_input if isinstance(tool_input, dict) else {}
        target = str(tool_input.get("to") or "")
        session = str(hook_input.get(HookInputField.SESSION_ID) or "")
        transcript: Path | None = None
        try:
            transcript = target_transcript(hook_input)
            if transcript is None:
                return GatingResult(decision=Decision.ALLOW)
            reading = read_tail(transcript)
            idle = time.time() - transcript.stat().st_mtime
        except OSError:
            untracked = self._untracked_dir()
            note_unmeasured(
                untracked,
                session_id=session,
                agent_id=(
                    transcript.name.removeprefix("agent-").removesuffix(".jsonl")
                    if transcript is not None
                    else target
                ),
                reason="transcript-unreadable" if transcript is not None else "agents-unlistable",
                handler=self.name,
                tool_name=ToolName.SEND_MESSAGE,
                log_dir=untracked / "logs" / "hooks",
            )
            return GatingResult(decision=Decision.ALLOW)
        threshold = int_or_none(self._max_resume_tokens) or DEFAULT_MAX_RESUME_TOKENS
        warm = int_or_none(self._warm_seconds) or DEFAULT_WARM_SECONDS
        if (
            reading is None
            or not reading.stopped
            or idle < warm
            or reading.context_tokens < threshold
        ):
            return GatingResult(decision=Decision.ALLOW)

        message = tool_input.get("message")
        first_line = (
            message.strip().splitlines()[0] if isinstance(message, str) and message.strip() else ""
        )
        if first_line.startswith(OVERRIDE_PREFIX):
            append_event(
                self._untracked_dir(),
                session,
                {
                    "kind": "resume-override",
                    "to": target,
                    "context_tokens": reading.context_tokens,
                    "reason": first_line.removeprefix(OVERRIDE_PREFIX).strip(),
                },
            )
            return GatingResult(decision=Decision.ALLOW)

        text = self._explain(
            target, reading.context_tokens, idle, self._last_handoff(session, transcript)
        )
        if self._mode == MODE_DENY:
            return GatingResult(decision=Decision.DENY, reason=text).under_rule(_RULE)
        return GatingResult(decision=Decision.ALLOW, context=[text])

    def _last_handoff(self, session: str, transcript: Path) -> Path | None:
        """The agent's handoff file (from the budget state) or its last persisted report."""
        agent_id = transcript.name.removeprefix("agent-").removesuffix(".jsonl")
        state = read_state(state_path(self._untracked_dir(), session, STATE_KIND, agent_id))
        for key in (STATE_HANDOFF_WRITTEN, STATE_HANDOFF_PATH):
            value = state.get(key)
            if isinstance(value, str) and value and path_is_file(value, unreadable_means=False):
                return Path(value)
        reports = self._root() / DEFAULT_PERSISTED_REPORT_DIR
        return find_persisted_report(reports, agent_name_of(transcript) or agent_id, agent_id)

    @staticmethod
    def _explain(target: str, context: int, idle: float, handoff: Path | None) -> str:
        source = (
            f"its last report or handoff, {handoff}"
            if handoff is not None
            else "its last report or handoff (none found on disk; ask it nothing, read its worktree)"
        )
        return (
            f"COLD RESUME: `{target}` is stopped, idle {int(idle // 60)} min (past the cache TTL), "
            f"and its context is {context:,} tokens. This message would resume all of it, "
            "re-writing the whole history to the cache before any work. Spawn a fresh agent "
            f"briefed from {source} instead. If this resume is genuinely worth it, start the "
            f"message with `{OVERRIDE_PREFIX} <reason>`; that is allowed and recorded."
        )

    def get_claude_md(self) -> str | None:
        """Resident guidance: the coordinator should spawn fresh before it is told to."""
        return (
            "## resume_guard — do not cold-resume a large finished agent\n\n"
            "A SendMessage to a STOPPED agent resumes its whole history. When it has "
            "been idle past the cache TTL (`warm_seconds`, 300) and its context is at or "
            "above `max_resume_tokens`, the guard advises (default) or DENIES (`mode: "
            "deny`). Spawn a fresh agent briefed from the stopped one's report or handoff "
            "file instead (one task per agent). A message to a RUNNING agent, a warm "
            "resume and a name this session does not know are never gated. When the "
            "resume is genuinely worth it, start the message with "
            "`RESUME-LARGE: <reason>`; it is allowed and recorded in the spend ledger."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """The deny case and its warm near miss, harness-undrivable: both need a real transcript."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="resume guard - a cold resume of a large stopped agent is refused",
                command="SendMessage a NEW TASK to a finished teammate idle for an hour at 300k context",
                description=(
                    "Under mode: deny the message is refused, naming the fresh-spawn route "
                    "and the agent's last report. Unit tests in "
                    "tests/unit/handlers/pre_tool_use/test_resume_guard.py cover the matrix."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"COLD RESUME", r"RESUME-LARGE"],
                safety_notes="Never gates a running agent, a warm resume or an unknown name.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "It judges a real teammate's transcript (stopped, cold, large); the "
                    "harness cannot fabricate one in the session directory."
                ),
            ),
            AcceptanceTest(
                title="resume guard - a warm resume of the same large agent is allowed",
                command=(
                    "SendMessage a follow-up to a teammate at 300k context within a minute "
                    "of it finishing its turn"
                ),
                description=(
                    "The agent is stopped and large but still inside the cache TTL "
                    "(warm_seconds), so the resume is cache reads only and passes with no "
                    "advisory."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="The near miss of the deny case: only the idle time differs.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "It judges a real teammate's transcript (stopped, warm, large); the "
                    "harness cannot fabricate one in the session directory."
                ),
            ),
        ]
