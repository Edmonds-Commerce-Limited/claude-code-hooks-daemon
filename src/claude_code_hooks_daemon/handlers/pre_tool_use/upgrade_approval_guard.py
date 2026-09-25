"""UpgradeApprovalGuardHandler — an agent cannot grant its own upgrade approval.

Plan 00376, review finding MAJOR 4. The pre-deploy upgrade gate lets the
project OWNER approve a breaking upgrade via a one-shot marker file, written
by ``hooks-daemon approve-upgrade <version> --from <previous>`` — a command
that requires an interactive TTY and a typed confirmation phrase, so an agent
cannot answer the prompt itself. That is the control; this handler closes the
three ways an agent could still reach the same outcome without the human ever
answering it:

1. **Running the approval command itself** — ``approve-upgrade`` as a
   subcommand of the daemon CLI (`bin/hooks-daemon`, a path-qualified copy,
   or the module-invocation spelling — `python -m` plus the dotted
   `claude_code_hooks_daemon.daemon.cli` module path), or the venv-free
   standalone gate's own ``approve`` subcommand
   (``upgrade_gate_standalone.py approve``). Both write the exact marker the
   TTY prompt exists to gate.
2. **Writing the marker directly** — ``touch``/redirect/``tee``/``cp``/``mv``/
   ``mkdir`` reaching a path under an ``upgrade-approvals/`` directory by any
   Bash route, or authoring it with ``Write``/``Edit``/``NotebookEdit``.
3. **Impersonating Layer 1 or steering the upgrade** — assigning, exporting
   or ``env``-setting ``HOOKS_DAEMON_UPGRADE_HANDOFF``, the path of the
   one-shot handoff file ``scripts/upgrade.sh`` writes for
   ``scripts/upgrade_version.sh`` (Layer 2 believes that file only when its
   parent wrote it; a command that sets the variable and runs Layer 2 IS that
   parent); or, on a command that runs an upgrade entry point, setting a
   variable that picks its interpreter, venv, forwarded flags or code
   (``_UPGRADE_STEERING_VARS``).
4. **Forging the installer's own version stamp** — writing a venv's
   ``.daemon-version`` file (under ``untracked/venv*/``) by any of the same
   routes as (2), which would make the gate believe the target is already
   installed.

Two distinct Rules (Decision B): route 3 is a different failure mode from
1/2/4 — steering the gate's control flow, rather than forging what it
protects — so it gets its own rule_id and its own remedy text.

**Reading is never denied.** ``ls``/``cat``/``stat``/``grep``/``find ...
-print``/``test -f`` over an approvals path or a version stamp, and merely
reading the env var (``echo "$VAR"``, ``grep VAR file``), are all
unaffected — matching only requires the token pattern this handler denies
(an assignment carries ``=``; a read does not).

**Inert-text exemption.** Mentioning ``approve-upgrade`` inside a
``git commit`` message, non-executing ``echo``/``printf`` prose, a ``grep``
search, or a quoted-delimiter heredoc body written to a file must not be
denied — the same house pattern every other Bash-scanning safety handler
uses (`claude_code_hooks_daemon.utils.shell_segmentation.strip_inert_spans`
for git/gh message values and quoted heredoc bodies fed to a data sink; a
per-segment ``grep``/``echo``/``printf`` head check here for the rest, the
same shape `sed_blocker` established). An ``echo``/``printf`` argument that
can genuinely EXECUTE something (a live ``$(...)``/backtick substitution) is
NOT exempt — it is scanned like any other command.
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass
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
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_path
from claude_code_hooks_daemon.handlers.utils.bash_file_writes import bash_file_writes
from claude_code_hooks_daemon.install.install_stamp import STAMP_FILENAME
from claude_code_hooks_daemon.install.upgrade_gate import APPROVAL_SUBDIR
from claude_code_hooks_daemon.utils.path_predicates import TextOrReason, read_text_or_reason
from claude_code_hooks_daemon.utils.shell_segmentation import (
    command_word,
    split_unquoted,
    strip_inert_spans,
)

#: Decode policy for the one read this handler makes (a patch file
#: `bash_file_writes` follows) — only ASCII path text matters here, so a
#: stray byte cannot raise.
_DECODE_REPLACE: Final[str] = "replace"

# --- item 1: running the approval command itself ---------------------------

#: `bin/hooks-daemon`, a path-qualified copy, or a bare `hooks-daemon`. The
#: negative lookahead stops `hooks-daemon.yaml`/`hooks-daemon-anything` from
#: reading as the CLI binary.
_HOOKS_DAEMON_BIN_RE: Final[str] = r"(?:\S*/)?hooks-daemon(?![\w.-])"
#: `python3 -m` plus the dotted `claude_code_hooks_daemon.daemon.cli` module
#: path — the module-invocation spelling of the same CLI.
_HOOKS_DAEMON_MODULE_RE: Final[str] = (
    r"python3?\s+-m\s+claude_code_hooks_daemon\.daemon\.cli(?![\w.])"
)
#: Either invocation, followed — permissively, any run of option tokens is
#: allowed between (`--project-root <path>`, `--pid-file <path>`, ...) — by
#: the `approve-upgrade` subcommand. Runs within ONE already-segmented stage
#: (see `_SEGMENT_SEPARATORS`), so the option run cannot cross into another
#: command.
_APPROVE_UPGRADE_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?:{_HOOKS_DAEMON_BIN_RE}|{_HOOKS_DAEMON_MODULE_RE})(?:\s+\S+)*?\s+approve-upgrade\b"
)
#: The venv-free standalone gate's own `approve` subcommand.
_STANDALONE_APPROVE_RE: Final[re.Pattern[str]] = re.compile(
    r"\bupgrade_gate_standalone\.py\b(?:\s+\S+)*?\s+approve\b"
)

# --- item 3: impersonating Layer 1 via an env var ----------------------------

#: The variable Layer 1 (`scripts/upgrade.sh`) hands Layer 2 its one-shot
#: handoff file in (Plan 00376). Kept here as the single source of truth for
#: THIS handler's pattern; the scripts are shell, not importable.
ENV_VAR_UPGRADE_HANDOFF: Final[str] = "HOOKS_DAEMON_UPGRADE_HANDOFF"
_GUARDED_ENV_VARS: Final[tuple[str, ...]] = (ENV_VAR_UPGRADE_HANDOFF,)
_ENV_VAR_GROUP: Final[str] = "|".join(_GUARDED_ENV_VARS)
#: An ASSIGNMENT (`VAR=...`, `export VAR`, `declare -x VAR`) — never a read
#: (`$VAR`, `${VAR}`), which carries no `=` immediately after the bare name.
_ENV_VAR_ASSIGN_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b(?:{_ENV_VAR_GROUP})=" rf"|\b(?:export|declare\s+-x|typeset\s+-x)\s+(?:{_ENV_VAR_GROUP})\b"
)

#: Variables the upgrade path reads to choose the interpreter, the venv whose
#: stamp is the installed version, the forwarded flags and pass state, the
#: files git lists for detection, or the code it runs. Denied only on a
#: command that also runs an upgrade entry point: each has ordinary uses
#: elsewhere.
_UPGRADE_STEERING_VARS: Final[tuple[str, ...]] = (
    "HOOKS_DAEMON_PYTHON",
    "HOOKS_DAEMON_VENV_PATH",
    "PATH",
    "HOSTNAME",
    "HOOKS_DAEMON_CLONE_URL",
    "HOOKS_DAEMON_UPGRADE_BASE_URL",
    "HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION",
    "HOOKS_DAEMON_UPGRADE_SECOND_PASS",
    "UPGRADE_FLAGS",
    "GIT_*",
)
_STEERING_GROUP: Final[str] = "|".join(
    re.escape(name).replace(r"\*", r"[A-Z0-9_]+") for name in _UPGRADE_STEERING_VARS
)
_STEERING_ASSIGN_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b(?:{_STEERING_GROUP})="
    rf"|\b(?:export|declare\s+-x|typeset\s+-x)\s+(?:{_STEERING_GROUP})\b"
)
#: The upgrade's entry points: Layer 1 (and the skill shim of the same name),
#: Layer 2, and the gate itself.
_UPGRADE_ENTRY_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[\s/])(?:upgrade\.sh|upgrade_version\.sh|upgrade_gate_standalone\.py)\b"
)

# --- segmentation and the inert-text exemption ------------------------------

#: Splits a Bash command into top-level stages: `;`, `&&`, `||`, a pipe stage,
#: a newline. Longest-first so `&&`/`||` are not read as two `&`/`|`.
_SEGMENT_SEPARATORS: Final[tuple[str, ...]] = ("&&", "||", ";", "|", "\n")
#: Spans meaning bash will EXECUTE something inside a quoted argument.
_SUBSTITUTION_MARKERS: Final[tuple[str, ...]] = ("$(", "`")
#: A `VAR=value` assignment prefix, skipped when resolving a segment's head.
_ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
#: `grep`/`rg` never execute what they search for, so any occurrence of a
#: guarded pattern in one of their segments is a SEARCH, not a run.
_ALWAYS_INERT_HEADS: Final[frozenset[str]] = frozenset({"grep", "rg"})
#: `echo`/`printf` are exempt UNLESS their argument can substitute (item 1's
#: "echo with live substitution is still denied" case).
_CONDITIONALLY_INERT_HEADS: Final[frozenset[str]] = frozenset({"echo", "printf"})

# --- item 2 / item 4: writes bash_file_writes cannot show -------------------

#: `bash_file_writes` follows redirects, `tee`, `cp`/`mv`/`install`/`dd`,
#: `ln`/`rsync`, in-place editors and interpreter one-liners, but not a bare
#: `touch`/`mkdir` — neither authors content nor relocates an existing file,
#: so neither shape `bash_write_destinations` recognises applies. Detected
#: here instead: every non-flag operand of a `touch`/`mkdir` head.
_EXTRA_WRITE_VERBS: Final[frozenset[str]] = frozenset({"touch", "mkdir"})

logger = logging.getLogger(__name__)


def _shell_words(segment: str) -> list[str]:
    """Shell words of one segment; whitespace words when shlex cannot parse it.

    A stray unbalanced quote in prose text must cost only this segment, not
    the whole scan — so a parse failure is logged and degrades to a plain
    split rather than raising (matches `handlers/utils/bash_file_writes.py`'s
    `_words`).
    """
    try:
        return shlex.split(segment)
    except ValueError as exc:
        logger.debug("upgrade_approval_guard: shlex could not parse %r (%s)", segment, exc)
        return segment.split()


def _segment_head(segment: str) -> str:
    """The command a segment runs, past any `VAR=value` assignment prefix."""
    for token in _shell_words(segment):
        if _ASSIGNMENT_RE.match(token):
            continue
        return command_word(token)
    return ""


def _is_inert_mention_segment(segment: str) -> bool:
    """Whether ``segment`` only MENTIONS guarded text rather than running it."""
    head = _segment_head(segment)
    if head in _ALWAYS_INERT_HEADS:
        return True
    if head in _CONDITIONALLY_INERT_HEADS:
        return not any(marker in segment for marker in _SUBSTITUTION_MARKERS)
    return False


def _executable_segments(command: str) -> list[str]:
    """Top-level stages of ``command``, with inert text stripped first."""
    executable = strip_inert_spans(command)
    return split_unquoted(executable, _SEGMENT_SEPARATORS)


def _bash_runs_guarded_action(command: str) -> bool:
    """Whether ``command`` runs `approve-upgrade` or the standalone `approve`."""
    for segment in _executable_segments(command):
        if _is_inert_mention_segment(segment):
            continue
        if _APPROVE_UPGRADE_RE.search(segment) or _STANDALONE_APPROVE_RE.search(segment):
            return True
    return False


def _bash_sets_bypass_env_var(command: str) -> bool:
    """Whether ``command`` sets the handoff variable, or steers an upgrade it runs."""
    segments = [
        segment
        for segment in _executable_segments(command)
        if not _is_inert_mention_segment(segment)
    ]
    if any(_ENV_VAR_ASSIGN_RE.search(segment) for segment in segments):
        return True
    runs_upgrade = any(_UPGRADE_ENTRY_RE.search(segment) for segment in segments)
    return runs_upgrade and any(_STEERING_ASSIGN_RE.search(segment) for segment in segments)


def _extra_write_targets(command: str) -> list[str]:
    """Operand paths of a bare `touch`/`mkdir` invocation, per segment."""
    targets: list[str] = []
    for segment in _executable_segments(command):
        if _is_inert_mention_segment(segment):
            continue
        tokens = _shell_words(segment)
        head_index: int | None = None
        for index, token in enumerate(tokens):
            if _ASSIGNMENT_RE.match(token):
                continue
            head_index = index
            break
        if head_index is None:
            continue
        if command_word(tokens[head_index]) not in _EXTRA_WRITE_VERBS:
            continue
        targets.extend(token for token in tokens[head_index + 1 :] if not token.startswith("-"))
    return targets


def _has_upgrade_approvals_segment(path: str) -> bool:
    """Whether ``path`` names something under an `upgrade-approvals/` directory."""
    return APPROVAL_SUBDIR in Path(path).parts


def _is_venv_version_stamp(path: str) -> bool:
    """Whether ``path`` is a `.daemon-version` stamp under `untracked/venv*/`."""
    parts = Path(path).parts
    if not parts or parts[-1] != STAMP_FILENAME:
        return False
    try:
        index = parts.index("untracked")
    except ValueError:
        return False
    return index + 1 < len(parts) and parts[index + 1].startswith("venv")


def _guarded_write_target(path: str) -> str | None:
    """Which guarded surface ``path`` hits — for the deny message — or None."""
    if _has_upgrade_approvals_segment(path):
        return "the one-shot upgrade-approval marker directory (`upgrade-approvals/`)"
    if _is_venv_version_stamp(path):
        return "a venv's installer version stamp (`.daemon-version`)"
    return None


def _read_text(path: Path) -> TextOrReason:
    """The one read `bash_file_writes` may make (a patch file it follows)."""
    return read_text_or_reason(path, errors=_DECODE_REPLACE)


@dataclass(frozen=True)
class _Violation:
    """What this call would do, and the Rule it violates."""

    rule_id: str
    note: str


class UpgradeApprovalGuardHandler(PreToolUseHandlerBase):
    """Deny an agent action that grants or bypasses the owner's upgrade approval."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.UPGRADE_APPROVAL_GUARD,
            priority=Priority.UPGRADE_APPROVAL_GUARD,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        self._rule_agent_action = Rule(
            rule_id=RuleID.UPGRADE_APPROVAL_AGENT_ACTION,
            blocked=(
                "an agent action that grants or forges the owner's upgrade approval "
                "(running `approve-upgrade`, writing/touching a marker under "
                "`upgrade-approvals/`, or forging a venv `.daemon-version` stamp)"
            ),
            why=(
                "Approving a breaking upgrade is the project OWNER's step, not the "
                "agent's — the gate exists so a human reads what changed before it happens"
            ),
            fix=(
                "Report the gate's reasons to the user and stop; the owner runs "
                "`hooks-daemon approve-upgrade <version> --from <previous>` in their own "
                "terminal (it requires a TTY and a typed confirmation phrase)"
            ),
            verbose=(
                "The upgrade gate's escalation path exists for the OWNER to read what a "
                "breaking upgrade changes and decide, in their own terminal — "
                "`hooks-daemon approve-upgrade <version> --from <previous>` requires an "
                "interactive TTY and a typed confirmation phrase precisely so an agent "
                "cannot answer the prompt on the owner's behalf.\n\n"
                "An agent must never reach the same outcome by another route: running "
                "`approve-upgrade` (or the standalone gate's `approve` subcommand) "
                "itself, writing or touching the `<version>.approved` marker under "
                "`upgrade-approvals/` by any Bash route or with Write/Edit/NotebookEdit, "
                "or forging a venv's `.daemon-version` stamp (which would make the gate "
                "believe the target is already installed).\n\n"
                "What to do instead: report the gate's reasons to the user and STOP. "
                "The owner decides, in their own terminal."
            ),
        )
        self._rule_env_bypass = Rule(
            rule_id=RuleID.UPGRADE_APPROVAL_ENV_BYPASS,
            blocked=(
                f"a Bash command that sets `{ENV_VAR_UPGRADE_HANDOFF}`, or runs an upgrade "
                "with a variable that picks its interpreter, venv, flags or code"
            ),
            why="The upgrade and its pre-deploy gate run as shipped, not as an agent steers them",
            fix="Run the upgrade with no such variable set; if it cannot run, tell the user",
            verbose=(
                f"`{ENV_VAR_UPGRADE_HANDOFF}` names the one-shot handoff file "
                "`scripts/upgrade.sh` (Layer 1) writes for `scripts/upgrade_version.sh` "
                "(Layer 2). Layer 2 believes it only when its parent process wrote it, and "
                "a command that sets the variable and runs Layer 2 is that parent, so "
                "setting it anywhere impersonates Layer 1.\n\n"
                "On a command that runs an upgrade entry point (`upgrade.sh`, "
                "`upgrade_version.sh`, `upgrade_gate_standalone.py`), these are denied "
                f"too: {', '.join(f'`{name}`' for name in _UPGRADE_STEERING_VARS)}. They "
                "choose the interpreter, the venv whose stamp is the installed version, the "
                "forwarded flags or the code that runs, which is how a crafted interpreter "
                "or a forged venv could answer for the pre-deploy gate. Layer 2 takes "
                "neither the gate's interpreter nor the installed version from them, and "
                "this rule keeps an agent from steering the rest.\n\n"
                "Run the upgrade with none of them set. If it genuinely needs one (an "
                "interpreter that is not on PATH, say), tell the user, who can run it "
                "themselves."
            ),
        )
        self._formatter = RuleFormatter()

    def get_rules(self) -> list[Rule]:
        """Return the two Rules backing this handler's deny paths (Decision B)."""
        return [self._rule_agent_action, self._rule_env_bypass]

    # ------------------------------------------------------------------
    # Single dispatch point (matches()/handle() must never disagree)
    # ------------------------------------------------------------------

    def _violation(self, hook_input: dict[str, Any]) -> _Violation | None:
        """What this call would do, or None when it is unaffected."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name == ToolName.BASH:
            return self._bash_violation(hook_input)
        if tool_name in (ToolName.WRITE, ToolName.EDIT):
            return self._file_path_violation(get_file_path(hook_input))
        if tool_name == ToolName.NOTEBOOK_EDIT:
            tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
            path = tool_input.get("notebook_path") if isinstance(tool_input, dict) else None
            return self._file_path_violation(path if isinstance(path, str) else None)
        return None

    def _file_path_violation(self, path: str | None) -> _Violation | None:
        if not path:
            return None
        surface = _guarded_write_target(path)
        if surface is None:
            return None
        return _Violation(
            rule_id=RuleID.UPGRADE_APPROVAL_AGENT_ACTION,
            note=f"Target: `{path}` — {surface}.",
        )

    def _bash_violation(self, hook_input: dict[str, Any]) -> _Violation | None:
        command = get_bash_command(hook_input)
        if not command:
            return None

        if _bash_sets_bypass_env_var(command):
            return _Violation(
                rule_id=RuleID.UPGRADE_APPROVAL_ENV_BYPASS,
                note=f"COMMAND: {command}",
            )

        if _bash_runs_guarded_action(command):
            return _Violation(
                rule_id=RuleID.UPGRADE_APPROVAL_AGENT_ACTION,
                note=f"COMMAND: {command}",
            )

        raw_cwd = hook_input.get(HookInputField.CWD)
        cwd = raw_cwd if isinstance(raw_cwd, str) and raw_cwd else None
        writes = bash_file_writes(command, cwd, _read_text)
        destinations = list(writes.destinations) + _extra_write_targets(command)
        for destination in destinations:
            surface = _guarded_write_target(destination)
            if surface is not None:
                return _Violation(
                    rule_id=RuleID.UPGRADE_APPROVAL_AGENT_ACTION,
                    note=f"Target: `{destination}` — {surface}.",
                )
        return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match any of the guarded agent actions."""
        return self._violation(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny, naming the owner's own remedy and the specific target/command."""
        violation = self._violation(hook_input)
        # Precondition: matches() found a violation on this same input.
        assert violation is not None, "Handler called without matches check"

        rule = (
            self._rule_env_bypass
            if violation.rule_id == RuleID.UPGRADE_APPROVAL_ENV_BYPASS
            else self._rule_agent_action
        )
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, rule.rule_id):
            message = self._formatter.terse(rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule.rule_id)
            message = self._formatter.verbose(rule)

        message += f"\n\n{violation.note}"
        return GatingResult(decision=Decision.DENY, reason=message)

    def get_claude_md(self) -> str | None:
        return (
            "## upgrade_approval_guard — an agent cannot grant its own upgrade approval\n\n"
            "The pre-deploy upgrade gate's escalation path is the project OWNER's step: "
            "`hooks-daemon approve-upgrade <version> --from <previous>` requires an "
            "interactive TTY and a typed confirmation phrase, run in the owner's own "
            "terminal. An agent cannot answer that prompt, and this handler denies "
            "every other route to the same outcome:\n\n"
            "1. Running `approve-upgrade` itself (any spelling: `bin/hooks-daemon`, a "
            "path-qualified copy, or `python -m` plus the dotted "
            "`claude_code_hooks_daemon.daemon.cli` module path), or the standalone "
            "gate's own `upgrade_gate_standalone.py approve` subcommand.\n"
            "2. Writing the `<version>.approved` marker under `upgrade-approvals/` by "
            "any Bash route (`touch`, a redirect, `tee`, `cp`/`mv`, `mkdir` of the "
            "directory) or with Write/Edit/NotebookEdit.\n"
            "3. Assigning, exporting or `env`-setting `HOOKS_DAEMON_UPGRADE_HANDOFF`, "
            "which impersonates the upgrade's Layer 1 (`scripts/upgrade.sh`); or, on a "
            "command that runs `upgrade.sh`, `upgrade_version.sh` or "
            "`upgrade_gate_standalone.py`, setting a variable that picks its "
            "interpreter, venv, flags, pass state, git view or code: "
            f"{', '.join(f'`{name}`' for name in _UPGRADE_STEERING_VARS)}. Run the "
            "upgrade with none of them set.\n"
            "4. Forging a venv's `.daemon-version` stamp under `untracked/venv*/`, by "
            "any of the routes in (2).\n\n"
            "**If you hit this**: report the gate's reasons to the user and STOP. Do "
            "not retry with a different spelling — ask the owner to run the approval "
            "command themselves.\n\n"
            "**Never denied**: reading — `ls`/`cat`/`stat`/`grep`/`find ... -print`/"
            "`test -f` over an approvals path or a version stamp, and merely reading "
            'the env var (`echo "$VAR"`, `grep VAR file`). Mentioning '
            "`approve-upgrade` inside a `git commit` message, non-executing "
            "`echo`/`printf` prose, a `grep` search, or a quoted-delimiter heredoc body "
            "written to a file is not denied either — an `echo`/`printf` argument that "
            "can genuinely EXECUTE something (a live `$(...)`/backtick substitution) is "
            "the one exception, and is scanned like any other command."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the upgrade approval guard."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Block an agent running approve-upgrade itself",
                command="bin/hooks-daemon approve-upgrade 99.0.0 --from 1.0.0",
                dispatch_as_bash=True,
                description=(
                    "An agent invoking the owner-only `approve-upgrade` subcommand is "
                    "denied before it can run (Plan 00376 review finding MAJOR 4)."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"approve-upgrade"],
                safety_notes="Denied before execution; the version is a dummy that cannot exist.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Block forging the upgrade-approval marker with touch",
                command="touch untracked/upgrade-approvals/99.0.0.approved",
                dispatch_as_bash=True,
                description="Writing the marker directly, bypassing the TTY prompt, is denied.",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"upgrade-approvals"],
                safety_notes="Denied before execution; no file is created.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Block exporting the Layer 1 handoff variable",
                command=f"export {ENV_VAR_UPGRADE_HANDOFF}=/tmp/handoff",
                dispatch_as_bash=True,
                description="Impersonating the upgrade's Layer 1 by hand is denied.",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"Layer 1"],
                safety_notes="Denied before execution; no shell state changes.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Allow reading an approval marker",
                command="cat untracked/upgrade-approvals/99.0.0.approved",
                dispatch_as_bash=True,
                description="A read-only reference to the approvals directory is never denied.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read of a file that does not exist; the shell reports the error, not the guard.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
