"""UsagePauseToolGateHandler - a usage-paused session uses only the cron tools.

Plan 00479 Task 4.2. A session paused on its host usage ceiling has one job
left: replace its crons with the resume cron and wind up its subagents. So while the
pause record is live (``utils.usage_pause``) the only tools the MAIN thread may use are
``PAUSE_ALLOWED_TOOLS`` (the cron tools, ``SendMessage`` and ``TaskStop``); every other
call is denied, which includes starting a new subagent (``Agent``/``Task``).

**Subagents are never denied or halted** (owner ruling, Plan 00479 round 4): in-flight
subagents finish and the main thread winds them up. A subagent over the ceiling still
STARTS the pause, so subagent activity cannot keep the session from pausing; the main
thread's next call then gets the directive.

The deny also HALTS the turn (``continue: false`` plus a ``stopReason``,
``GatingResult.deny_and_halt``). A plain deny only refuses one call and the
model would try another; a turn that was already running when the ceiling was
reached stops at its next tool call instead of continuing to spend usage.

Terminal, first on the event: its deny is the final word on the call, and it
must not be pre-empted by a later handler's own (non-halting) deny.

``ToolSearch`` is allowed too: the cron tools are deferred built-ins whose
schemas load only through it (``constants/tools.py``).

**Entry (Plan 00479 M3).** A session kept going by Stop continuations or one long
turn never submits a prompt, so ``usage_pause_gate`` never sees it. This handler
therefore also ENTERS the pause (``try_start_pause``, the same entry the prompt
gate uses) when the host ceiling is reached. The call that starts it is a plain deny
carrying the directive, NOT a halt: ``continue: false`` ends the turn and its
``stopReason`` is not shown to the model (``CLAUDE/Code/HooksSystem.md``), so a halt
would leave the directive unread. That holds for the first main-thread call after a
pause a SUBAGENT started too (a subagent cannot ``CronDelete``,
``R-SUBAGENT-CRON-DELETE``, so only the main thread acts on the directive). Later
main-thread calls halt. The ceiling check
reads the in-memory usage snapshot and is skipped altogether for a host with no
ceiling, so the cost on every tool call is one config-cache lookup and one stat.

Reads the same record every usage-pause gate does and fails open: no project
context, no record, another session, a read error -- nothing is paused.
"""

from __future__ import annotations

from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.handler_scope import in_subagent
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.utils.usage_pause_gate import (
    PAUSE_ALLOWED_TOOLS,
    PauseEnvironment,
    active_usage_pause,
    render_pause_directive,
    tool_allowed_while_paused,
    try_start_pause,
)

_ALLOWED_TEXT: Final[str] = ", ".join(sorted(PAUSE_ALLOWED_TOOLS))

_STOP_REASON: Final[str] = (
    "Session paused on its usage ceiling: only the cron and subagent wind-up tools are "
    "allowed until the resume cron fires."
)

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.USAGE_PAUSE_TOOL,
    blocked=f"any tool except {_ALLOWED_TEXT} while the session is paused on its usage ceiling",
    why="The session stopped taking on work to keep the account under its usage ceiling",
    fix="Replace the session's crons with the one resume cron, then stop; the session resumes at the window reset",
    verbose=(
        "WHY BLOCKED:\n"
        "This session is PAUSED (Plan 00479): a usage window reached the ceiling\n"
        "configured for this host. Until it resumes, the only tools allowed are\n"
        f"{_ALLOWED_TEXT}. The turn is halted so it cannot keep spending usage.\n\n"
        "DO INSTEAD:\n"
        "  0. The cron tools are deferred: load them with ToolSearch if needed.\n"
        "  1. CronList, then CronDelete every cron listed.\n"
        "  2. CronCreate ONE recurring resume cron, exactly as the pause directive\n"
        "     gave it (its prompt starts [tick:usage-resume]).\n"
        "  3. Do not start new subagents; let running ones finish.\n"
        "  4. Stop. The session resumes by itself after the window reset.\n\n"
        "A human can run `bin/hooks-daemon usage-pause clear` (in a terminal): it removes the\n"
        "pause and no pause is started for this session again until the latest reset among\n"
        "the windows over the ceiling (at most 8 days)."
    ),
)


