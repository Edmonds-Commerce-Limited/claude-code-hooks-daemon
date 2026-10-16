"""SubagentContextBudgetHandler - bound a subagent's context with a forced handoff (Plan 00471 L2).

Every tool call re-reads the agent's whole context, so spend is roughly average
context x tool calls. Measured in this project: 76.5 % of subagent spend ran at a
context above 200k, from agents reused for task after task. Claude Code has no
subagent-only compaction setting, so this is the subagent-only substitute: it
never touches the coordinator (scope SUB).

- **Soft band** (``soft_tokens``): one ``additionalContext`` per band crossing,
  naming the handoff file, a WIP commit, and a SendMessage to the lead. Advising
  on every call would itself grow the context.
- **Hard band** (``hard_tokens``, shipped OFF): every tool is denied except the
  three handoff steps: Write/Edit (and Read) under ``handoff_globs``, Bash whose
  every segment starts with an ``allowed_bash_prefixes`` entry, and SendMessage.
  After three consecutive denials the reason escalates to "stop now; your
  worktree state is the handoff". Nothing is killed and nothing is lost: the
  allowlist always admits the handoff, and ``subagent_handoff_gate`` holds the
  stop until it exists.
- **Override**: a ``budget: <N>k`` line in a NAMED dispatch's prompt raises this
  agent's bands, clamped to ``max_override_tokens`` so it never switches the
  gate off (``agent_dispatch_recorder`` records it at dispatch).
- **Unmeasured**: a transcript that cannot be found or read ALLOWS, with one
  ``unmeasured`` verdict per ``(agent_id, reason)`` (RULINGS-fable.md Q2). A
  budget is a cost control: failing closed would lock every subagent out the
  day Claude Code moves the file.

List options follow the additive/replace standard: ``mode: additive`` (the
default, and the reading of an unknown value) merges onto the built-in globs and
prefixes; ``mode: replace`` uses only the project's.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
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
from claude_code_hooks_daemon.core import Decision, GatingResult, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.utils.agent_dispatch_registry import (
    UNNAMED_AGENT_ID,
    dispatch_budget,
    effective_agent_type,
)
from claude_code_hooks_daemon.utils.spend_ledger import (
    note_unmeasured,
    read_state,
    state_path,
    write_state,
)
from claude_code_hooks_daemon.utils.transcript_spend import plan_key_from
from claude_code_hooks_daemon.utils.transcript_tail import read_tail, resolve_agent_transcript

_MODE_ADDITIVE: Final[str] = "additive"
_MODE_REPLACE: Final[str] = "replace"

#: Where a handoff may be written while the hard band is on.
DEFAULT_HANDOFF_GLOBS: Final[tuple[str, ...]] = ("**/subagent-reports/**", "untracked/scratch/**")

#: Bash a handoff needs: look at the worktree, stage it, commit it.
DEFAULT_BASH_PREFIXES: Final[tuple[str, ...]] = (
    "git status",
    "git diff",
    "git add",
    "git commit",
    "git log",
)

DEFAULT_SOFT_TOKENS: Final[int] = 300_000
DEFAULT_MAX_OVERRIDE_TOKENS: Final[int] = 450_000

#: Consecutive hard-band denials after which the reason says to stop.
ESCALATE_AFTER_DENIALS: Final[int] = 3

#: The state-document kind, shared with ``subagent_handoff_gate``.
STATE_KIND: Final[str] = "context-budget"

STATE_ADVISED: Final[str] = "advised"
STATE_DENIALS: Final[str] = "denials"
STATE_HARD_ENGAGED: Final[str] = "hard_engaged"
STATE_HANDOFF_PATH: Final[str] = "handoff_path"
STATE_HANDOFF_WRITTEN: Final[str] = "handoff_written"

_BAND_SOFT: Final[str] = "soft"
_HANDOFF_SUFFIX: Final[str] = "-handoff.md"
_REPORTS_DIR: Final[str] = "subagent-reports"
_SCRATCH_DIR: Final[tuple[str, ...]] = ("untracked", "scratch")
_PLAN_ROOT: Final[tuple[str, ...]] = ("CLAUDE", "Plan")
_LABEL_UNSAFE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]")

#: Shell separators between the segments a Bash allowlist judges one by one.
_SEGMENT_SPLIT: Final[re.Pattern[str]] = re.compile(r"&&|\|\||[;|\n]")
#: Anything that runs a command the segment text does not show.
_HIDDEN_EXECUTION: Final[re.Pattern[str]] = re.compile(r"\$\(|`|<\(|>\(")
_GIT_DIR_OPTION: Final[re.Pattern[str]] = re.compile(r"^git\s+-C\s+\S+\s+")
_CD: Final[re.Pattern[str]] = re.compile(r"^cd(\s+\S+)?$")

_FILE_TOOLS: Final[frozenset[str]] = frozenset({ToolName.WRITE, ToolName.EDIT, ToolName.READ})

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.SUBAGENT_CONTEXT_BUDGET,
    blocked="a subagent tool call outside the handoff steps at or above the hard context budget",
    why="Every call re-reads the whole context, so an agent this large spends most of its tokens re-reading",
    fix="Write the handoff file named in the message, commit your work, SendMessage the lead, then stop",
    verbose=(
        "WHY BLOCKED:\n"
        "This subagent's context is at or above the hard budget. Every tool call\n"
        "re-reads the whole context, so continuing costs far more than a fresh agent\n"
        "started from a short handoff. Nothing is lost: your work is in the worktree.\n\n"
        "DO INSTEAD (these are always allowed):\n"
        "  1. Write the handoff file the message names (Write/Edit under the handoff\n"
        "     directories): what is done, what is left, where the state is.\n"
        "  2. git add and git commit your work in progress.\n"
        "  3. SendMessage the lead with the handoff path, then stop.\n\n"
        "A coordinator that needs a longer run dispatches the agent with a\n"
        "`budget: <N>k` line in its prompt (clamped to max_override_tokens)."
    ),
)


@dataclass(frozen=True)
class Bands:
    """The token thresholds that apply to one agent."""

    soft: int | None
    hard: int | None


def int_or_none(value: object) -> int | None:
    """A positive int option, or None for unset/disabled."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def handoff_path(project_root: Path, cwd: str, label: str, plan_key: str) -> Path:
    """The handoff file an agent is told to write.

    ``<plan>/subagent-reports/<yymmdd>-<label>-handoff.md`` in the checkout the
    agent runs in (its ``cwd`` when that holds a plan folder for its plan key),
    else ``untracked/scratch/`` of that checkout.
    """
    safe_label = _LABEL_UNSAFE.sub("-", label) or "agent"
    stamp = datetime.now(UTC).strftime("%y%m%d")
    name = f"{stamp}-{safe_label}{_HANDOFF_SUFFIX}"
    bases = [Path(cwd)] if cwd else []
    bases.append(project_root)
    if plan_key:
        for base in bases:
            plan_root = base.joinpath(*_PLAN_ROOT)
            matches = sorted(plan_root.glob(f"{int(plan_key):05d}-*")) if plan_root.is_dir() else []
            if matches:
                return matches[0] / _REPORTS_DIR / name
    return bases[0].joinpath(*_SCRATCH_DIR, name)


