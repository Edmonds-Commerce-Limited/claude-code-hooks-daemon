"""Opt-in bash safe-mode forcer: require a `set` safety prelude (Plan 00270).

The opt-in counterpart Plan 00268 deferred. That plan REJECTED enforcing
``set -e`` as a blanket rule — forced errexit changes the semantics of every
command, and the false-positive shapes (`grep -q p f; echo done`, exit-code
observers, labelled diagnostic sweeps) would make a blanket handler mostly
wrong, and a handler that is mostly wrong gets disabled. Each objection maps
to a mitigation here rather than being ignored: the handler ships
``enabled: false``, warns first even when enabled, only speaks where
sequencing exists (``min_statements``), can be scoped to mutator-bearing
commands (``only_with_mutator``), and carries a ``MUST_SKIP_SAFE_MODE_BECAUSE``
escape hatch.

``mode: inject`` (auto-prepending the prelude via PreToolUse ``updatedInput``)
is RESERVED, not implemented: Claude Code documents the field, but this
daemon's PreToolUse response schema does not model it and the serialiser never
emits it. The value is rejected at config load with a message naming that gap,
so the config surface is already stable for the follow-up that closes it.
"""

from __future__ import annotations

import re
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, ToolName
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.handlers.pre_tool_use.verification_result_gate import (
    statements_contain_mutator,
)
from claude_code_hooks_daemon.utils.bash_flags import (
    FLAG_ERREXIT,
    FLAG_PIPEFAIL,
    SAFE_MODE_FLAGS,
    detect_safe_mode_flags,
    split_statements,
)

_MODE_WARN: Final = "warn"
_MODE_BLOCK: Final = "block"
_MODE_INJECT: Final = "inject"

#: Default `require` list. `nounset` is deliberately absent: `set -u` breaks
#: the ubiquitous `$OPTIONAL_VAR` probing idiom and would dominate the
#: false-positive budget for marginal benefit (BRAINSTORM §3).
_DEFAULT_REQUIRE: Final[tuple[str, ...]] = (FLAG_ERREXIT, FLAG_PIPEFAIL)

#: Single-statement commands gain nothing from a prelude; the default of 2
#: means the handler only speaks where sequencing exists. A pure `&&` chain
#: splits to ONE statement, so correct explicit gating is exempt for free.
_DEFAULT_MIN_STATEMENTS: Final = 2

#: In-command escape hatch, following the daemon's MUST_..._BECAUSE
#: convention (git_stash, root_recursion_guard, comment_size).
_ESCAPE_HATCH: Final = "MUST_SKIP_SAFE_MODE_BECAUSE"

#: How each required flag is spelt in a remedy prelude.
_FLAG_SPELLING: Final[dict[str, str]] = {
    FLAG_ERREXIT: "set -e",
    FLAG_PIPEFAIL: "set -o pipefail",
    "nounset": "set -u",
}

#: The blind-spot education block. Shown verbatim wherever the handler
#: speaks, so an enabling project never mistakes the prelude for a guarantee.
#: Deliberately does NOT claim `rc=$?` capture survives `set -e` — it does
#: not; the honest remedy for exit-code observers is the escape hatch.
_BLIND_SPOTS: Final = (
    "`set -e` is NOT a safety guarantee — know its blind spots:\n"
    "- It is DISABLED inside `if`/`elif`/`while`/`until` conditions and under `!`.\n"
    "- A failure in any non-final operand of `&&`/`||` does not exit.\n"
    "- `local x=$(fail)` and `export x=$(fail)` mask the substitution's exit "
    "status; the assignment succeeds.\n"
    "- `cmd | head` under `pipefail` can fail on SIGPIPE alone — `pipefail` "
    "turns some benign shapes into failures, which is the point but surprises "
    "people."
)


