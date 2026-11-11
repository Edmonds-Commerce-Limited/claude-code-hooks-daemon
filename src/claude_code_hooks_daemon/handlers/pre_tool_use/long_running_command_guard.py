"""Deny a long command run in the foreground of the main thread (Plan 00602).

A foreground Bash call blocks the session: messages from the owner and from
other agents wait until it ends. So a command that may take more than about
30 seconds must run with ``run_in_background``, and a foreground command must
carry a timeout.

``timeout N`` is the strongest sign. Nobody bounds a command at ten minutes
unless they expect it to run for minutes, so the wrapper is the flag that
forces the command into the background. The other signs are a wait loop
(``until``/``while`` with ``sleep``), ``sleep N`` above the threshold, and a
program on the known-slow list. Judgement is by command shape
(:mod:`claude_code_hooks_daemon.utils.long_running_command`); nothing is
measured.

**The role test is the scope key.** ``scope=MAIN`` admits an event only when it
carries no ``agent_id`` and is not synthetic, so a sub-agent's Bash call is
never judged (it blocks nobody's messages) and this module never reads
``agent_id``.

**What it never judges:** a call made with ``run_in_background: true``; a
command ending in a lone ``&``; a ``timeout`` at or below the threshold; and
anything the command-position view blanks as data (a commit message, an
``echo`` argument, a heredoc body).

**It cannot loop on its own text.** The deny gives the same command back with
``run_in_background`` set, which is never judged, and recommends the Monitor
tool for waiting on a condition. It never recommends a foreground ``timeout``
above the threshold. The command is echoed as a JSON field, so the text of a
deny is not itself a wait loop if it is ever pasted into a shell.

Ships OFF (``get_default_enabled`` is False): a client's workflow may
legitimately run a suite in the foreground, and the shipped ordinary-command
corpus holds foreground ``pytest`` rows the owner has not dropped.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.escape_hatch import command_declares_hatch
from claude_code_hooks_daemon.utils.long_running_command import (
    DEFAULT_THRESHOLD_SECONDS,
    Finding,
    FindingKind,
    LongRunningPolicy,
    classify,
)

_MODE_DENY: Final = "deny"
_MODE_ADVISE: Final = "advise"
_MODE_OFF: Final = "off"
_MODES: Final[tuple[str, ...]] = (_MODE_DENY, _MODE_ADVISE, _MODE_OFF)

_OPTION_MODE: Final = "mode"
_OPTION_THRESHOLD: Final = "threshold_seconds"
_OPTION_SLOW: Final = "extra_slow_patterns"
_OPTION_FAST: Final = "extra_fast_programs"
_OPTION_EXEMPT: Final = "exempt_patterns"

#: In-command opt-out, following the daemon's MUST_..._BECAUSE convention.
_ESCAPE_HATCH: Final = "MUST_RUN_FOREGROUND_BECAUSE"

_RUN_IN_BACKGROUND: Final = "run_in_background"
_TOOL_INPUT: Final = "tool_input"

#: Longest command text echoed back in a message.
_ECHO_LIMIT: Final = 240

_RULE_FOR_KIND: Final[dict[FindingKind, str]] = {
    FindingKind.WAIT_LOOP: RuleID.LONG_RUNNING_WAIT_LOOP,
    FindingKind.LONG_TIMEOUT: RuleID.LONG_RUNNING_TIMEOUT,
    FindingKind.LONG_SLEEP: RuleID.LONG_RUNNING_SLEEP,
    FindingKind.SLOW_COMMAND: RuleID.LONG_RUNNING_SLOW_COMMAND,
    FindingKind.UNBOUNDED: RuleID.LONG_RUNNING_NO_TIMEOUT,
}

_WHY: Final = (
    "A foreground Bash call in the main thread blocks the session: messages "
    "from the owner and from other agents wait until it ends."
)

_BACKGROUND_FIX: Final = (
    "Re-issue the same call with `run_in_background: true`; the harness "
    "notifies you when it ends. To wait for a condition (CI, a file, a "
    "process), start the waiter in the background or use the Monitor tool; "
    "never sleep-loop in the foreground."
)

_RULES: Final[tuple[Rule, ...]] = (
    Rule(
        rule_id=RuleID.LONG_RUNNING_WAIT_LOOP,
        blocked="a foreground `until`/`while` loop that sleeps in the main thread",
        why=_WHY,
        fix=_BACKGROUND_FIX,
        verbose=(
            "A loop that sleeps waits for something outside the command, so it "
            "ends when that thing happens, not when the command is done. Run "
            "it with `run_in_background: true`, or use the Monitor tool, which "
            "streams a condition's events without holding the session."
        ),
    ),
    Rule(
        rule_id=RuleID.LONG_RUNNING_TIMEOUT,
        blocked="a foreground `timeout N` wrapper with N above the threshold",
        why=_WHY + " A timeout of minutes is the tell that the command runs for minutes.",
        fix=_BACKGROUND_FIX,
        verbose=(
            "A timeout at or below `threshold_seconds` (default 30) is the "
            "explicit short bound a foreground command should carry, and is "
            "allowed. A longer one means the command is expected to run long: "
            "keep the `timeout` and run the call in the background."
        ),
    ),
    Rule(
        rule_id=RuleID.LONG_RUNNING_SLEEP,
        blocked="a foreground `sleep N` with N above the threshold",
        why=_WHY,
        fix=_BACKGROUND_FIX,
        verbose=(
            "A long sleep in the foreground only holds the session. Do the "
            "waiting in the background (a notification arrives when it ends) "
            "and keep working meanwhile."
        ),
    ),
    Rule(
        rule_id=RuleID.LONG_RUNNING_SLOW_COMMAND,
        blocked="a foreground run of a known-slow program (tests, QA, builds, installs)",
        why=_WHY,
        fix=_BACKGROUND_FIX,
        verbose=(
            "The slow list is `DEFAULT_SLOW_PATTERNS` in "
            "`utils/long_running_command.py` plus the project's "
            "`extra_slow_patterns`. A run bounded by a `timeout` at or below "
            "the threshold is allowed. Add a command a project runs fast to "
            "`exempt_patterns`."
        ),
    ),
    Rule(
        rule_id=RuleID.LONG_RUNNING_NO_TIMEOUT,
        blocked="(advisory only) a foreground command of unknown length with no timeout",
        why="Nothing says the command will end, and a foreground command blocks the session.",
        fix="Prefix `timeout <seconds>` (at or below the threshold), or run it in the background.",
        verbose=(
            "Advisory, never a deny. Programs on the known-fast list are not "
            "named. Add a fast project command to `extra_fast_programs`."
        ),
    ),
)

_RULE_BY_ID: Final[dict[str, Rule]] = {rule.rule_id: rule for rule in _RULES}

_DENYING_ORDER: Final[tuple[FindingKind, ...]] = (
    FindingKind.WAIT_LOOP,
    FindingKind.LONG_TIMEOUT,
    FindingKind.LONG_SLEEP,
    FindingKind.SLOW_COMMAND,
)


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(entry, str) for entry in value)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0


class LongRunningCommandGuardHandler(PreToolUseHandlerBase):
    """Send a likely-long foreground Bash call to ``run_in_background``.

    Options (``handlers.pre_tool_use.long_running_command_guard.options``):
        mode: ``deny`` (default), ``advise`` or ``off``.
        threshold_seconds: length counted as long (default 30); ``timeout N``
            and ``sleep N`` above it are findings.
        extra_slow_patterns: regexes added to the known-slow list, matched
            against ``<program> <arguments>`` after wrappers are peeled.
        extra_fast_programs: program names added to the known-fast list.
        exempt_patterns: regexes matched against the whole command; a match
            is never judged.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.LONG_RUNNING_COMMAND_GUARD,
            priority=Priority.LONG_RUNNING_COMMAND_GUARD,
            terminal=False,
            # The whole role test: a sub-agent's call blocks nobody's messages.
            scope=HandlerScope.MAIN,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.NON_TERMINAL],
        )
        # Options: applied by blind setattr AFTER __init__, so every read below
        # re-validates the type instead of trusting it.
        self._mode: Any = _MODE_DENY
        self._threshold_seconds: Any = DEFAULT_THRESHOLD_SECONDS
        self._extra_slow_patterns: Any = []
        self._extra_fast_programs: Any = []
        self._exempt_patterns: Any = []

    @staticmethod
    def validate_options(options: Mapping[str, Any]) -> dict[str, str]:
        """The configured options this handler refuses, keyed by option name."""
        problems: dict[str, str] = {}
        if _OPTION_MODE in options and options[_OPTION_MODE] not in _MODES:
            problems[_OPTION_MODE] = (
                f"long_running_command_guard mode must be one of {', '.join(_MODES)}, "
                f"got {options[_OPTION_MODE]!r}."
            )
        if _OPTION_THRESHOLD in options and not _is_number(options[_OPTION_THRESHOLD]):
            problems[_OPTION_THRESHOLD] = (
                "long_running_command_guard threshold_seconds must be a positive "
                f"number, got {options[_OPTION_THRESHOLD]!r}."
            )
        for option in (_OPTION_SLOW, _OPTION_FAST, _OPTION_EXEMPT):
            if option in options and not _is_string_list(options[option]):
                problems[option] = (
                    f"long_running_command_guard {option} must be a list of strings, "
                    f"got {options[option]!r}."
                )
        if _OPTION_SLOW not in problems and _OPTION_EXEMPT not in problems:
            try:
                LongRunningPolicy.build(
                    extra_slow_patterns=options.get(_OPTION_SLOW, []),
                    exempt_patterns=options.get(_OPTION_EXEMPT, []),
                )
            except ValueError as exc:
                option = _OPTION_SLOW if _OPTION_SLOW in str(exc) else _OPTION_EXEMPT
                problems[option] = f"long_running_command_guard {exc}"
        return problems

    def get_default_enabled(self) -> bool:
        """Ships off; see the module docstring. Keep consistent with the config template."""
        return False

    def get_rules(self) -> list[Rule]:
        """The five rules this handler speaks with (four deny, one advisory)."""
        return list(_RULES)

    def _mode_value(self) -> str:
        return self._mode if self._mode in _MODES else _MODE_DENY

    def _threshold(self) -> float:
        value = self._threshold_seconds
        return float(value) if _is_number(value) else DEFAULT_THRESHOLD_SECONDS

    def _policy(self) -> LongRunningPolicy:
        """The policy from options; a malformed one falls back to its default."""
        slow = self._extra_slow_patterns if _is_string_list(self._extra_slow_patterns) else []
        fast = self._extra_fast_programs if _is_string_list(self._extra_fast_programs) else []
        exempt = self._exempt_patterns if _is_string_list(self._exempt_patterns) else []
        try:
            return LongRunningPolicy.build(
                threshold_seconds=self._threshold(),
                extra_slow_patterns=slow,
                extra_fast_programs=fast,
                exempt_patterns=exempt,
            )
        except ValueError:
            return LongRunningPolicy.build(
                threshold_seconds=self._threshold(), extra_fast_programs=fast
            )

    def _findings(self, hook_input: dict[str, Any]) -> tuple[Finding, ...]:
        """Findings for a foreground Bash call; none for anything out of scope."""
        if self._mode_value() == _MODE_OFF:
            return ()
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return ()
        tool_input = hook_input.get(_TOOL_INPUT)
        if isinstance(tool_input, dict) and tool_input.get(_RUN_IN_BACKGROUND) is True:
            return ()
        command = get_bash_command(hook_input)
        if not command or command_declares_hatch(command, _ESCAPE_HATCH):
            return ()
        return classify(command, self._policy())

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a foreground Bash call that looks long or unbounded."""
        return bool(self._findings(hook_input))

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny (or advise on) a long foreground call; advise on an unbounded one."""
        findings = self._findings(hook_input)
        command = get_bash_command(hook_input) or ""
        denying = [f for f in findings if f.kind in _DENYING_ORDER]
        if not denying:
            return self._no_timeout_advice(findings)
        message = self._long_message(command, denying)
        if self._mode_value() == _MODE_ADVISE:
            return GatingResult(
                decision=Decision.ALLOW,
                context=[f"{_RULE_FOR_KIND[f.kind]}: {f.subject}" for f in denying],
                guidance=message,
            )
        return GatingResult.deny(message)

    def _no_timeout_advice(self, findings: tuple[Finding, ...]) -> GatingResult:
        """The advisory for a command of unknown length."""
        programs = ", ".join(dict.fromkeys(f.subject for f in findings))
        seconds = int(self._threshold())
        return GatingResult(
            decision=Decision.ALLOW,
            context=[f"{RuleID.LONG_RUNNING_NO_TIMEOUT}: no timeout on {programs}"],
            guidance=(
                f"[{RuleID.LONG_RUNNING_NO_TIMEOUT}] `{programs}` is not known to be fast "
                "and this call carries no timeout. A foreground command blocks the "
                f"session, so prefix `timeout {seconds}` to bound it, or run the call "
                "with `run_in_background: true` if it may take longer."
            ),
        )

    def _long_message(self, command: str, denying: list[Finding]) -> str:
        """The deny text: what was seen, the exact background form, Monitor, the hatch."""
        ordered = sorted(denying, key=lambda f: _DENYING_ORDER.index(f.kind))
        primary = _RULE_BY_ID[_RULE_FOR_KIND[ordered[0].kind]]
        also = [
            _RULE_FOR_KIND[f.kind] for f in ordered if _RULE_FOR_KIND[f.kind] != primary.rule_id
        ]
        seen = "; ".join(dict.fromkeys(f"{f.kind.value}: {f.subject}" for f in ordered))
        shown = command if len(command) <= _ECHO_LIMIT else command[:_ECHO_LIMIT] + " ..."
        form = json.dumps({"command": shown, _RUN_IN_BACKGROUND: True})
        also_line = f" Also: {', '.join(dict.fromkeys(also))}." if also else ""
        return (
            f"{RuleFormatter().headline(primary)}\n"
            f"This call looks long ({seen}).{also_line} {_WHY}\n\n"
            f"Re-issue the same Bash call with run_in_background set:\n  {form}\n\n"
            "The harness notifies you when it ends; keep working meanwhile. To wait "
            "for a condition (a CI run, a file, a process), use the Monitor tool or "
            "start the waiter in the background; never sleep-loop in the foreground.\n\n"
            "If this command must block (the owner is watching it live), declare it in "
            f'the command itself: {_ESCAPE_HATCH}="reason"; <command>'
        )

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## long_running_command_guard — never run a long command in the foreground\n\n"
            "A foreground Bash call in the main thread blocks the session: messages from "
            "the owner and from other agents wait until it ends. Any command that may "
            "take more than about 30 seconds runs with `run_in_background: true`, and any "
            "other foreground command carries a timeout.\n\n"
            "**DENIED in the main thread** (sub-agent calls are never judged): a "
            "`timeout N` wrapper with N above the threshold (the timeout is the tell), a "
            "wait loop (`until`/`while` with `sleep`), `sleep N` above the threshold, and "
            "known-slow programs (test suites, `llm_qa.py`, builds, installs, "
            "`gh run watch`). The deny gives the exact `run_in_background` form. "
            "To wait for a condition, use the Monitor tool or start the waiter in the "
            "background.\n\n"
            "**Advisory**: a command not known to be fast and with no timeout; prefix "
            "`timeout 30` or background it. Short commands (`git status`, `ls`, `cat`, "
            "`grep`, a quick `gh` read) are never touched, and neither is a call already "
            "backgrounded or a command ending in `&`.\n\n"
            "**Opt out** for one call that must block, naming why:\n\n"
            "```\n"
            f'{_ESCAPE_HATCH}="reason"; <command>\n'
            "```\n\n"
            "Configure via `handlers.pre_tool_use.long_running_command_guard.options`: "
            "`mode` (deny | advise | off), `threshold_seconds`, `extra_slow_patterns`, "
            "`extra_fast_programs`, `exempt_patterns`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """A long sleep is denied; a short one is allowed. Both need the main thread."""
        from claude_code_hooks_daemon.core import RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Long-running guard - a long foreground sleep is denied",
                command="sleep 45",
                dispatch_as_bash=True,
                description=(
                    "A foreground `sleep 45` in the main thread is denied; the reason "
                    "gives the run_in_background form and names the Monitor tool."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"run_in_background", r"Monitor"],
                safety_notes="Denied before it runs; the worst case is a 45 second sleep.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Long-running guard - a short foreground command is allowed",
                command="git status --short",
                dispatch_as_bash=True,
                description="A short, known-fast command is never blocked.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=True,
            ),
        ]