class UsagePauseToolGateHandler(PreToolUseHandlerBase):
    """Deny and halt the main thread's tools outside the pause allow-list while paused."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.USAGE_PAUSE_TOOL_GATE,
            priority=Priority.USAGE_PAUSE_TOOL_GATE,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.WORKFLOW],
        )
        # The seams entry reads the world through; tests substitute fakes.
        self._env = PauseEnvironment()
        # Sessions whose pause THIS call just started (set by ``matches``, read by ``handle``).
        self._entered: set[str] = set()

    def get_default_enabled(self) -> bool:
        """On by default; inert unless a usage pause is recorded or the ceiling is reached."""
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A tool outside the allowed set, in a paused session or one that just crossed.

        Entry from here (Plan 00479 M3) covers a session kept going by Stop
        continuations and long turns, which never submit a new prompt. Total:
        any failure reading the record or the ceiling is "not paused".
        """
        if tool_allowed_while_paused(hook_input.get(HookInputField.TOOL_NAME)):
            return False
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        if not session_id:
            return False
        subagent = in_subagent(hook_input)
        if active_usage_pause(session_id, now=self._env.clock()) is not None:
            # A subagent is never refused: in-flight subagents finish (Plan 00479 round 4).
            return not subagent
        if try_start_pause(hook_input, self._env) is None:
            return False
        # The main thread has not seen the directive yet, whoever started the pause.
        self._entered.add(session_id)
        return not subagent

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny the (main-thread) call; halt the turn only once the model knows what to do.

        * The first main-thread call after a pause starts, from any thread, is a plain deny
          carrying the full directive: ``continue: false`` ends the turn and ``stopReason``
          is not shown to the model, so a halt here would leave the directive unread.
        * Every later main-thread call is denied and halts the turn.
        """
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        reason = RuleFormatter().verbose(_RULE)
        pause = active_usage_pause(session_id, now=self._env.clock())
        if pause is not None:
            reason = f"{reason}\n\n{render_pause_directive(pause)}"
        if session_id in self._entered:
            self._entered.discard(session_id)
            return GatingResult.deny(reason)
        return GatingResult.deny_and_halt(reason, stop_reason=_STOP_REASON)

    def get_rules(self) -> list[Rule]:
        """The single Rule backing this handler's deny."""
        return [_RULE]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## usage_pause_tool_gate — a usage-paused session uses only the cron tools\n\n"
            "While a session is paused on its host usage ceiling (see `usage_pause_gate`) "
            "every main-thread tool except `CronList`, `CronDelete`, `CronCreate`, "
            "`ToolSearch` (the cron tools are deferred; it loads them), `SendMessage` and "
            "`TaskStop` is denied, and the deny halts the turn (`continue: false`). That "
            "includes starting a new subagent; running subagents are never denied or "
            "halted, they finish, and you wind them up (message them, `TaskStop` idle or "
            "finished ones). A session that crosses the ceiling mid-turn is paused by its "
            "next tool call, from the main thread or a subagent; the next MAIN-thread call "
            "is refused WITHOUT a halt and carries the full directive so you can act on "
            "it. Replace the session's crons with the one recurring resume cron the pause "
            "directive describes, then stop. The session resumes by itself after the "
            "window reset."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One case, declared as harness-undrivable.

        The deny needs a live pause record for the probe's session, and a probe
        cannot write one without changing the very state it is meant to observe;
        without it the gate (correctly) allows. The behaviour is covered by unit
        tests, and by the Plan 00479 Task 4.8 live probe with a synthetic
        snapshot above the ceiling.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="usage pause tool gate - a non-cron tool is denied while paused",
                command="Bash a command while the session is usage-paused",
                description=(
                    "With a live usage pause for the session, a Bash call is denied and "
                    "the turn halted; CronList, CronDelete and CronCreate are allowed."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"paused", r"CronCreate"],
                safety_notes="Denies only while a usage pause record is live for the session.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "The deny needs a live usage-pause record for the probe's session, and "
                    "a probe cannot create one without altering the state it observes; with "
                    "none, the gate allows by design. Verified by unit tests and the Plan "
                    "00479 Task 4.8 live probe."
                ),
            ),
            AcceptanceTest(
                title="usage pause tool gate - an ordinary tool call in an unpaused session",
                command="echo 'a session with no usage pause'",
                description=(
                    "Near-miss: with no usage pause recorded for the session (the default, "
                    "and every host without a usage ceiling) no tool is touched."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Negative case: the gate must be inert unless a pause is recorded.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                dispatch_as_bash=True,
            ),
        ]
