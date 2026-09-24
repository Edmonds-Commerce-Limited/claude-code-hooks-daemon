"""SubagentFullQaBlockerHandler - a sub-agent does not start a full QA run.

Plan 00463. When the owner asked for this, five full-suite runs were executing
at once, one per worktree. Each took 15-20 minutes on an eight-core host. Each
agent then re-ran the suite after every fix round, and the coordinator ran it
again before merging. The full gate stays BEFORE the merge, because
cross-cutting checks break from changes far away and a first full run on the
main branch would land every such break there. It moves to the coordinator,
which runs it on the delivered branch head, one run at a time: once per
delivery rather than once per fix round.

**What "full" means is the project's to declare.** ``full_qa_patterns`` names
commands by the program they RUN (basename of the script, binary or
``python -m`` module) and says which arguments make that program run the whole
suite. Nothing ships by default: a client's full-QA commands cannot be known
here, and a default built from this repository's own commands could never fire
anywhere else. An enabled handler with no patterns is reported by
``get_enforcement_status`` rather than left looking like a guard with nothing
to deny.

**Commands are parsed, never substring-matched.** The shared scanner in
``utils.shell_segmentation`` blanks what bash hands over as data (a commit
message, a heredoc body fed to ``cat``) and splits the rest into commands.
Each command is resolved through wrappers (``timeout``, ``env``, ``nohup``),
interpreters (``python3 x.py``, ``python -m pytest``, ``bash -c '...'``) and
project runners (``uv run``) to the program it actually starts. So ``grep
"llm_qa.py all"`` and a commit message saying the same are never denied: they
RUN ``grep`` and ``git``.

**The scope key carries the role test, so this module never reads
``agent_id``.** ``scope=SUB`` admits an event only when ``agent_id`` is present
and the event is not synthetic (``core.handler_scope``). The coordinator's own
full run therefore draws nothing, and neither does the acceptance harness.

This is a resource guard for cooperating agents, not a security boundary.
Spellings the scanner cannot see through, such as a substitution inside
double quotes or a script that runs the suite under another name, are not
chased: the coordinator's full gate still runs before every merge, and the cost
of a miss is one wasted run.
"""

from __future__ import annotations

import logging
import re
import shlex
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    Priority,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import normalise_line_continuations
from claude_code_hooks_daemon.utils.shell_segmentation import (
    command_word,
    peel_command_wrappers,
    split_unquoted,
    strip_inert_spans,
)

logger = logging.getLogger(__name__)

# ── Pattern schema ─────────────────────────────────────────────────────────

_KEY_ID: Final[str] = "id"
_KEY_COMMAND: Final[str] = "command"
_KEY_FULL_ARGS: Final[str] = "full_args"
_KEY_BARE_IS_FULL: Final[str] = "bare_is_full"
_KEY_READ_ONLY_FLAGS: Final[str] = "read_only_flags"
_KEY_VALUE_FLAGS: Final[str] = "value_flags"

_KNOWN_KEYS: Final[frozenset[str]] = frozenset(
    {
        _KEY_ID,
        _KEY_COMMAND,
        _KEY_FULL_ARGS,
        _KEY_BARE_IS_FULL,
        _KEY_READ_ONLY_FLAGS,
        _KEY_VALUE_FLAGS,
    }
)
_REQUIRED_TEXT_KEYS: Final[tuple[str, ...]] = (_KEY_ID, _KEY_COMMAND)
_WORD_LIST_KEYS: Final[tuple[str, ...]] = (_KEY_FULL_ARGS, _KEY_READ_ONLY_FLAGS, _KEY_VALUE_FLAGS)

#: The option names, for messages that tell a project what to fix.
_OPTION_PATTERNS: Final[str] = "full_qa_patterns"


@dataclass(frozen=True, slots=True)
class FullQaPattern:
    """One declared full-suite command.

    Attributes:
        pattern_id: Names the pattern in the deny, so an agent can see WHICH
            declaration it hit.
        command: The basename of the program the command runs.
        full_args: Operands that make the program run the whole suite. None
            means every run of it is full.
        bare_is_full: With ``full_args`` set, a run naming no operand at all
            is full too (``pytest`` with no path collects the whole suite).
        read_only_flags: Flags that make the run a read rather than a run
            (``--read-only``, ``--collect-only``).
        value_flags: Flags whose next word is their value, so that word is not
            mistaken for an operand (``pytest -k expr``).
    """

    pattern_id: str
    command: str
    full_args: frozenset[str] | None
    bare_is_full: bool
    read_only_flags: frozenset[str]
    value_flags: frozenset[str]


