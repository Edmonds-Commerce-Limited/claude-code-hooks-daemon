"""OwnerDirectivesRegisterHandler - replay the owner's recorded directives (Plan 00636 Task 2.2, s3).

The coordinator retrospective counted one owner directive given about eight
times. The register records each directive ONCE, in config
(``options.directives``), and replays it to a coordinator seat so the seat
checks the list before asking the owner again. It is a filing cabinet, in the
manner of ``standing_authorisations``: the text is a recorded request, never a
countermand, never a fresh human instruction and never a citable approval.

Advisory only: it never denies and is never terminal, so it cannot form a
refuse/continue loop. It is silent unless ``options.directives`` holds at least
one valid entry, and then speaks only on a seat the 00631 probe does not rule
out: a declared coordinator (or a coordinator duty), an unreadable role or an
unresolved probe, exactly as ``owner_wait_stop_guard`` arms. A declared worker,
no team and a sub-agent are untouched. Delivered on the first human prompt of a
session and every ``prompt_interval`` human prompts after, so it survives
compaction; machine turns neither count nor deliver.

Not built (unsettled; see the Task 2.2 note in the plan): detecting a repeated
owner directive from the bus, writing a directive into the register, and
detecting that a seat re-asked one.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final, Protocol

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, TeamSeatConfig
from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.handlers.utils.bounded_fifo_map import BoundedFifoMap
from claude_code_hooks_daemon.utils.automated_prompt import is_automated_prompt
from claude_code_hooks_daemon.utils.config_cache import default_config, load_config_cached
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.owner_directives import (
    Directive,
    parse_directives,
    render_directives,
)
from claude_code_hooks_daemon.utils.team_role_gate import GateVerdict, duty_gate, role_gate
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ROLE_COORDINATOR,
    SeatContext,
    SeatContextResolver,
    SeatState,
    SessionSignals,
)

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_INTERVAL: Final[int] = 10
MAX_PROMPT_INTERVAL: Final[int] = 1000
_MAX_TRACKED_SESSIONS: Final[int] = 512
_UNKNOWN_SESSION: Final[str] = "unknown"
_ARMED_VERDICTS: Final[tuple[GateVerdict, ...]] = (GateVerdict.APPLIES, GateVerdict.ROLE_UNKNOWN)


class _SeatResolver(Protocol):
    def resolve(self, signals: SessionSignals) -> SeatContext: ...


class OwnerDirectivesRegisterHandler(UserPromptSubmitHandlerBase):
    """Replay the owner's recorded directives to a coordinator seat. Advisory, never denies."""

    def __init__(self) -> None:
        """Initialise as a non-terminal advisory handler (see the module docstring)."""
        super().__init__(
            handler_id=HandlerID.OWNER_DIRECTIVES_REGISTER,
            priority=Priority.OWNER_DIRECTIVES_REGISTER,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )
        # Options, injected by the registry from ``options.<name>``; validated at use.
        self._directives: object = None
        self._prompt_interval: object = DEFAULT_PROMPT_INTERVAL
        # Seams, not config options.
        self._resolver: _SeatResolver | None = None
        self._prompts_since: BoundedFifoMap[str, int] = BoundedFifoMap(
            max_entries=_MAX_TRACKED_SESSIONS
        )

    def get_default_enabled(self) -> bool:
        """On by default; silent without a register and inert off a coordinator seat."""
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match any prompt-bearing UserPromptSubmit event."""
        return isinstance(hook_input.get(HookInputField.PROMPT), str)

    # -- options -----------------------------------------------------------------

    def _interval(self) -> int:
        value = self._prompt_interval
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 1 <= value <= MAX_PROMPT_INTERVAL
        ):
            return value
        logger.warning(
            "owner_directives_register: options.prompt_interval=%r is not an integer in 1..%d; "
            "using the default %d",
            value,
            MAX_PROMPT_INTERVAL,
            DEFAULT_PROMPT_INTERVAL,
        )
        return DEFAULT_PROMPT_INTERVAL

    def _register(self) -> tuple[Directive, ...]:
        register = parse_directives(self._directives)
        for problem in register.problems:
            logger.warning("owner_directives_register: %s; it is skipped", problem)
        return register.directives

    # -- seat gate ---------------------------------------------------------------

    def _team_seat_config(self) -> TeamSeatConfig:
        root = getattr(self, "_workspace_root", None)
        try:
            project_root = Path(root) if root is not None else ProjectContext.project_root()
            config: Config = load_config_cached(project_root / ".claude" / "hooks-daemon.yaml")
        except (ValidationError, OSError, ValueError, RuntimeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="an unlocatable or unloadable project config falls back to the default team_seat block, which still probes a session carrying a teamchat runtime",
            )
            config = default_config()
        return config.team_seat

    def _context(self, hook_input: dict[str, Any]) -> SeatContext:
        if self._resolver is None:
            self._resolver = SeatContextResolver.from_config(self._team_seat_config())
        return self._resolver.resolve(SessionSignals.from_hook_input(hook_input))

    def _armed(self, hook_input: dict[str, Any]) -> bool:
        """Whether this seat gets the register: a coordinator, an unreadable role or a duty.

        Mirrors ``owner_wait_stop_guard``: an unreadable role or probe keeps the
        advisory on (it only adds text); a declared worker, no team and a
        sub-agent are untouched. A fault reading the seat counts as armed.
        """
        try:
            context = self._context(hook_input)
            if context.state is SeatState.UNRESOLVED:
                gate = role_gate(hook_input, context, team="", role=ROLE_COORDINATOR)
                return gate.verdict in _ARMED_VERDICTS
            for team in context.teams_held():
                gate = role_gate(hook_input, context, team=team, role=ROLE_COORDINATOR)
                if gate.verdict in _ARMED_VERDICTS:
                    return True
            return duty_gate(hook_input, context, duty=ROLE_COORDINATOR).verdict is (
                GateVerdict.APPLIES
            )
        except Exception as exc:  # the seat probe is a boundary; an advisory only adds text
            log_and_continue(
                logger,
                exc,
                reason="owner_directives_register could not read the seat, so it counts as armed: the replay only adds advisory text and never blocks",
                level=logging.WARNING,
            )
            return True

    # -- handle ------------------------------------------------------------------

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Replay the register on the first human prompt and every ``prompt_interval`` after."""
        directives = self._register()
        if not directives:
            return BlockingResult(decision=Decision.ALLOW, context=[])
        prompt = str(hook_input.get(HookInputField.PROMPT, "") or "")
        if is_automated_prompt(prompt):
            return BlockingResult(decision=Decision.ALLOW, context=[])
        session = str(hook_input.get(HookInputField.SESSION_ID, "") or _UNKNOWN_SESSION)
        seen = self._prompts_since.get(session)
        interval = self._interval()
        due = seen is None or seen + 1 >= interval
        if not due:
            self._prompts_since.put(session, (seen or 0) + 1)
            return BlockingResult(decision=Decision.ALLOW, context=[])
        if not self._armed(hook_input):
            return BlockingResult(decision=Decision.ALLOW, context=[])
        self._prompts_since.put(session, 0)
        return BlockingResult(decision=Decision.ALLOW, context=[render_directives(directives)])

    def get_claude_md(self) -> str | None:
        """None: the replayed register is the whole message (see the guidance coverage table)."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """None: it needs a teamchat coordinator seat, which an acceptance run does not hold."""
        return []
