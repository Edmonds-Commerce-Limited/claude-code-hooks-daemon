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

- no team (no teamchat runtime, ``whoami`` exit 69, no seats), a sub-agent, or
  a seat whose duties are all declared and none is ``host``: silent, no change;
- a declared ``host`` duty: armed;
- a duty that cannot be read (the probe gave no answer, or a row with no
  duty): armed, because an unreadable state never disarms a guard. The first
  refusal in a session says the probe gave no answer.

The command classification is the shared one in
:mod:`utils.long_running_command`, taking its test, build and QA groups (not
installs, containers or watches, which are deployment and triage) plus the lint
and QA-script shapes below, and judging backgrounded or ``timeout``-bounded
runs too: the lane is about WHAT runs, not how long.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
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
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.long_running_command import (
    BUILD_PATTERNS,
    QA_PATTERNS,
    TEST_PATTERNS,
    FindingKind,
    LongRunningPolicy,
    classify,
)
from claude_code_hooks_daemon.utils.team_role_gate import GateVerdict, duty_gate
from claude_code_hooks_daemon.utils.teamchat_seat import (
    DUTY_HOST,
    SeatContext,
    SeatContextResolver,
    SeatState,
    SessionSignals,
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

#: Lint and type-check programs, and package-script spellings of lint/QA.
LINT_PATTERNS: Final[tuple[str, ...]] = (
    r"^(?:ruff|mypy|pyright|pylint|flake8|black|isort|bandit|eslint|prettier|stylelint"
    r"|shellcheck|golangci-lint|phpstan|psalm|phpcs|rubocop|hadolint|markdownlint|yamllint)\b",
    r"^(?:npm|yarn|pnpm|bun)\s+(?:run\s+)?(?:llm:)?(?:lint|typecheck|type-check|qa)\S*",
    r"^npx\s+(?:jest|vitest|playwright|mocha|tsc|eslint|prettier)\b",
    r"^cargo\s+fmt\b",
    # `python -m unittest` peels to `unittest`.
    r"^unittest\b",
)
#: ``make`` options whose value is the next word (or attached: ``-Csub``).
_MAKE_VALUED: Final[str] = "CfIoW"
_MAKE_LONG_VALUED: Final[str] = (
    "directory|file|makefile|include-dir|old-file|assume-old|new-file|assume-new|what-if"
)
#: One ``make`` option, each word read exactly one way (no backtracking blow-up):
#: a valued option with its value, ``-j``/``-l`` with an optional number, or any
#: other option.
_MAKE_OPTION: Final[str] = (
    rf"\s+(?:-[{_MAKE_VALUED}]\s*\S+"
    r"|-[jl](?:\s*\d+(?:\.\d+)?)?"
    rf"|--(?:{_MAKE_LONG_VALUED})\s+\S+"
    rf"|-(?![{_MAKE_VALUED}jl])(?!-(?:{_MAKE_LONG_VALUED})(?:\s|$))\S+)"
)
#: A target or a ``VAR=value`` word (never an option, never a bare number).
_MAKE_WORD: Final[str] = r"\s+(?![-\d])\S+"
_LANE_TARGETS: Final[str] = r"(?:test|tests|check|lint|build|qa|all|ci)\b"
#: ``make`` (or ``gmake``) with only options and assignments, or naming a
#: test/build/lint target anywhere. ``make deploy`` and ``make -C infra deploy``
#: are untouched.
LANE_MAKE_PATTERNS: Final[tuple[str, ...]] = (
    rf"^g?make(?:{_MAKE_OPTION}|\s+[A-Za-z_][A-Za-z0-9_]*=\S*)*\s*$",
    rf"^g?make(?:{_MAKE_OPTION}|{_MAKE_WORD})*?\s+{_LANE_TARGETS}",
)
#: Task runners and project managers, by their test/lint/build verbs only:
#: ``just deploy``, ``hatch publish`` and Taskwarrior's ``task add`` are untouched.
LANE_RUNNER_PATTERNS: Final[tuple[str, ...]] = (
    r"^(?:just|task)(?:\s+-\S+)*\s+(?:test|tests|check|lint|build|qa|ci|typecheck|fmt)\b",
    r"^hatch\s+(?:test|build|fmt)\b",
    r"^hatch\s+run(?:\s+-\S+)*\s+(?:(?:test|tests|lint|types|typing|qa|cov|style)[\w.-]*:\S+"
    r"|(?:[\w.-]+:)?(?:test|tests|cov|lint|check|typecheck|type-check|qa|pytest|mypy|ruff|fmt)\b)",
    r"^pre-commit(?:\s+-\S+)*(?:\s+(?:run|try-repo)\b|\s*$)",
)
_JS_RUNNER: Final[str] = r"(?:(?:pnpm|yarn|bun)(?:\s+(?:exec|dlx|x))?|npm\s+exec|npx|bunx|pnpx)"
#: Package-manager spellings the shared test/build patterns do not list.
LANE_PACKAGE_PATTERNS: Final[tuple[str, ...]] = (
    r"^(?:npm|pnpm)\s+(?:t|tst)(?:\s|$)",
    r"^(?:npm|yarn|pnpm|bun)\s+run-script\s+(?:llm:)?"
    r"(?:test|build|lint|typecheck|type-check|qa|check)\S*",
    r"^(?:npm|yarn|pnpm|bun)\s+run\s+check(?::\S*)?(?:\s|$)",
    rf"^{_JS_RUNNER}(?:\s+-\S+)*\s+(?:jest|vitest|playwright|mocha|tsc|eslint|prettier)\b",
)
#: A script named for tests, QA, lint or autofix: ``run_tests.sh``, ``llm_qa.py``,
#: ``test_x.py``, ``run_autofix.sh``. A deploy, smoke, health, publish or
#: connection check is triage even when its name carries ``test`` or ``qa``
#: (``deploy-qa.sh``, ``smoke_test.sh``).
QA_SCRIPT_PATTERNS: Final[tuple[str, ...]] = (
    r"^(?![\w.-]*(?:deploy|smoke|health|publish|connection))"
    r"(?:[\w.-]*[_.-])?(?:tests?|qa|lint|typecheck|type_check|autofix)(?:[_.-][\w.-]*)?"
    r"\.(?:sh|bash|py)\b",
)
#: The shared build group, except that a JVM build tool is judged by its goal:
#: ``mvn deploy`` and ``gradle publish`` ship an artefact and are deployment.
_SHIPPING_GOAL: Final[str] = r"(?!(?:.*\s)?(?:deploy|publish)(?:\s|$))"
LANE_BUILD_PATTERNS: Final[tuple[str, ...]] = (
    r"^(?:tsc|webpack|ant|cmake|ninja|bazel)\b",
    rf"^(?:gradle|gradlew|mvn){_SHIPPING_GOAL}\b",
    *BUILD_PATTERNS[1:],
)
#: A toolchain selector before the subcommand: ``cargo +nightly test``.
LANE_TOOLCHAIN_PATTERNS: Final[tuple[str, ...]] = (
    r"^cargo\s+\+\S+\s+(?:test|bench|build|check|clippy|fmt)\b",
)
LANE_PATTERNS: Final[tuple[str, ...]] = (
    *TEST_PATTERNS,
    *LANE_TOOLCHAIN_PATTERNS,
    *LANE_BUILD_PATTERNS,
    *QA_PATTERNS,
    *LINT_PATTERNS,
    *LANE_MAKE_PATTERNS,
    *LANE_RUNNER_PATTERNS,
    *LANE_PACKAGE_PATTERNS,
    *QA_SCRIPT_PATTERNS,
)
#: Any ``timeout`` counts as unbounded here, so a bounded test run is still judged.
_LANE_THRESHOLD_SECONDS: Final[float] = 0.0
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
    "Host seat lane: this session holds a teamchat seat whose duty cannot be read, so "
    "the guard stays armed, and this is a test, build, lint or QA command. If this is a "
    f"host seat: {_LANE}"
)
_NO_ANSWER: Final[str] = "The teamchat whoami probe gave no answer."
_NULL_DUTY: Final[str] = "The teamchat probe answered, but the seat's duty is not declared."
_HANDLER_ERROR: Final[str] = (
    "Host seat lane: the guard could not judge this command, so it is treated as a "
    f"test, build, lint or QA command. {_LANE}"
)

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.HOST_SEAT_LANE,
    blocked=(
        "a test, build, lint or QA command in a session holding a teamchat seat with "
        "duty host (or whose duty cannot be read)"
    ),
    why="Host seats are for deployment and triage at desktop level; they are not workers",
    fix="Run it in a worker seat of the team",
    verbose=(
        "WHY BLOCKED:\n"
        "This session holds a teamchat seat whose duty is host in some team (or\n"
        "its duty cannot be read), and the command runs tests, a build, a linter\n"
        "or QA. Host seats are for deployment and triage, not for worker lanes.\n\n"
        "DO INSTEAD:\n"
        "  Hand the command to a worker seat of the team.\n"
        "Deployment and triage commands are never refused here."
    ),
)