@dataclass(frozen=True, slots=True)
class FullQaMatch:
    """The first full-suite invocation found in a command."""

    pattern_id: str
    segment: str


def parse_full_qa_patterns(raw: object) -> tuple[list[FullQaPattern], list[str]]:
    """Validate the ``full_qa_patterns`` option.

    A malformed entry is skipped and REPORTED, never guessed at. Guessing
    ``full_args: tests`` (a string) into ``["t", "e", ...]`` or into "every
    run is full" would each produce a guard nobody configured.

    Args:
        raw: The option value exactly as the YAML produced it.

    Returns:
        ``(patterns, problems)``: every valid entry, in order, and one sentence
        per entry that could not be used.
    """
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], [f"`{_OPTION_PATTERNS}` must be a list of mappings, got {type(raw).__name__}"]

    patterns: list[FullQaPattern] = []
    problems: list[str] = []
    seen_ids: set[str] = set()
    for position, entry in enumerate(raw, start=1):
        pattern, problem = _parse_entry(position, entry)
        if problem is not None:
            problems.append(problem)
            continue
        if pattern is None:
            continue
        if pattern.pattern_id in seen_ids:
            problems.append(f"entry {position}: duplicate id `{pattern.pattern_id}`")
            continue
        seen_ids.add(pattern.pattern_id)
        patterns.append(pattern)
    return patterns, problems


def _parse_entry(position: int, entry: object) -> tuple[FullQaPattern | None, str | None]:
    """One entry, or the sentence saying why it cannot be used."""
    if not isinstance(entry, Mapping):
        return None, f"entry {position}: expected a mapping, got {type(entry).__name__}"

    unknown = sorted(str(key) for key in entry if key not in _KNOWN_KEYS)
    if unknown:
        return None, f"entry {position}: unknown key(s) {', '.join(unknown)}"

    for key in _REQUIRED_TEXT_KEYS:
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            return None, f"entry {position}: `{key}` must be a non-empty string"

    word_lists: dict[str, frozenset[str] | None] = {}
    for key in _WORD_LIST_KEYS:
        value = entry.get(key)
        if value is None:
            word_lists[key] = None
            continue
        if not isinstance(value, list) or not all(
            isinstance(word, str) and word.strip() for word in value
        ):
            return None, f"entry {position}: `{key}` must be a list of non-empty strings"
        word_lists[key] = frozenset(word.strip() for word in value)

    bare_is_full = entry.get(_KEY_BARE_IS_FULL, False)
    if not isinstance(bare_is_full, bool):
        return None, f"entry {position}: `{_KEY_BARE_IS_FULL}` must be true or false"

    full_args = word_lists[_KEY_FULL_ARGS]
    return (
        FullQaPattern(
            pattern_id=str(entry[_KEY_ID]).strip(),
            command=command_word(str(entry[_KEY_COMMAND]).strip()),
            full_args=(
                None if full_args is None else frozenset(_normalise_operand(a) for a in full_args)
            ),
            bare_is_full=bare_is_full,
            read_only_flags=word_lists[_KEY_READ_ONLY_FLAGS] or frozenset(),
            value_flags=word_lists[_KEY_VALUE_FLAGS] or frozenset(),
        ),
        None,
    )


# ── Resolving what a command runs ──────────────────────────────────────────

#: Where one command ends and the next begins. Beyond the chain and pipe
#: separators, a grouping or substitution delimiter also starts a new command:
#: ``(cd x && pytest)`` and ``echo $(pytest)`` both RUN pytest. Outside quotes
#: only, which ``split_unquoted`` guarantees.
_COMMAND_BOUNDARIES: Final[tuple[str, ...]] = ("&&", "||", ";", "|", "\n", "(", ")", "`")

#: A lone ``&`` backgrounds the command before it and starts another. It is
#: split at WORD level rather than above, because ``2>&1`` carries one too.
_BACKGROUND: Final[str] = "&"

#: ``NAME=value`` ahead of a command is an environment assignment, not the
#: command.
_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_]\w*=")

#: Shell keywords that can sit in front of a command without being it.
_SHELL_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "time", "exec"}
)

