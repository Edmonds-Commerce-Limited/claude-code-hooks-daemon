"""Bash safe-mode forcer: require a `set` safety prelude (Plan 00270).

On by default and blocking, by owner ruling: "lets make the bash strict mode on
by default - it should be harmless and provides a LOT of safety". The false-
positive shapes Plan 00268 worried about (`grep -q p f; echo done`, exit-code
observers, labelled diagnostic sweeps) are handled by mitigations rather than
ignored: the handler only speaks where sequencing exists (``min_statements``;
a pure `&&` chain is one statement and exempt), can be scoped to
mutator-bearing commands (``only_with_mutator``), can be downgraded to
``mode: warn`` or disabled per project, and carries a
``MUST_SKIP_SAFE_MODE_BECAUSE`` escape hatch.

``mode: inject`` (auto-prepending the prelude via PreToolUse ``updatedInput``)
is RESERVED, not implemented: Claude Code documents the field, but this
daemon's PreToolUse response schema does not model it and the serialiser never
emits it. The value is rejected at config load with a message naming that gap,
so the config surface is already stable for the follow-up that closes it.
"""

from __future__ import annotations

import re
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.handlers.pre_tool_use.verification_result_gate import (
    statements_contain_mutator,
)
from claude_code_hooks_daemon.utils.bash_flags import (
    FLAG_ERREXIT,
    FLAG_PIPEFAIL,
    SAFE_MODE_FLAGS,
    detect_safe_mode_flags,
    sequenced_statements,
    split_statements,
)
from claude_code_hooks_daemon.utils.option_coercion import coerce_int_option

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

#: Owner ruling A3 (Plan 00483): the handler speaks only where a MUTATOR (the
#: shared table in ``verification_result_gate``) is in the command, so a
#: read-only chain like `grep x a; grep y b` is never blocked.
_DEFAULT_ONLY_WITH_MUTATOR: Final = True

#: In-command escape hatch, following the daemon's MUST_..._BECAUSE
#: convention (git_stash, root_recursion_guard, comment_size).
_ESCAPE_HATCH: Final = "MUST_SKIP_SAFE_MODE_BECAUSE"

#: How each required flag is spelt in a remedy prelude.
_FLAG_SPELLING: Final[dict[str, str]] = {
    FLAG_ERREXIT: "set -e",
    FLAG_PIPEFAIL: "set -o pipefail",
    "nounset": "set -u",
}

#: N328: worded around the CURRENT harness behaviour, which could change.
_HARNESS_ERREXIT: Final = (
    "Under the current Claude Code Bash tool a top-level `set -e` does not stop "
    "the command: the tool runs it inside an `&&` list, where bash ignores "
    "errexit (this includes `{ }` groups and subshells). `pipefail` and `-u` "
    "still work; only a fresh `bash -c` process stops on errexit."
)

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
    "people.\n"
    f"- {_HARNESS_ERREXIT}"
)

#: N328: the forms that really stop on failure, led with wherever the handler
#: speaks. The first two need no errexit at all.
_STOPPING_FORMS: Final = (
    "Forms that actually stop on a failing step:\n"
    "  step_one && step_two                 # `&&` chaining\n"
    "  step_one || exit 1                   # explicit exit on each step\n"
    "  bash -c 'set -euo pipefail; step_one; step_two'   # a fresh process"
)