class _SeatResolver(Protocol):
    def resolve(self, signals: SessionSignals) -> SeatContext: ...


@lru_cache(maxsize=16)
def _lane_policy(extra_patterns: tuple[str, ...]) -> LongRunningPolicy:
    return LongRunningPolicy(
        threshold_seconds=_LANE_THRESHOLD_SECONDS,
        slow_patterns=tuple(re.compile(p) for p in (*LANE_PATTERNS, *extra_patterns)),
        deep_peel=True,
    )


def is_lane_command(command: str, *, extra_patterns: Sequence[str] = ()) -> bool:
    """Whether ``command`` runs a test, build, lint or QA command anywhere in it.

    Text bash hands over as data (an ``echo`` argument, a commit message) is
    never read as a command; ``sh -c`` bodies, wrappers and backgrounded
    statements are.
    """
    findings = classify(command, _lane_policy(tuple(extra_patterns)), include_background=True)
    return any(finding.kind is FindingKind.SLOW_COMMAND for finding in findings)


class HostSeatLaneGuardHandler(PreToolUseHandlerBase):
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
        if self._resolver is None:
            from claude_code_hooks_daemon.config.models import TeamSeatConfig

            config = self._team_seat if self._team_seat is not None else TeamSeatConfig()
            self._resolver = SeatContextResolver.from_config(config)
        return self._resolver

    def _verdict(self, hook_input: Mapping[str, Any]) -> tuple[GateVerdict, SeatState | None]:
        """The duty gate on ``host`` and the probe state behind it.

        NOT_APPLICABLE (state None) with no teamchat runtime, and no probe run.
        """
        signals = SessionSignals.from_hook_input(hook_input)
        if not signals.runtime:
            return GateVerdict.NOT_APPLICABLE, None
        context = self._seat_resolver().resolve(signals)
        return duty_gate(hook_input, context, duty=DUTY_HOST).verdict, context.state

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
            verdict, _state = self._verdict(hook_input)
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
            return self._refuse(_HANDLER_ERROR)

    def _judge(self, hook_input: dict[str, Any]) -> GatingResult:
        verdict, state = self._verdict(hook_input)
        if verdict is GateVerdict.NOT_APPLICABLE or not self._is_lane(hook_input):
            return GatingResult(decision=Decision.ALLOW)
        if verdict is GateVerdict.ROLE_UNKNOWN:
            if state is not SeatState.UNRESOLVED:
                # The probe answered; the seat's duty is null on the wire.
                return self._refuse(f"{_UNKNOWN_REFUSAL} {_NULL_DUTY}")
            if self._first_note(hook_input):
                return self._refuse(f"{_UNKNOWN_REFUSAL} {_NO_ANSWER}")
            return self._refuse(_UNKNOWN_REFUSAL)
        return self._refuse(_REFUSAL)

    def _first_note(self, hook_input: Mapping[str, Any]) -> bool:
        """Whether this is the session's first no-answer refusal (then remembered)."""
        session = str(hook_input.get(HookInputField.SESSION_ID) or "")
        if session in self._noted_sessions:
            return False
        if len(self._noted_sessions) >= _MAX_NOTED_SESSIONS:
            self._noted_sessions.clear()
        self._noted_sessions.add(session)
        return True

    def _refuse(self, text: str) -> GatingResult:
        if self._mode == MODE_BLOCK:
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
            "worker seat. Deployment and triage commands are never refused. If the "
            "seat's duty cannot be read the guard stays armed. `mode: advise` (the "
            "default) only reports; `mode: block` denies. A session with no team seat "
            "is never affected."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Harness-undrivable: arming needs a live teamchat seat with duty host."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        unseated = (
            "Arming needs a live teamchat runtime and a seat with duty host; the harness "
            "session holds no team seat, so the guard stays silent there."
        )
        return [
            AcceptanceTest(
                title="host seat lane guard - a test run from a host seat is refused",
                command="pytest tests/unit",
                description=(
                    "Under mode: block a host-duty seat's pytest is denied. Unit tests in "
                    "tests/unit/handlers/pre_tool_use/test_host_seat_lane_guard.py cover "
                    "the matrix."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"R-HOST-SEAT-LANE", r"worker seat"],
                safety_notes="Never runs the tests: the command is denied before it starts.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=unseated,
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
                harness_cannot_produce=unseated,
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