#: A redirection word. When nothing follows the operator, the target is the
#: next word (``> log``); otherwise it is attached (``2>&1``, ``>log``).
_REDIRECT: Final[re.Pattern[str]] = re.compile(r"^(?:\d*|&)(?:>>?|<<?<?|>&|<&)(?P<target>.*)$")

_PYTHON_INTERPRETER: Final[re.Pattern[str]] = re.compile(r"^python(?:\d+(?:\.\d+)*)?$")
_PYTHON_VALUE_FLAGS: Final[frozenset[str]] = frozenset({"-X", "-W"})
_PYTHON_MODULE_FLAG: Final[str] = "-m"
_PYTHON_CODE_FLAG: Final[str] = "-c"

_SHELL_INTERPRETERS: Final[frozenset[str]] = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_SHELL_VALUE_FLAGS: Final[frozenset[str]] = frozenset({"-o", "+o", "-O", "+O"})
_SHELL_CODE_LETTER: Final[str] = "c"

#: Project runners whose ``run`` subcommand starts the command after it.
_PROJECT_RUNNERS: Final[frozenset[str]] = frozenset({"uv", "poetry", "pipenv", "pdm", "hatch"})
_RUNNER_SUBCOMMAND: Final[str] = "run"

#: How deep ``bash -c '...'`` is followed. Deeper nesting is not a way anyone
#: runs a test suite by accident.
_MAX_NESTING: Final[int] = 3

_FLAG_PREFIX: Final[str] = "-"
_LONG_FLAG_PREFIX: Final[str] = "--"
_END_OF_OPTIONS: Final[str] = "--"
_LONE_DASH: Final[str] = "-"
_FLAG_VALUE_SEPARATOR: Final[str] = "="
_CURRENT_DIR: Final[str] = "."
_CURRENT_DIR_PREFIX: Final[str] = "./"
_PATH_SEPARATOR: Final[str] = "/"


def _words(segment: str) -> list[str]:
    """The words of one command, quoting removed as bash would remove it.

    An unbalanced quote (usually a fragment the segmenter cut out of a larger
    construct) falls back to whitespace splitting rather than failing: the
    worst outcome is a word that still carries a quote character and so
    matches nothing.
    """
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _split_background(words: list[str]) -> Iterator[list[str]]:
    """Split one word list at each lone ``&`` word."""
    current: list[str] = []
    for word in words:
        if word == _BACKGROUND:
            yield current
            current = []
            continue
        current.append(word)
    yield current


def _invocations(command: str, depth: int = 0) -> Iterator[tuple[str, list[str], str]]:
    """Every ``(program, arguments, segment)`` the command would run.

    Line continuations are joined here as well as at ``get_bash_command``:
    the code string inside ``bash -c '...'`` never passed through that
    boundary, and joining twice changes nothing.
    """
    scan_target = strip_inert_spans(normalise_line_continuations(command))
    for segment in split_unquoted(scan_target, _COMMAND_BOUNDARIES):
        for words in _split_background(_words(segment)):
            yield from _resolve(words, segment, depth)


def _strip_prefixes(argv: list[str]) -> list[str]:
    """Drop assignments, keywords and wrappers until the command word leads."""
    while True:
        start = 0
        while start < len(argv) and (
            _ASSIGNMENT.match(argv[start]) or argv[start] in _SHELL_KEYWORDS
        ):
            start += 1
        _, peeled = peel_command_wrappers(argv[start:])
        if start == 0 and peeled == 0:
            return argv
        argv = argv[start + peeled :]


def _resolve(words: list[str], segment: str, depth: int) -> Iterator[tuple[str, list[str], str]]:
    """Resolve one word list to the program it starts."""
    argv = _strip_prefixes(words)
    if not argv:
        return
    name = command_word(argv[0])
    rest = argv[1:]
    if not name:
        return

    if name in _PROJECT_RUNNERS:
        operands = [word for word in rest if not word.startswith(_FLAG_PREFIX)]
        if operands and operands[0] == _RUNNER_SUBCOMMAND:
            yield from _resolve(rest[rest.index(_RUNNER_SUBCOMMAND) + 1 :], segment, depth)
        return

    if _PYTHON_INTERPRETER.match(name):
        yield from _resolve_python(rest, segment)
        return

    if name in _SHELL_INTERPRETERS:
        yield from _resolve_shell(rest, segment, depth)
        return

    yield name, rest, segment