class SubagentContextBudgetHandler(PreToolUseHandlerBase):
    """Advise a subagent past ``soft_tokens``; past ``hard_tokens`` allow only its handoff."""

    #: Options, injected by the registry as ``self._<key>``.
    _soft_tokens: int | None = DEFAULT_SOFT_TOKENS
    _hard_tokens: int | None = None
    _handoff_globs: list[str] | None = None
    _allowed_bash_prefixes: list[str] | None = None
    _exempt_agent_types: list[str] | None = None
    _max_override_tokens: int | None = DEFAULT_MAX_OVERRIDE_TOKENS
    _mode: str | None = None

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUBAGENT_CONTEXT_BUDGET,
            priority=Priority.SUBAGENT_CONTEXT_BUDGET,
            terminal=True,
            scope=HandlerScope.SUB,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING],
        )
        # Overridable by a test; resolved lazily in production.
        self._untracked_override: Path | None = None
        self._project_root: Path | None = None

    @staticmethod
    def validate_options(options: Mapping[str, Any]) -> dict[str, str]:
        """Refuse a malformed option; the handler then runs on its default for it."""
        problems: dict[str, str] = {}
        for key in ("soft_tokens", "hard_tokens", "max_override_tokens"):
            value = options.get(key)
            if key in options and value is not None and int_or_none(value) is None:
                problems[key] = f"{key} must be a positive integer or null"
        for key in ("handoff_globs", "allowed_bash_prefixes", "exempt_agent_types"):
            value = options.get(key)
            if key in options and not (
                isinstance(value, list) and all(isinstance(item, str) for item in value)
            ):
                problems[key] = f"{key} must be a list of strings"
        return problems

    # ------------------------------------------------------------------
    # configuration
    # ------------------------------------------------------------------

    def _untracked_dir(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    def _root(self) -> Path:
        return self._project_root or ProjectContext.project_root()

    def _merged(self, configured: list[str] | None, defaults: tuple[str, ...]) -> list[str]:
        """A list option under the additive/replace standard."""
        extra = list(configured or [])
        if self._mode == _MODE_REPLACE:
            return extra
        return [*defaults, *(item for item in extra if item not in defaults)]

    def handoff_globs(self) -> list[str]:
        return self._merged(self._handoff_globs, DEFAULT_HANDOFF_GLOBS)

    def bash_prefixes(self) -> list[str]:
        return self._merged(self._allowed_bash_prefixes, DEFAULT_BASH_PREFIXES)

    def bands_for(self, hook_input: Mapping[str, Any]) -> Bands:
        """This agent's bands: the configured ones, raised by its dispatch override."""
        soft = int_or_none(self._soft_tokens)
        hard = int_or_none(self._hard_tokens)
        override = self._override(hook_input)
        if override is None:
            return Bands(soft, hard)
        if hard is not None:
            gap = hard - soft if soft is not None and soft < hard else 0
            raised_hard = max(hard, override)
            return Bands(max(soft or 0, raised_hard - gap) or None, raised_hard)
        return Bands(max(soft or 0, override), None)

    def _override(self, hook_input: Mapping[str, Any]) -> int | None:
        agent_id = str(hook_input.get(HookInputField.AGENT_ID) or "")
        name = str(hook_input.get(HookInputField.AGENT_TYPE) or "")
        if not name or UNNAMED_AGENT_ID.fullmatch(agent_id):
            return None
        budget = dispatch_budget(self._untracked_dir(), self._session(hook_input), name)
        if budget is None:
            return None
        ceiling = int_or_none(self._max_override_tokens) or DEFAULT_MAX_OVERRIDE_TOKENS
        return min(budget, ceiling)

    @staticmethod
    def _session(hook_input: Mapping[str, Any]) -> str:
        return str(hook_input.get(HookInputField.SESSION_ID) or "")

    @staticmethod
    def agent_label(hook_input: Mapping[str, Any]) -> str:
        """The agent's dispatch name when it has one, else its id."""
        agent_id = str(hook_input.get(HookInputField.AGENT_ID) or "")
        name = str(hook_input.get(HookInputField.AGENT_TYPE) or "")
        return name if name and not UNNAMED_AGENT_ID.fullmatch(agent_id) else agent_id

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every subagent tool call, unless both bands are off or its type is exempt."""
        if int_or_none(self._soft_tokens) is None and int_or_none(self._hard_tokens) is None:
            return False
        exempt = self._exempt_agent_types or []
        if not exempt:
            return True
        agent_type = effective_agent_type(
            self._untracked_dir(),
            self._session(hook_input),
            str(hook_input.get(HookInputField.AGENT_TYPE) or ""),
            str(hook_input.get(HookInputField.AGENT_ID) or ""),
        )
        return agent_type not in exempt

    def get_rules(self) -> list[Rule]:
        """The rule behind the hard-band deny."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Measure the agent's context and apply its band."""
        session = self._session(hook_input)
        agent_id = str(hook_input.get(HookInputField.AGENT_ID) or "")
        transcript = resolve_agent_transcript(
            str(hook_input.get(HookInputField.TRANSCRIPT_PATH) or ""), session, agent_id
        )
        if transcript is None:
            return self._unmeasured(hook_input, "transcript-missing")
        try:
            reading = read_tail(transcript)
        except OSError:
            return self._unmeasured(hook_input, "transcript-unreadable")
        if reading is None:
            return GatingResult(decision=Decision.ALLOW)

        bands = self.bands_for(hook_input)
        context = reading.context_tokens
        state_file = state_path(self._untracked_dir(), session, STATE_KIND, agent_id)
        state = read_state(state_file)
        target = self._handoff_target(hook_input)

        if bands.hard is not None and context >= bands.hard:
            return self._hard(hook_input, state_file, state, context, bands.hard, target)
        if bands.soft is not None and context >= bands.soft:
            advised = state.get(STATE_ADVISED)
            advised = advised if isinstance(advised, list) else []
            if _BAND_SOFT not in advised:
                state[STATE_ADVISED] = [*advised, _BAND_SOFT]
                state[STATE_HANDOFF_PATH] = str(target)
                write_state(state_file, state)
                return GatingResult(
                    decision=Decision.ALLOW,
                    context=[self._soft_advice(context, bands, target)],
                )
        return GatingResult(decision=Decision.ALLOW)

    def _handoff_target(self, hook_input: Mapping[str, Any]) -> Path:
        cwd = str(hook_input.get(HookInputField.CWD) or "")
        label = self.agent_label(hook_input)
        return handoff_path(self._root(), cwd, label, plan_key_from(label, cwd))

    def _unmeasured(self, hook_input: Mapping[str, Any], reason: str) -> GatingResult:
        untracked = self._untracked_dir()
        note_unmeasured(
            untracked,
            session_id=self._session(hook_input),
            agent_id=str(hook_input.get(HookInputField.AGENT_ID) or ""),
            reason=reason,
            handler=self.name,
            tool_name=str(hook_input.get(HookInputField.TOOL_NAME) or ""),
            log_dir=untracked / "logs" / "hooks",
        )
        return GatingResult(decision=Decision.ALLOW)

    @staticmethod
    def _soft_advice(context: int, bands: Bands, target: Path) -> str:
        hard = (
            f" At {bands.hard:,} every tool but those steps is denied."
            if bands.hard is not None
            else ""
        )
        return (
            f"CONTEXT BUDGET: this subagent's context is {context:,} tokens, past the "
            f"{bands.soft or 0:,} soft budget. Every tool call re-reads all of it, so a fresh "
            "agent from a short handoff is cheaper than continuing. At your next natural "
            f"break: (1) write a handoff to {target} (done, left, where the state is); "
            "(2) git add and commit your work in progress; (3) SendMessage the lead with the "
            f"handoff path, then stop.{hard} This advice is given once."
        )

    # ------------------------------------------------------------------
    # the hard band
    # ------------------------------------------------------------------

    def _hard(
        self,
        hook_input: Mapping[str, Any],
        state_file: Path,
        state: dict[str, Any],
        context: int,
        hard: int,
        target: Path,
    ) -> GatingResult:
        state[STATE_HARD_ENGAGED] = True
        state[STATE_HANDOFF_PATH] = str(target)
        allowed, written = self._allowlisted(hook_input)
        if allowed:
            state[STATE_DENIALS] = 0
            if written:
                state[STATE_HANDOFF_WRITTEN] = written
            write_state(state_file, state)
            return GatingResult(decision=Decision.ALLOW)
        previous = state.get(STATE_DENIALS)
        previous = previous if isinstance(previous, int) and not isinstance(previous, bool) else 0
        state[STATE_DENIALS] = previous + 1
        write_state(state_file, state)
        escalate = previous >= ESCALATE_AFTER_DENIALS
        return GatingResult(
            decision=Decision.DENY,
            reason=self._deny_reason(context, hard, target, escalate=escalate),
        ).under_rule(_RULE)

    def _deny_reason(self, context: int, hard: int, target: Path, *, escalate: bool) -> str:
        steps = (
            f"  1. Write the handoff to {target}\n"
            "     (what is done, what is left, where the state is).\n"
            "  2. git add and git commit your work in progress.\n"
            "  3. SendMessage the lead with the handoff path, then stop."
        )
        if escalate:
            return (
                f"CONTEXT BUDGET EXCEEDED ({context:,} >= {hard:,} tokens), and the last "
                f"{ESCALATE_AFTER_DENIALS} calls were denied too. Stop now; your worktree "
                "state is the handoff. If you can, first:\n"
                f"{steps}"
            )
        return (
            f"CONTEXT BUDGET EXCEEDED: this subagent's context is {context:,} tokens, at or "
            f"above the hard budget of {hard:,}. Only the handoff steps are allowed:\n"
            f"{steps}\n\n"
            "Allowed now: Write/Edit/Read under "
            f"{', '.join(self.handoff_globs())}; Bash made only of "
            f"{', '.join(self.bash_prefixes())}; SendMessage. Nothing is lost: your work "
            "stays in the worktree."
        )

    def _allowlisted(self, hook_input: Mapping[str, Any]) -> tuple[bool, str]:
        """Whether the call is a handoff step, and the handoff path it writes (or ``""``)."""
        tool = hook_input.get(HookInputField.TOOL_NAME)
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        tool_input = tool_input if isinstance(tool_input, dict) else {}
        if tool == ToolName.SEND_MESSAGE:
            return True, ""
        if tool == ToolName.BASH:
            return self._bash_allowed(str(tool_input.get("command") or "")), ""
        if tool in _FILE_TOOLS:
            path = str(tool_input.get("file_path") or "")
            if path and self._under_handoff_globs(path, hook_input):
                return True, path if tool != ToolName.READ else ""
        return False, ""

    def _bash_allowed(self, command: str) -> bool:
        if not command.strip() or _HIDDEN_EXECUTION.search(command):
            return False
        prefixes = self.bash_prefixes()
        for raw in _SEGMENT_SPLIT.split(command):
            segment = " ".join(raw.split())
            if not segment or _CD.match(segment):
                continue
            segment = _GIT_DIR_OPTION.sub("git ", segment)
            if not any(
                segment == prefix or segment.startswith(prefix + " ") for prefix in prefixes
            ):
                return False
        return True

    def _under_handoff_globs(self, path: str, hook_input: Mapping[str, Any]) -> bool:
        normalised = os.path.normpath(path)
        candidates = [normalised]
        for base in (str(hook_input.get(HookInputField.CWD) or ""), str(self._root())):
            if base and normalised.startswith(base.rstrip("/") + "/"):
                candidates.append(normalised[len(base.rstrip("/")) + 1 :])
        return any(
            fnmatch.fnmatch(candidate, glob)
            for candidate in candidates
            for glob in self.handoff_globs()
        )

    # ------------------------------------------------------------------
    # documentation
    # ------------------------------------------------------------------

    def get_claude_md(self) -> str | None:
        """Resident guidance: a subagent should know the handoff route before the deny."""
        return (
            "## subagent_context_budget — a large subagent hands off\n\n"
            "Inside a subagent, past `soft_tokens` of context you are told ONCE to hand "
            "off; past `hard_tokens` (off unless configured) every tool is DENIED except "
            "the handoff: Write/Edit/Read under `handoff_globs` (`**/subagent-reports/**`, "
            "`untracked/scratch/**`), Bash made only of `git status|diff|add|commit|log`, "
            "and SendMessage. The handoff is a file at the path the message names "
            "(`<plan>/subagent-reports/<yymmdd>-<agent>-handoff.md`), a WIP commit, and a "
            "SendMessage to the lead. Past `hard_tokens`, `subagent_handoff_gate` also "
            "BLOCKS the agent's stop until that handoff file exists (at most three times, "
            "then the worktree is the handoff). A coordinator raises one agent's budget with a "
            "`budget: <N>k` line in a NAMED dispatch's prompt, clamped to "
            "`max_override_tokens`. An unmeasurable transcript never blocks."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """The soft advisory through a real subagent; the hard band is unit-tested."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="subagent context budget - a large subagent is advised once",
                command=("Inside a subagent whose context is past soft_tokens, run any tool twice"),
                description=(
                    "The first call carries additionalContext naming the handoff file, a WIP "
                    "commit and a SendMessage to the lead; the second carries none. Hard "
                    "mode ships off, and its deny/allow matrix is covered by "
                    "tests/unit/handlers/pre_tool_use/test_subagent_context_budget.py."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"CONTEXT BUDGET", r"handoff"],
                safety_notes="Advisory only at the soft band; never denies with hard_tokens unset.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "The harness marks every probe synthetic, and a SUB-scoped handler "
                    "declines a synthetic event unless it is a probe standing for a "
                    "subagent; the context also comes from a real agent transcript. Run "
                    "it through a real subagent in this repository (soft_tokens 150000)."
                ),
            )
        ]