class BashSafeModeHandler(PreToolUseHandlerBase):
    """Require a bash safety prelude on multi-statement Bash invocations.

    Ships ``enabled: true``. Configuration options (via config YAML):
        mode: "block" (default) or "warn". "inject" is reserved and rejected
            at config load until the daemon serialises PreToolUse
            ``updatedInput``.
        require: list of flags to demand — any of "errexit", "pipefail",
            "nounset". Default ["errexit", "pipefail"].
        min_statements: sequenced-statement threshold (default 2).
        only_with_mutator: if true (default), only commands containing an
            entry from the shared mutator table are in scope; false covers
            every sequenced command.
        exempt_patterns: additive regexes matched against the whole command.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BASH_SAFE_MODE,
            priority=Priority.BASH_SAFE_MODE,
            terminal=False,
            # Plan 00466 n24 security review, M3: carries its own escape
            # hatch and per-project opt-outs -- an explicit, deliberate
            # opt-out from structural fail-closed, not an oversight.
            tags=[
                HandlerTag.VALIDATION,
                HandlerTag.QA_ENFORCEMENT,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ADVISORY,
            ],
        )
        # Config options: applied by blind setattr AFTER __init__. `_mode` is
        # a property so an unsupported value is rejected AT LOAD, inside the
        # registry's instantiation guard, with a message naming why.
        self._mode = _MODE_BLOCK
        self._require: Any = list(_DEFAULT_REQUIRE)
        self._min_statements: Any = _DEFAULT_MIN_STATEMENTS
        self._only_with_mutator: Any = _DEFAULT_ONLY_WITH_MUTATOR
        self._exempt_patterns = []
        # Single deny concept (Plan 00116): the block-mode path only. The
        # warn-mode advisory (context/guidance) is UNCHANGED — Decision C
        # rules apply to the deny path, and this handler's advisory content
        # is already dynamic per-missing-flag, matching the pre-migration
        # behaviour exactly.
        self._rule = Rule(
            rule_id=RuleID.BASH_SAFE_MODE_PRELUDE_MISSING,
            blocked="a sequenced Bash invocation with no `set` safety prelude",
            why="Errors in earlier statements can be silently ignored",
            fix=(
                "Gate with `&&` or `|| exit 1`, or run the body in "
                "`bash -c 'set -euo pipefail; …'` -- a top-level `set -e` does not "
                "stop the command under the current Claude Code Bash tool"
            ),
            verbose=_BLIND_SPOTS,
        )
        self._formatter = RuleFormatter()

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
                    f"bash_safe_mode exempt_patterns entry {entry!r} is not a valid regex: {exc}."
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
        """On by default, per the owner ruling cited in the module docstring.

        Must stay consistent with the ``enabled: true`` flag in the config
        template (enforced by ``test_default_enabled_template_consistency``).
        """
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True only when the command is missing a required prelude flag."""
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        command = get_bash_command(hook_input)
        if not command:
            return False
        return bool(self._missing_flags(command))

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's block-mode deny path."""
        return [self._rule]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Warn about (or deny) a sequenced command with no safety prelude.

        The block-mode DENY path is verbose-first/terse-after per
        (transcript_path, rule_id) via the shared DisclosureTracker
        (Plan 00116, Decision G/C: rules apply to the deny path only). The
        warn-mode advisory (context/guidance) is UNCHANGED.
        """
        command = get_bash_command(hook_input)
        missing = self._missing_flags(command) if command else ()
        if not missing:
            return GatingResult(decision=Decision.ALLOW)

        if self._mode == _MODE_BLOCK:
            transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
            tracker = get_data_layer().disclosure
            rule_id = RuleID.BASH_SAFE_MODE_PRELUDE_MISSING

            if transcript_path and tracker.was_disclosed(transcript_path, rule_id):
                reason = f"{self._formatter.terse(self._rule)}\n\n{self._missing_detail(missing)}"
            else:
                if transcript_path:
                    tracker.mark_disclosed(transcript_path, rule_id)
                reason = self._block_message(missing)
            return GatingResult(decision=Decision.DENY, reason=reason)
        return GatingResult(
            decision=Decision.ALLOW,
            context=[
                "Sequenced Bash invocation without a safety prelude — missing: "
                + ", ".join(missing)
                + "."
            ],
            guidance=self._message(missing),
        )

    @staticmethod
    def _missing_detail(missing: tuple[str, ...]) -> str:
        """One-line naming of the missing flags, pointing at forms that stop."""
        return (
            f"Missing: {', '.join(missing)}. Prefer `&&` / `|| exit 1` or "
            "`bash -c 'set -euo pipefail; …'`: a top-level `set -e` does not stop "
            "the command under the current Claude Code Bash tool."
        )

    def _missing_flags(self, command: str) -> tuple[str, ...]:
        """Required flags the command does not declare, or () when out of scope."""
        if _ESCAPE_HATCH in command:
            return ()
        if self._matches_exempt_pattern(command):
            return ()
        statements = split_statements(command)
        if len(sequenced_statements(command)) < self._threshold():
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
        A malformed entry must degrade
        to the default policy, never take the daemon down.
        """
        value = self._require
        if not isinstance(value, list):
            return _DEFAULT_REQUIRE
        validated = tuple(flag for flag in value if flag in SAFE_MODE_FLAGS)
        return validated or _DEFAULT_REQUIRE

    def _threshold(self) -> int:
        """Coerced ``min_statements`` option, via the shared
        :func:`coerce_int_option` (Plan 00311 Task 1.5)."""
        return coerce_int_option(self._min_statements, default=_DEFAULT_MIN_STATEMENTS)

    def _matches_exempt_pattern(self, command: str) -> bool:
        return any(pattern.search(command) for pattern in self._exempt_patterns)

    def _message(self, missing: tuple[str, ...]) -> str:
        return (
            "BASH SAFE MODE: this multi-statement invocation declares no "
            f"safety prelude for: {', '.join(missing)}.\n\n{self._remedy_body(missing)}"
        )

    @staticmethod
    def _remedy_body(missing: tuple[str, ...]) -> str:
        """The shared body of the warn and block messages (N328).

        Leads with the forms that stop on failure under Claude Code; the
        prelude is still accepted, and still worth having for ``pipefail``.
        """
        remedy = "; ".join(_FLAG_SPELLING[flag] for flag in missing)
        return (
            f"{_STOPPING_FORMS}\n\n"
            f"A declared prelude (e.g. `{remedy}`, or the combined "
            "`set -euo pipefail`) still satisfies this check and still gives you "
            "`pipefail` and `-u`, but it is not what stops a failing step.\n\n"
            f"{_BLIND_SPOTS}\n\n"
            "If this command legitimately must run every statement regardless "
            "of failures (a diagnostic sweep, an exit-code observer), declare "
            "it in the command itself:\n"
            f'  {_ESCAPE_HATCH}="explain why"; <command>\n\n'
            "Its sibling `verification_result_gate` does NOT accept a top-level "
            "`set -e` as consuming a verifier's result, for the same reason."
        )

    def _block_message(self, missing: tuple[str, ...]) -> str:
        """First-fire (verbose) block-mode message, leading with the rule ID.

        Reuses ``_message``'s rich, per-invocation-specific prose (the
        missing-flag list and remedy spelling are dynamic per call, which a
        static ``Rule.verbose`` cannot carry — Migration Pattern) with the
        rule_id prefix the Plan 00116 parity contract requires.
        """
        return (
            f"BLOCKED [{RuleID.BASH_SAFE_MODE_PRELUDE_MISSING}]: this "
            f"multi-statement invocation declares no safety prelude for: "
            f"{', '.join(missing)}.\n\n{self._remedy_body(missing)}"
        )

    def get_claude_md(self) -> str | None:
        return (
            "## bash_safe_mode — a safety prelude is required on sequenced Bash\n\n"
            "This handler ships on and blocks by default (a project can opt "
            "out with `enabled: false` or `mode: warn`). A Bash invocation with multiple "
            "sequenced statements (`;` or newline separated) must declare the "
            "required `set` flags — by default `set -e` (errexit) and "
            "`set -o pipefail` (`set -euo pipefail` satisfies both; `nounset` "
            "is only checked where configured). A command already carrying the "
            "prelude, a single statement, a pure `&&` chain, and (by default, "
            "`only_with_mutator: true`) a read-only chain with no mutator such "
            "as `git commit` or `git push` are never flagged.\n\n"
            "**Fix when blocked**: chain the statements with `&&`, add "
            "`|| exit 1` to each step, or run the body in "
            "`bash -c 'set -euo pipefail; …'`. A top-level prelude "
            "(`set -euo pipefail`) is still accepted, but it does not stop a "
            "failing step: " + _HARNESS_ERREXIT + "\n\n"
            f"{_BLIND_SPOTS}\n\n"
            "Because of those blind spots, do NOT drop explicit gating "
            "(`&&`, `|| exit 1`) just because a prelude is present — the "
            "prelude is not a replacement for consuming results.\n\n"
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
        """Acceptance tests exercising the configured mode with read-only commands."""
        from claude_code_hooks_daemon.core import RecommendedModel, TestType

        blocking = self._mode == _MODE_BLOCK
        return [
            AcceptanceTest(
                title="Bash safe mode - sequenced statements without a prelude",
                command="git status --short\ngit tag --list",
                dispatch_as_bash=True,
                description=(
                    "Two newline-sequenced read-only statements with no `set` "
                    "prelude. "
                    + (
                        "Block mode: the command is denied and the reason names "
                        "the missing flags."
                        if blocking
                        else "Advisory mode: the command runs and the context "
                        "names the missing flags."
                    )
                    + " The second statement is shaped like a mutator "
                    "(`git tag`) so this fixture still fires when "
                    "`only_with_mutator` is enabled -- `--list` keeps it "
                    "read-only."
                ),
                expected_decision=Decision.DENY if blocking else Decision.ALLOW,
                expected_message_patterns=[r"errexit", r"pipefail"],
                safety_notes="Both statements are read-only; --list tags nothing.",
                test_type=TestType.BLOCKING if blocking else TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Bash safe mode - a pure && chain is exempt",
                command="git status --short && git tag --list",
                dispatch_as_bash=True,
                description=(
                    "A pure `&&` chain is one statement, so explicit gating "
                    "needs no prelude and is silent in both modes."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Both commands are read-only; --list tags nothing.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Bash safe mode - a gated compound command is exempt",
                command='for b in main; do git rev-parse "$b" || exit 1; done',
                dispatch_as_bash=True,
                description=(
                    "The `;` in `for … ; do … ; done` (and in `{ …; }`, "
                    "`if …; then …; fi`) is syntax, not sequencing, so a fully "
                    "gated compound command needs no prelude in either mode."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only: rev-parse prints a commit id.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Bash safe mode - a declared prelude is silent",
                command="set -euo pipefail\ngit status --short\ngit tag --list",
                dispatch_as_bash=True,
                description=(
                    "The prelude satisfies the default require list. Same "
                    "mutator-shaped second statement as the sibling test above, "
                    "so this is a genuine test of the prelude being recognised "
                    "-- not an accidental silence from no mutator being present."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Both statements are read-only; --list tags nothing.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