def _resolve_python(rest: list[str], segment: str) -> Iterator[tuple[str, list[str], str]]:
    """``python [flags] script args`` or ``python [flags] -m module args``."""
    index = 0
    while index < len(rest):
        argument = rest[index]
        if argument == _PYTHON_MODULE_FLAG:
            if index + 1 < len(rest):
                yield rest[index + 1], rest[index + 2 :], segment
            return
        if argument.startswith(_PYTHON_MODULE_FLAG) and not argument.startswith(_LONG_FLAG_PREFIX):
            yield argument[len(_PYTHON_MODULE_FLAG) :], rest[index + 1 :], segment
            return
        if argument == _PYTHON_CODE_FLAG:
            # Python source, not a shell command: nothing here is a program.
            return
        if argument in _PYTHON_VALUE_FLAGS:
            index += 2
            continue
        if argument.startswith(_FLAG_PREFIX):
            index += 1
            continue
        yield command_word(argument), rest[index + 1 :], segment
        return


def _resolve_shell(
    rest: list[str], segment: str, depth: int
) -> Iterator[tuple[str, list[str], str]]:
    """``bash script args`` runs the script; ``bash -c 'code'`` runs the code."""
    index = 0
    runs_code = False
    while index < len(rest):
        argument = rest[index]
        if argument in _SHELL_VALUE_FLAGS:
            index += 2
            continue
        if argument.startswith(_FLAG_PREFIX) and not argument.startswith(_LONG_FLAG_PREFIX):
            runs_code = runs_code or _SHELL_CODE_LETTER in argument[1:]
            index += 1
            continue
        if argument.startswith(_LONG_FLAG_PREFIX):
            index += 1
            continue
        if runs_code:
            if depth < _MAX_NESTING:
                yield from _invocations(argument, depth + 1)
            return
        yield command_word(argument), rest[index + 1 :], segment
        return


def _normalise_operand(value: str) -> str:
    """Spell a path operand one way: ``./tests/`` and ``tests`` are the same run."""
    if value.startswith(_PATH_SEPARATOR):
        return value.rstrip(_PATH_SEPARATOR) or _PATH_SEPARATOR
    normalised = value
    while normalised.startswith(_CURRENT_DIR_PREFIX):
        normalised = normalised[len(_CURRENT_DIR_PREFIX) :]
    return normalised.rstrip(_PATH_SEPARATOR) or _CURRENT_DIR


def _operand_is_full(operand: str, full_args: frozenset[str]) -> bool:
    """An operand names a full run directly, or as an absolute path ending in one."""
    if operand in full_args:
        return True
    if not operand.startswith(_PATH_SEPARATOR):
        return False
    return any(
        operand.endswith(_PATH_SEPARATOR + entry) for entry in full_args if entry != _CURRENT_DIR
    )


def _is_full_run(pattern: FullQaPattern, arguments: Sequence[str]) -> bool:
    """Whether these arguments make ``pattern.command`` run the whole suite."""
    operands: list[str] = []
    index = 0
    options_ended = False
    while index < len(arguments):
        argument = arguments[index]
        index += 1
        redirect = _REDIRECT.match(argument)
        if redirect is not None:
            if not redirect.group("target"):
                index += 1
            continue
        if not options_ended and argument == _END_OF_OPTIONS:
            options_ended = True
            continue
        if not options_ended and argument.startswith(_FLAG_PREFIX) and argument != _LONE_DASH:
            if argument.split(_FLAG_VALUE_SEPARATOR, 1)[0] in pattern.read_only_flags:
                return False
            if argument in pattern.value_flags:
                index += 1
            continue
        operands.append(_normalise_operand(argument))

    if pattern.full_args is None:
        return True
    if any(_operand_is_full(operand, pattern.full_args) for operand in operands):
        return True
    return not operands and pattern.bare_is_full


def find_full_qa_invocation(command: str, patterns: Sequence[FullQaPattern]) -> FullQaMatch | None:
    """The first full-suite run in ``command``, or None.

    Args:
        command: The Bash command as the tool received it (line continuations
            already joined by ``get_bash_command``).
        patterns: The validated declaration.

    Returns:
        The pattern that matched and the command segment it matched in.
    """
    if not patterns:
        return None
    for program, arguments, segment in _invocations(command):
        for pattern in patterns:
            if pattern.command == program and _is_full_run(pattern, arguments):
                return FullQaMatch(pattern_id=pattern.pattern_id, segment=segment.strip())
    return None