class BashSafeModeHandler(PreToolUseHandlerBase):
    """Require a bash safety prelude on multi-statement Bash invocations.

    Ships ``enabled: false``. Configuration options (via config YAML):
        mode: "warn" (default) or "block". "inject" is reserved and rejected
            at config load until the daemon serialises PreToolUse
            ``updatedInput``.
        require: list of flags to demand — any of "errexit", "pipefail",
            "nounset". Default ["errexit", "pipefail"].
        min_statements: sequenced-statement threshold (default 2).
        only_with_mutator: if true, only commands containing an entry from
            the shared mutator table are in scope (default false).
        exempt_patterns: additive regexes matched against the whole command.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BASH_SAFE_MODE,
            priority=Priority.BASH_SAFE_MODE,
            terminal=False,
            tags=[HandlerTag.VALIDATION, HandlerTag.QA_ENFORCEMENT, HandlerTag.NON_TERMINAL],
        )
        # Config options: applied by blind setattr AFTER __init__. `_mode` is
        # a property so an unsupported value is rejected AT LOAD, inside the
        # registry's instantiation guard, with a message naming why.
        self._mode = _MODE_WARN
        self._require: Any = list(_DEFAULT_REQUIRE)
        self._min_statements: Any = _DEFAULT_MIN_STATEMENTS
        self._only_with_mutator: Any = False
        self._exempt_patterns = []

    @property
    def _exempt_patterns(self) -> list[re.Pattern[str]]:
        return self.__exempt_patterns

    @_exempt_patterns.setter
    def _exempt_patterns(self, value: object) -> None:
        """Compile the configured regexes, rejecting bad config AT LOAD.

        A pattern that cannot compile is a config typo the author wrote
        expecting an exemption; silently ignoring it would leave the
        exemption inert with no signal. Raising here surfaces the message in
        the registry's instantiation guard, exactly like ``mode: inject``.
        """
        if not isinstance(value, list):
            raise ValueError(
                f"bash_safe_mode exempt_patterns must be a list of regex strings, got {value!r}."
            )
        compiled: list[re.Pattern[str]] = []
        for entry in value:
            if not isinstance(entry, str):
                raise ValueError(
                    f"bash_safe_mode exempt_patterns entries must be strings, got {entry!r}."
                )
            try:
                compiled.append(re.compile(entry))
            except re.error as exc:
                raise ValueError(
                    f"bash_safe_mode exempt_patterns entry {entry!r} is not a "
                    f"valid regex: {exc}."
                ) from exc
        self.__exempt_patterns = compiled

    @property
    def _mode(self) -> str:
        return self.__mode

    @_mode.setter
    def _mode(self, value: object) -> None:
        if value == _MODE_INJECT:
            raise ValueError(
                "bash_safe_mode mode 'inject' is reserved but NOT implemented: "
                "this daemon's PreToolUse response schema does not model "
                "hookSpecificOutput.updatedInput and the serialiser never emits "
                "it, so the daemon cannot rewrite tool input yet. Use mode "
                "'warn' or 'block' until the serialisation gap is closed."
            )
        if value not in (_MODE_WARN, _MODE_BLOCK):
            raise ValueError(f"bash_safe_mode mode must be 'warn' or 'block', got {value!r}.")
        self.__mode = str(value)

    def get_default_enabled(self) -> bool:
        """Opt-in handler — off by default, per the feature's own framing.

        Plan 00268's cry-wolf analysis stands: forced errexit changes the
        semantics of every command, so enabling this is a per-project policy
        act, never a default. Must stay consistent with the
        ``enabled: false`` flag in the config template (enforced by
        ``test_default_enabled_template_consistency``).
        """
        return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True only when the command is missing a required prelude flag."""
        if hook_input.get("tool_name") != ToolName.BASH:
            return False
        command = get_bash_command(hook_input)
        if not command:
            return False
        return bool(self._missing_flags(command))

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Warn about (or deny) a sequenced command with no safety prelude."""
        command = get_bash_command(hook_input)
        missing = self._missing_flags(command) if command else ()
        if not missing:
            return GatingResult(decision=Decision.ALLOW)

        if self._mode == _MODE_BLOCK:
            return GatingResult(decision=Decision.DENY, reason=self._message(missing))
        return GatingResult(
            decision=Decision.ALLOW,
            context=[
                "Sequenced Bash invocation without a safety prelude — missing: "
                + ", ".join(missing)
                + "."
            ],
            guidance=self._message(missing),
        )

    def _missing_flags(self, command: str) -> tuple[str, ...]:
        """Required flags the command does not declare, or () when in scope-free."""
        if _ESCAPE_HATCH in command:
            return ()
        if self._matches_exempt_pattern(command):
            return ()
        statements = split_statements(command)
        if len(statements) < self._threshold():
            return ()
        declared = detect_safe_mode_flags(statements)
        missing = tuple(flag for flag in self._required_flags() if flag not in declared)
        if not missing:
            return ()
        if self._only_with_mutator is True and not statements_contain_mutator(statements):
            return ()
        return missing

    def _required_flags(self) -> tuple[str, ...]:
        """The validated `require` list, falling back to the shipped default.

        Options arrive by blind setattr from YAML, so the type is not trusted.
        This handler is opt-in and warn-first; a malformed entry must degrade
        to the default policy, never take the daemon down.
        """
        value = self._require
        if not isinstance(value, list):
            return _DEFAULT_REQUIRE
        validated = tuple(flag for flag in value if flag in SAFE_MODE_FLAGS)
        return validated or _DEFAULT_REQUIRE

    def _threshold(self) -> int:
        value = self._min_statements
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        return _DEFAULT_MIN_STATEMENTS

    def _matches_exempt_pattern(self, command: str) -> bool:
        return any(pattern.search(command) for pattern in self._exempt_patterns)

    def _message(self, missing: tuple[str, ...]) -> str:
        remedy = "; ".join(_FLAG_SPELLING[flag] for flag in missing)
        return (
            "BASH SAFE MODE: this multi-statement invocation declares no "
            f"safety prelude for: {', '.join(missing)}.\n\n"
            f"Add the prelude at the top of the invocation (e.g. `{remedy}`, "
            "or the combined `set -euo pipefail`), or gate the statements "
            "explicitly with `&&` / `|| { ...; exit 1; }`.\n\n"
            f"{_BLIND_SPOTS}\n\n"
            "If this command legitimately must run every statement regardless "
            "of failures (a diagnostic sweep, an exit-code observer), declare "
            "it in the command itself:\n"
            f'  {_ESCAPE_HATCH}="explain why"; <command>\n\n'
            "This handler is opt-in project policy (it ships disabled); its "
            "sibling `verification_result_gate` already stands down when a "
            "prelude is present, so the two never double-fire."
        )

    def get_claude_md(self) -> str | None:
        return (
            "## bash_safe_mode — a safety prelude is required on sequenced Bash\n\n"
            "This handler is **opt-in project policy** (ships disabled; this "
            "project has chosen to enable it). A Bash invocation with multiple "
            "sequenced statements (`;` or newline separated) must declare the "
            "required `set` flags — by default `set -e` (errexit) and "
            "`set -o pipefail` (`set -euo pipefail` satisfies both; `nounset` "
            "is only checked where configured). A command already carrying the "
            "prelude, a single statement, and a pure `&&` chain are never "
            "flagged.\n\n"
            f"{_BLIND_SPOTS}\n\n"
            "Because of those blind spots, do NOT drop explicit gating "
            "(`&&`, `|| exit 1`) just because the prelude is present — the "
            "prelude is a floor, not a replacement for consuming results.\n\n"
            "**Escape hatch** for commands that must run every statement "
            "(diagnostic sweeps, exit-code observers):\n\n"
            "```\n"
            f'{_ESCAPE_HATCH}="explain why"; <command>\n'
            "```\n\n"
            "Configure via `handlers.pre_tool_use.bash_safe_mode.options`: "
            "`mode` (warn | block; `inject` is reserved and rejected at load), "
            "`require`, `min_statements`, `only_with_mutator`, "
            "`exempt_patterns`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests exercising the warn path with read-only commands."""
        from claude_code_hooks_daemon.core import RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Bash safe mode - sequenced statements without a prelude",
                command="git status --short\ngit log --oneline -n 1",
                description=(
                    "Two newline-sequenced read-only statements with no `set` "
                    "prelude. Advisory by default: the command runs and the "
                    "context names the missing flags."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"errexit", r"pipefail"],
                safety_notes="Both statements are read-only git queries.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Bash safe mode - a declared prelude is silent",
                command="set -euo pipefail\ngit status --short\ngit log --oneline -n 1",
                description="The prelude satisfies the default require list.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Both statements are read-only git queries.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
