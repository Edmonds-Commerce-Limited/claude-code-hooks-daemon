"""CiStateReadingHandler - tell GitHub "queued" from stuck (Plan 00636 Task 2.3, s5).

The coordinator retrospective (00630 DESIGN.md section 19, s5) recorded a run
GitHub reported as "queued" being told to the team as stuck, and a seat
asserting what another seat's code did without asking it. After a ``gh run
list``, a ``gh run view --json`` or a ``gh pr checks`` on a coordinator seat,
this handler reads the output that command already printed
(``utils/ci_state.py``) and adds one context block: each not-started run read
as QUEUED (under ``options.stuck_after_minutes``), STUCK (at or past it),
PENDING (``gh pr checks`` cannot split queued from running) or UNKNOWN
(unreadable), followed by the rule to ask a seat before asserting its code.

Advisory only: it never denies, is never terminal, and runs no command or
network call of its own. Silent when the output shows nothing waiting to start,
so the seat probe runs only when there is something to say. The gate is the
shared ``coordinator_advisory_armed``: a declared coordinator, a coordinator
duty, an unreadable role or an unresolved probe hear it; a declared worker, no
team and a sub-agent do not. A fault reading the seat counts as armed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Protocol

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.ci_state import (
    CiCommandKind,
    ci_commands,
    read_ci_output,
    render_ci_readings,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.team_role_gate import coordinator_advisory_armed
from claude_code_hooks_daemon.utils.teamchat_seat import (
    SeatContext,
    SeatContextResolver,
    SessionSignals,
)

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import TeamSeatConfig

logger = logging.getLogger(__name__)

DEFAULT_STUCK_AFTER_MINUTES: Final[int] = 30
MAX_STUCK_AFTER_MINUTES: Final[int] = 1440
_SECONDS_PER_MINUTE: Final[int] = 60
_STDOUT_FIELD: Final[str] = "stdout"


class _SeatResolver(Protocol):
    def resolve(self, signals: SessionSignals) -> SeatContext: ...


class CiStateReadingHandler(PostToolUseHandlerBase):
    """Read a ``gh`` CI output as queued, stuck, pending or unknown. Advisory, never denies."""

    def __init__(self) -> None:
        """Initialise as a non-terminal advisory handler (see the module docstring)."""
        super().__init__(
            handler_id=HandlerID.CI_STATE_READING,
            priority=Priority.CI_STATE_READING,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )
        # Option, injected by the registry from ``options.stuck_after_minutes``; validated at use.
        self._stuck_after_minutes: object = DEFAULT_STUCK_AFTER_MINUTES
        # Injected by the registry from the top-level ``team_seat:`` block.
        self._team_seat: TeamSeatConfig | None = None
        # Seams, not config options.
        self._resolver: _SeatResolver | None = None
        self._clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def get_default_enabled(self) -> bool:
        """On by default; silent off a coordinator seat and when nothing is waiting to start."""
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A Bash command that runs a CI-reading ``gh`` command."""
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        command = get_bash_command(hook_input)
        return command is not None and bool(ci_commands(command))

    def _threshold_seconds(self) -> int:
        value = self._stuck_after_minutes
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 1 <= value <= MAX_STUCK_AFTER_MINUTES
        ):
            return value * _SECONDS_PER_MINUTE
        logger.warning(
            "ci_state_reading: options.stuck_after_minutes=%r is not an integer in 1..%d; "
            "using the default %d",
            value,
            MAX_STUCK_AFTER_MINUTES,
            DEFAULT_STUCK_AFTER_MINUTES,
        )
        return DEFAULT_STUCK_AFTER_MINUTES * _SECONDS_PER_MINUTE

    def _seat_resolver(self) -> _SeatResolver:
        if self._resolver is None:
            from claude_code_hooks_daemon.config.models import TeamSeatConfig

            config = self._team_seat if self._team_seat is not None else TeamSeatConfig()
            self._resolver = SeatContextResolver.from_config(config)
        return self._resolver

    def _armed(self, hook_input: dict[str, Any]) -> bool:
        try:
            context = self._seat_resolver().resolve(SessionSignals.from_hook_input(hook_input))
            return coordinator_advisory_armed(hook_input, context)
        except Exception as exc:  # the seat probe is a boundary; an advisory only adds text
            log_and_continue(
                logger,
                exc,
                reason="ci_state_reading could not read the seat, so it counts as armed: the reading only adds advisory text and never blocks",
                level=logging.WARNING,
            )
            return True

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Add the reading when the output shows a run or check that has not started."""
        silent = BlockingResult(decision=Decision.ALLOW, context=[])
        response = hook_input.get(HookInputField.TOOL_RESPONSE)
        if not isinstance(response, dict):
            return silent
        stdout = response.get(_STDOUT_FIELD)
        if not isinstance(stdout, str) or not stdout.strip():
            return silent
        kinds = ci_commands(get_bash_command(hook_input) or "")
        threshold = self._threshold_seconds()
        readings = read_ci_output(
            stdout,
            now=self._clock(),
            stuck_after_seconds=threshold,
            reshaped=CiCommandKind.RESHAPED in kinds,
        )
        if not readings or not self._armed(hook_input):
            return silent
        return BlockingResult(
            decision=Decision.ALLOW,
            context=[render_ci_readings(readings, stuck_after_seconds=threshold)],
        )

    def get_claude_md(self) -> str | None:
        """Resident guidance: the ask-the-seat rule holds whether or not a reading fires."""
        return (
            '## ci_state_reading — GitHub "queued" is not stuck; ask before asserting\n\n'
            "On a coordinator seat, after `gh run list`, `gh run view --json` or "
            "`gh pr checks`, the output already printed is read (no command or network "
            "call of its own): a run queued under `options.stuck_after_minutes` "
            f"(default {DEFAULT_STUCK_AFTER_MINUTES}) is QUEUED, normal waiting for a "
            "runner; at or past it, STUCK, with the `gh run view` check to make; "
            "`gh pr checks` `pending` folds queued and running, so it says PENDING and "
            "names the `gh run list --json` command that can tell; anything unreadable "
            "is UNKNOWN, never either. The reading is not a verification anyone can "
            "cite.\n\n"
            "Never tell the team what another seat's code does, or why its CI is red "
            "or stuck, without asking that seat on the bus first.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One test: the silent default; a reading needs a coordinator seat and a queued run."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="ci-state reading ignores gh named only as text",
                command='echo "gh run list: queued"',
                description=(
                    "Negative case, deterministic on any seat. `gh` is not in"
                    " command position here (it is echo's text) and no gh output"
                    " exists, so NO 'CI STATE READING' context may be added, even"
                    " on a coordinator seat. Readings themselves need a queued run"
                    " and a coordinator seat, which an acceptance run cannot"
                    " guarantee; they are covered by"
                    " tests/unit/handlers/post_tool_use/test_ci_state_reading.py and"
                    " tests/unit/utils/test_ci_state.py."
                ),
                expected_decision=Decision.ALLOW,
                # Deliberately empty: this test asserts that NOTHING is injected.
                expected_message_patterns=[],
                safety_notes="Harmless echo; advisory handler, never blocks.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=True,
            ),
        ]