# ── The handler ────────────────────────────────────────────────────────────

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.SUBAGENT_FULL_QA,
    blocked="a full-suite QA run inside a sub-agent (a declared `full_qa_patterns` command)",
    why="Concurrent full runs across agents exhaust the host, and the coordinator runs the full gate before every merge anyway",
    fix="Run targeted QA on what you changed, commit, and hand the commit to the coordinator",
    verbose=(
        "WHY BLOCKED:\n"
        "The full QA suite is the COORDINATOR's gate. It runs once per delivery,\n"
        "on your branch head, one run at a time. Several agents each running the\n"
        "whole suite exhaust the host, and the coordinator repeats every one of\n"
        "those runs before the merge anyway.\n\n"
        "DO INSTEAD:\n"
        "  1. Run targeted QA: the checks and tests that cover what you changed.\n"
        "  2. Commit, then send the coordinator the commit hash and your targeted\n"
        "     results.\n"
        "  3. The coordinator runs the full gate and sends back anything it finds.\n\n"
        "Only a command that RUNS the whole suite is denied. Mentioning one in a\n"
        "commit message, a grep or an echo never is, and the coordinator's own\n"
        "run is unaffected."
    ),
)

_GENERIC_TARGETED_FORM: Final[str] = (
    "  - the same tools scoped to what you changed: named checks rather than the\n"
    "    whole suite, and tests on explicit test files or directories"
)


