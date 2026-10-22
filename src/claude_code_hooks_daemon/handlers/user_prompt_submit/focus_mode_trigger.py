"""FocusModeTriggerHandler - the ``hooks-daemon focus`` prompt command (Plan 00501 Task 3.1).

A genuine human prompt that OPENS with ``hooks-daemon focus <task>`` (any case,
or the speech-to-text spellings ``hooks daemon`` / ``hooks demon``) turns focus
on for this session only; ``hooks-daemon focus off`` (aliases ``done``, ``end``,
``disable``) turns it off. Either is stated back in exactly one context line,
and the prompt still reaches the model, so the task it names is the stated task.

Every other genuine human prompt renews the session's focus (TTL, ruling 02),
classified from the prompt text alone. On EVERY prompt, command or not, the
session's pending mode news (an expiry; after a daemon restart, what survived
or was cleared, a usage pause included) is stated in one line by
``core.session_mode_statement``, the registry notices' only reader (Task 4.2).

Never gated by autonomy (``drives_autonomy`` stays False): focus itself halts
every work-driving handler, so a gated trigger could never turn it off. Never
denies. A registry failure is logged at WARNING; on a command it is also stated
to the agent, since the human asked for something that did not happen.
"""

from __future__ import annotations

import logging
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.data_layer import get_data_layer
from claude_code_hooks_daemon.core.focus_mode import (
    FocusCommand,
    enter_focus,
    exit_focus,
    parse_focus_command,
)
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.core.session_mode_statement import pending_mode_statement
from claude_code_hooks_daemon.daemon.controller import get_controller
from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import clear_goal_signal
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.session_modes import UsagePauseView
from claude_code_hooks_daemon.utils.usage_pause_gate import active_usage_pause

logger = logging.getLogger(__name__)

#: The transition log's evidence for a focus change typed at the prompt.
_COMMAND_EVIDENCE = "the human's `hooks-daemon focus` prompt command"


def _session_id(hook_input: dict[str, Any]) -> str:
    value = hook_input.get(HookInputField.SESSION_ID)
    return value.strip() if isinstance(value, str) else ""


def _usage_pause_view(session_id: str) -> UsagePauseView | None:
    """The session's live usage pause, as the restatement needs it."""
    pause = active_usage_pause(session_id)
    if pause is None:
        return None
    return UsagePauseView(paused_at=pause.paused_at, until=pause.expires_at, reason=pause.reason)


def _daemon_is_unattended() -> bool:
    """Whether the daemon-wide mode is ``unattended``."""
    mode = get_controller().get_mode().get(ModeConstant.KEY_MODE)
    return bool(mode == DaemonMode.UNATTENDED.value)


class FocusModeTriggerHandler(UserPromptSubmitHandlerBase):
    """Turn the session's focus mode on or off from the prompt; renew it on every human prompt."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.FOCUS_MODE_TRIGGER,
            priority=Priority.FOCUS_MODE_TRIGGER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every string prompt: a command, a renewal or a pending notice may apply."""
        return isinstance(hook_input.get(HookInputField.PROMPT), str)

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Apply a focus command, or renew focus; state notices. Always ALLOW."""
        prompt = hook_input.get(HookInputField.PROMPT)
        session_id = _session_id(hook_input)
        command = parse_focus_command(prompt)
        if not session_id:
            if command is None:
                return BlockingResult(decision=Decision.ALLOW)
            logger.warning("focus_mode_trigger: a focus command arrived with no session id")
            return BlockingResult(
                decision=Decision.ALLOW,
                context=["FOCUS MODE NOT CHANGED: the prompt carried no session id."],
            )
        try:
            registry = get_data_layer().session_modes
            line = self._apply(registry, session_id, command, prompt)
            statement = pending_mode_statement(
                registry,
                session_id,
                usage_pause=lambda: _usage_pause_view(session_id),
                unattended=_daemon_is_unattended,
            )
        except (RuntimeError, OSError) as error:
            log_and_continue(
                logger,
                error,
                reason="the session-modes registry could not be used, so focus was neither changed nor renewed",
            )
            if command is None:
                return BlockingResult(decision=Decision.ALLOW)
            return BlockingResult(
                decision=Decision.ALLOW,
                context=[f"FOCUS MODE NOT CHANGED: the daemon could not record it ({error})."],
            )
        context = [] if statement is None else [statement]
        if line is not None:
            context.append(line)
        return BlockingResult(decision=Decision.ALLOW, context=context)

    @staticmethod
    def _apply(
        registry: SessionModeRegistry,
        session_id: str,
        command: FocusCommand | None,
        prompt: object,
    ) -> str | None:
        """Carry out ``command`` (or renew focus); the line to state, if any."""
        if command is None:
            registry.note_prompt(session_id, prompt)
            return None
        if command.is_off:
            return exit_focus(registry, session_id, evidence=_COMMAND_EVIDENCE).line()
        return enter_focus(
            registry,
            session_id,
            command.task,
            clear_goal=clear_goal_signal,
            evidence=_COMMAND_EVIDENCE,
        ).line()

    def get_claude_md(self) -> str | None:
        """Document the focus command."""
        return (
            "## focus_mode_trigger — `hooks-daemon focus <task>` points one session at one task\n\n"
            "A human prompt that STARTS with `hooks-daemon focus <task>` (any case; "
            "`hooks daemon` and `hooks demon` also work) turns focus on for that session "
            "only; `hooks-daemon focus off` (or `done`, `end`, `disable`) turns it off. "
            "While focused, declared cron ticks, goal injection and the goal-ledger stop "
            "challenge are off, the failsafe tick still arrives naming the task, and an "
            "existing goal is cleared once on entry. Focus lasts 12 hours, renewed by each "
            "prompt the human types. Also: `/mode focus <task>`, `/mode focus off`, or "
            "`hooks-daemon session-mode`.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One case: the trigger is a typed human prompt."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="hooks-daemon focus <task> turns focus on with one context line",
                command="Type the prompt: hooks-daemon focus write the release note",
                harness_cannot_produce=(
                    "The trigger is a prompt the human types; an agent under test cannot "
                    "submit a UserPromptSubmit prompt. Covered by "
                    "tests/unit/handlers/user_prompt_submit/test_focus_mode_trigger.py."
                ),
                description=(
                    "A human prompt opening with `hooks-daemon focus <task>` enters focus "
                    "for the session and injects one FOCUS MODE ON line naming the task."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"FOCUS MODE ON"],
                safety_notes="Advisory only; writes the session's session-modes file.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
