"""HostSeatLaneGuardHandler - a host-duty team seat runs no test, build, lint or QA (Plan 00635).

Owner ruling (lts-infra Q62, settled as Q64 D3): host seats are for deployment
and triage at desktop level; they are not workers. A session holding a
teamchat seat whose duty in ANY held team is ``host`` therefore has its test,
build, lint and QA commands refused, with a message naming the lane: run it in
a worker seat. Deployment and triage commands are untouched.

This is the dynamic, by-duty layer only. The static layer (a ``cc-deny.json``
written from the seat's duty) belongs to fedora-desktop; this handler builds
no deny rules.

Arming is :func:`team_role_gate.duty_gate` on ``host``:

- no team (no teamchat runtime, ``whoami`` exit 69, no seats), or a seat with
  no ``host`` duty in any held team: silent, no change. Duty is a teams-only,
  optional field, so a row whose duty is null, absent or unreadable declares
  nothing and does not arm (owner ruling D1);
- a declared ``host`` duty in any held team: armed, whatever the other rows
  say. A sub-agent of that seat is armed too, on the DECLARED duty only, and
  is only ever advised, never denied, whatever the mode (owner answer to Q1);
- a probe that gave no answer, in a session that resolved a seat earlier:
  armed on the main thread, because an unreadable probe never disarms a seat
  proven to be in a team. A session that never resolved a seat is not proven
  to be in one (D3) and stays silent. The first refusal says the probe gave
  no answer.

The lane commands are a SHORT per-language list held by the strategies in
``strategies/lane_commands/`` (test runners, builds, linters, QA scripts; not
installs, containers or watches, which are deployment and triage). They are
judged through the shared peel in :mod:`utils.long_running_command`, which
reads the common wrappers, ``sh -c`` bodies and backgrounded or
``timeout``-bounded runs: the lane is about WHAT runs, not how long. The long
tail of wrapper spellings is deliberately not chased, since this guard advises.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final, Protocol

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.handler_scope import acts_as_main_thread
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.strategies.lane_commands.common import (
    HARNESS_CANNOT_PRODUCE,
    runs_any,
)
from claude_code_hooks_daemon.strategies.lane_commands.registry import (
    LaneCommandStrategyRegistry,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.team_role_gate import GateVerdict, duty_gate
from claude_code_hooks_daemon.utils.teamchat_seat import (
    DUTY_HOST,
    SeatContext,
    SessionSignals,
    TeamOnlyGuidance,
    shared_resolver,
)

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import TeamSeatConfig

logger = logging.getLogger(__name__)

MODE_OFF: Final[str] = "off"
MODE_ADVISE: Final[str] = "advise"
MODE_BLOCK: Final[str] = "block"
_MODES: Final[frozenset[str]] = frozenset({MODE_OFF, MODE_ADVISE, MODE_BLOCK})
_OPTION_MODE: Final[str] = "mode"
_OPTION_EXTRA: Final[str] = "extra_lane_patterns"

_LANE_REGISTRY: Final[LaneCommandStrategyRegistry] = LaneCommandStrategyRegistry.create_default()
#: Every language's lane commands: the strategies in ``strategies/lane_commands/``.
LANE_PATTERNS: Final[tuple[str, ...]] = _LANE_REGISTRY.get_lane_patterns()
#: Sessions already told the probe gave no answer; cleared when it reaches this size.
_MAX_NOTED_SESSIONS: Final[int] = 1024

_LANE: Final[str] = (
    "Host seats are for deployment and triage, not for running tests: run it in a worker seat."
)
_REFUSAL: Final[str] = (
    "Host seat lane: this session holds a teamchat seat with duty host, and this is a "
    f"test, build, lint or QA command. {_LANE}"
)
_UNKNOWN_REFUSAL: Final[str] = (
    "Host seat lane: the teamchat probe gave no answer, so the guard stays armed, and "
    f"this is a test, build, lint or QA command. If this is a host seat: {_LANE}"
)
_NO_ANSWER: Final[str] = "The teamchat whoami probe gave no answer."
_HANDLER_ERROR: Final[str] = (
    "Host seat lane: the guard could not judge this command, so it is treated as a "
    f"test, build, lint or QA command. {_LANE}"
)

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.HOST_SEAT_LANE,
    blocked=(
        "a test, build, lint or QA command in a session holding a teamchat seat with "
        "duty host (or whose teamchat probe gives no answer)"
    ),
    why="Host seats are for deployment and triage at desktop level; they are not workers",
    fix="Run it in a worker seat of the team",
    verbose=(
        "WHY BLOCKED:\n"
        "This session holds a teamchat seat whose duty is host in some team (or\n"
        "the teamchat probe gave no answer), and the command runs tests, a build, a linter\n"
        "or QA. Host seats are for deployment and triage, not for worker lanes.\n\n"
        "DO INSTEAD:\n"
        "  Hand the command to a worker seat of the team.\n"
        "Deployment and triage commands are never refused here."
    ),
)


class _SeatResolver(Protocol):
    def resolve(self, signals: SessionSignals) -> SeatContext: ...


def is_lane_command(command: str, *, extra_patterns: Sequence[str] = ()) -> bool:
    """Whether ``command`` runs a test, build, lint or QA command anywhere in it.

    Text bash hands over as data (an ``echo`` argument, a commit message) is
    never read as a command; ``sh -c`` bodies, wrappers and backgrounded
    statements are.
    """
    return runs_any(command, (*LANE_PATTERNS, *extra_patterns))


class HostSeatLaneGuardHandler(TeamOnlyGuidance, PreToolUseHandlerBase):
    """Refuse a host-duty seat's test, build, lint or QA command."""

    _mode: str | None = MODE_ADVISE
    _extra_lane_patterns: list[str] | None = None

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.HOST_SEAT_LANE_GUARD,
            priority=Priority.HOST_SEAT_LANE_GUARD,
            terminal=True,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        # Injected by the registry from the `team_seat:` block.
        self._team_seat: TeamSeatConfig | None = None
        self._resolver: _SeatResolver | None = None
        self._noted_sessions: set[str] = set()

    @staticmethod
    def validate_options(options: Mapping[str, Any]) -> dict[str, str]:
        """Refuse a malformed option; the handler then runs on its default for it."""
        problems: dict[str, str] = {}
        if _OPTION_MODE in options and options[_OPTION_MODE] not in _MODES:
            problems[_OPTION_MODE] = f"mode must be one of {', '.join(sorted(_MODES))}"
        if _OPTION_EXTRA in options:
            problem = _pattern_problem(options[_OPTION_EXTRA])
            if problem:
                problems[_OPTION_EXTRA] = problem
        return problems

    def is_dormant(self) -> bool:
        """Whether config leaves this handler unable to fire."""
        return self._mode == MODE_OFF

    def _seat_resolver(self) -> _SeatResolver:
        return self._resolver if self._resolver is not None else shared_resolver(self._team_seat)

    def _verdict(self, hook_input: Mapping[str, Any]) -> GateVerdict:
        """The duty gate on ``host``.

        NOT_APPLICABLE with no teamchat runtime, and no probe run. ROLE_UNKNOWN
        only when the probe gave no answer in a session that resolved a seat
        earlier (the shared resolver's D3 rule). An undeclared duty is
        NOT_APPLICABLE (D1, in ``duty_gate``); a host in one team is never
        disarmed by a null duty in another. A sub-agent is judged as its seat
        on a DECLARED duty only (``include_subagents``).
        """
        signals = SessionSignals.from_hook_input(hook_input)
        if not signals.runtime:
            return GateVerdict.NOT_APPLICABLE
        context = self._seat_resolver().resolve(signals)
        return duty_gate(hook_input, context, duty=DUTY_HOST, include_subagents=True).verdict

    def _is_lane(self, hook_input: Mapping[str, Any]) -> bool:
        command = get_bash_command(dict(hook_input)) or ""
        return is_lane_command(command, extra_patterns=tuple(self._extra_lane_patterns or ()))

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """An armed seat running a test, build, lint or QA command.

        The seat is resolved (TTL-cached) BEFORE the command is classified, so
        a failure before arming is silent (a seatless session must see no
        change) and a failure classifying for an armed seat counts as the lane
        command (fail closed).
        """
        if self.is_dormant() or hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        try:
            verdict = self._verdict(hook_input)
        except Exception as exc:
            log_and_continue(
                logger,
                exc,
                reason="a failure before arming leaves the guard silent; a seatless session must see no change",
            )
            return False
        if verdict is GateVerdict.NOT_APPLICABLE:
            return False
        try:
            return self._is_lane(hook_input)
        except Exception as exc:
            log_and_continue(
                logger,
                exc,
                reason="a failure classifying an armed seat's command counts as a lane command (fail closed)",
            )
            return True

    def get_rules(self) -> list[Rule]:
        """The rule behind the deny."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """The mode's refusal for an armed lane command; otherwise allow. Never raises."""
        try:
            return self._judge(hook_input)
        except Exception as exc:
            log_and_continue(
                logger,
                exc,
                reason="a failure after arming is the mode's refusal; the exception text is never shown",
            )
            return self._refuse(_HANDLER_ERROR, hook_input)

    def _judge(self, hook_input: dict[str, Any]) -> GatingResult:
        verdict = self._verdict(hook_input)
        if verdict is GateVerdict.NOT_APPLICABLE or not self._is_lane(hook_input):
            return GatingResult(decision=Decision.ALLOW)
        if verdict is GateVerdict.ROLE_UNKNOWN:
            # Only an unanswered probe reaches here; see _verdict.
            if self._first_note(hook_input):
                return self._refuse(f"{_UNKNOWN_REFUSAL} {_NO_ANSWER}", hook_input)
            return self._refuse(_UNKNOWN_REFUSAL, hook_input)
        return self._refuse(_REFUSAL, hook_input)

    def _first_note(self, hook_input: Mapping[str, Any]) -> bool:
        """Whether this is the session's first no-answer refusal (then remembered)."""
        session = str(hook_input.get(HookInputField.SESSION_ID) or "")
        if session in self._noted_sessions:
            return False
        if len(self._noted_sessions) >= _MAX_NOTED_SESSIONS:
            self._noted_sessions.clear()
        self._noted_sessions.add(session)
        return True

    def _refuse(self, text: str, hook_input: Mapping[str, Any]) -> GatingResult:
        """The mode's refusal. A sub-agent is only ever advised (owner answer to Q1)."""
        if self._mode == MODE_BLOCK and acts_as_main_thread(hook_input):
            return GatingResult(decision=Decision.DENY, reason=text).under_rule(_RULE)
        return GatingResult(decision=Decision.ALLOW, context=[f"{text} [{RuleID.HOST_SEAT_LANE}]"])

    def get_claude_md(self) -> str | None:
        """Resident guidance: what a host-duty seat must not run."""
        return (
            "## host_seat_lane_guard — a host seat does not run tests\n\n"
            "In a session holding a teamchat seat whose duty is `host` in any team, "
            "test, build, lint and QA commands (`pytest`, `npm test`, `make test`, "
            "`ruff`, `mypy`, `llm_qa.py`, also via `sh -c`, wrappers or `&`) are "
            "refused: host seats are for deployment and triage. Hand the command to a "
            "worker seat. Deployment and triage commands are never refused. Only an "
            "explicit `host` duty arms it: a session with no team seat, or a seat whose "
            "duty is null or missing, is never affected. If the teamchat probe gives "
            "no answer at all the guard stays armed. `mode: advise` (the default) only "
            "reports; `mode: block` denies."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """This handler's own tests plus one lane refusal per language strategy.

        All are harness-undrivable: arming needs a live teamchat seat with duty host.
        """
        strategy_tests = [
            test
            for strategy in _LANE_REGISTRY.strategies()
            for test in strategy.get_acceptance_tests()
        ]
        return [*self._own_acceptance_tests(), *strategy_tests]

    def _own_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="host seat lane guard - a wrapped test run from a host seat is refused",
                command="nice -n 19 pytest tests/unit",
                description=(
                    "Under mode: block a host-duty seat's pytest is denied through a "
                    "wrapper (the bare form is the Python strategy's test). Unit tests in "
                    "tests/unit/handlers/pre_tool_use/test_host_seat_lane_guard.py cover "
                    "the matrix."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"R-HOST-SEAT-LANE", r"worker seat"],
                safety_notes="Never runs the tests: the command is denied before it starts.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=HARNESS_CANNOT_PRODUCE,
            ),
            AcceptanceTest(
                title="host seat lane guard - a triage command is untouched",
                command="git status",
                description="A triage command, in any session, passes with no advisory.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only command.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=HARNESS_CANNOT_PRODUCE,
            ),
        ]


def _pattern_problem(value: object) -> str:
    """Why ``value`` is not a list of valid regexes; empty when it is."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return "extra_lane_patterns must be a list of regex strings"
    for pattern in value:
        try:
            re.compile(pattern)
        except re.error as exc:
            return f"extra_lane_patterns entry {pattern!r} is not a valid regex: {exc}"
    return ""