class SubagentFullQaBlockerHandler(PreToolUseHandlerBase):
    """Deny a declared full-suite QA run inside a sub-agent; the coordinator runs it.

    Terminal: the deny is the final word on the call. It runs ahead of any
    project handler that would redirect a verbose QA script to the full
    LLM-optimised suite, because that advice is wrong for a sub-agent.

    Options (``handlers.pre_tool_use.subagent_full_qa_blocker.options``):
        full_qa_patterns: list of ``{id, command, full_args?, bare_is_full?,
            read_only_flags?, value_flags?}``. Default empty, which is inert.
        targeted_qa_commands: list of command strings the deny names as the
            allowed path. Default empty, which names the generic form.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUBAGENT_FULL_QA_BLOCKER,
            priority=Priority.SUBAGENT_FULL_QA_BLOCKER,
            terminal=True,
            # The whole role test. The handler must not re-derive main-vs-sub.
            scope=HandlerScope.SUB,
            tags=[
                HandlerTag.QA_ENFORCEMENT,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
                HandlerTag.WORKFLOW,
            ],
        )
        # Injected by the registry via blind setattr from YAML after
        # construction, so they are typed as the untrusted values they are and
        # validated on every read rather than parsed once here.
        self._full_qa_patterns: object = None
        self._targeted_qa_commands: object = None
        self._reported_problems: frozenset[str] = frozenset()

    def get_default_enabled(self) -> bool:
        """Opt-IN: a client's full-QA commands cannot be known from here."""
        return False

    def _patterns(self) -> list[FullQaPattern]:
        """The valid declaration, logging each NEW problem once."""
        patterns, problems = parse_full_qa_patterns(self._full_qa_patterns)
        fresh = frozenset(problems) - self._reported_problems
        for problem in sorted(fresh):
            logger.warning("subagent_full_qa_blocker: %s (entry skipped)", problem)
        self._reported_problems |= fresh
        return patterns

    def _targeted_forms(self) -> list[str]:
        raw = self._targeted_qa_commands
        if not isinstance(raw, list):
            return []
        return [entry.strip() for entry in raw if isinstance(entry, str) and entry.strip()]

    def _find(self, hook_input: dict[str, Any]) -> FullQaMatch | None:
        command = get_bash_command(hook_input)
        if not command:
            return None
        return find_full_qa_invocation(command, self._patterns())

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when the Bash command would run a declared full suite."""
        return self._find(hook_input) is not None

    def get_rules(self) -> list[Rule]:
        """The single Rule backing this handler's deny."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Refuse, naming what matched and the targeted forms that are allowed.

        Always verbose. A sub-agent meets this a handful of times in its life,
        and the one thing it needs every time is the list of what to run
        instead.
        """
        match = self._find(hook_input)
        if match is None:
            return GatingResult(decision=Decision.ALLOW)

        declared = self._targeted_forms()
        instead = (
            "\n".join(f"  - {form}" for form in declared) if declared else _GENERIC_TARGETED_FORM
        )
        return GatingResult.deny(
            f"{RuleFormatter().verbose(_RULE)}\n\n"
            f"MATCHED: `{match.pattern_id}` in `{match.segment}`\n\n"
            f"RUN INSTEAD:\n{instead}"
        )

    def get_enforcement_status(self, project_root: Path) -> list[str]:
        """Report a declaration that leaves the guard unable to fire.

        Root-independent: the declaration is one per config, so every root
        reports the same lines and the caller de-duplicates them.
        """
        patterns, problems = parse_full_qa_patterns(self._full_qa_patterns)
        lines = [
            f"subagent_full_qa_blocker: `{_OPTION_PATTERNS}` {problem}" for problem in problems
        ]
        if not patterns:
            lines.append(
                "subagent_full_qa_blocker is enabled but declares no usable "
                f"`{_OPTION_PATTERNS}`, so it can never fire. Declare this "
                "project's full-suite commands, or disable the handler."
            )
        return lines

    def get_acceptance_tests(self) -> list[Any]:
        """Two probes, both a SUB-AGENT's payload, driven in-process.

        The live harness marks every probe synthetic, and ``scope=SUB``
        declines a synthetic event before ``matches()`` runs, so a live probe
        would observe ALLOW whatever the handler does. Declaring the probes as
        raw ``hook_input`` carrying an ``agent_id`` means the contract test
        drives the CONFIGURED handler directly, and the live harness skips
        them instead of recording a vacuous pass.

        ``pytest`` with no path is the whole suite in any pytest project, so
        the probes need no project-specific script. They pass only where the
        project declares an unscoped pytest as full, which this repository
        does.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        def _subagent_bash(command: str) -> dict[str, Any]:
            return {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "agent_id": "a-full-qa-probe",
            }

        return [
            AcceptanceTest(
                title="subagent full QA blocker - a sub-agent's whole-suite pytest is denied",
                command="pytest (no path, so the whole suite) from inside a sub-agent",
                description=(
                    "Inside a sub-agent, a declared full-suite run is refused. The reason "
                    "names the rule, says the coordinator runs the full gate, and lists "
                    "the targeted forms to run instead."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"R-SUBAGENT-FULL-QA", r"coordinator", r"RUN INSTEAD"],
                safety_notes="Never executed: the payload is judged in-process.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                hook_input=_subagent_bash("pytest"),
            ),
            AcceptanceTest(
                title="subagent full QA blocker - a sub-agent's targeted pytest is allowed",
                command="pytest on one explicit test file from inside a sub-agent",
                description=(
                    "The near-miss, and the path the deny sends agents down: pytest on "
                    "explicit test paths is targeted QA and is never matched."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Never executed: the payload is judged in-process.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                hook_input=_subagent_bash("pytest tests/unit/test_example.py"),
            ),
        ]

    def get_claude_md(self) -> str | None:
        """Resident guidance: a sub-agent needs the split BEFORE it plans its QA.

        Criterion T1 (it denies) and T3 (a standing policy): an agent that
        learns it from a deny has already queued a full run it cannot make.
        """
        return (
            "## subagent_full_qa_blocker — full QA is the coordinator's gate\n\n"
            "Inside a SUB-AGENT, a Bash command that would run a declared full-suite "
            "QA command (`full_qa_patterns`) is DENIED. The coordinator runs the full "
            "gate once per delivery, on the branch head, one run at a time. The main "
            "thread is never affected.\n\n"
            "**As a sub-agent**: run targeted QA (the checks and tests covering what you "
            "changed), commit, and hand the commit hash to the coordinator. The deny "
            "lists the targeted commands this project declares "
            "(`targeted_qa_commands`).\n\n"
            "**Commands are parsed, not substring-matched.** A commit message, `grep` or "
            "`echo` that mentions a full-QA command runs nothing and is never denied; a "
            "read-only form such as a `--read-only` summary is allowed if the project "
            "declares that flag.\n\n"
            "**Configure** under `handlers.pre_tool_use.subagent_full_qa_blocker.options`: "
            "`full_qa_patterns` entries are `{id, command, full_args?, bare_is_full?, "
            "read_only_flags?, value_flags?}`, where `command` is the program's basename "
            "and `full_args` are the operands that make it run the whole suite (omit it "
            "and every run is full). Ships off with no patterns; enabled with none, "
            "`hooks-daemon check` reports it as unable to fire."
        )
