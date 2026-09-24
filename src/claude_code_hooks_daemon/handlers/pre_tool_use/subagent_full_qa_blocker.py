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

**Coverage is proven for two agent kinds, not claimed for a third.** Agent-tool
subagents carry ``agent_id`` (Plan 00423), and so do in-process teammates
(measured by Plan 00463). A Workflow-tool agent's payload is UNMEASURED, so
this guard is not claimed to see one. Nothing here keys on the agent's kind or
on the id's shape, only on the field being non-empty, so if a Workflow agent
turns out to carry it the guard covers it with no change.

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
    END_OF_OPTIONS,
    FLAG_PREFIX,
    LONE_DASH,
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
_KEY_OPTION_GRAMMAR: Final[str] = "option_grammar"

_KNOWN_KEYS: Final[frozenset[str]] = frozenset(
    {
        _KEY_ID,
        _KEY_COMMAND,
        _KEY_FULL_ARGS,
        _KEY_BARE_IS_FULL,
        _KEY_READ_ONLY_FLAGS,
        _KEY_VALUE_FLAGS,
        _KEY_OPTION_GRAMMAR,
    }
)

#: Every pytest option that takes a value: pytest's own, pytest-cov's, and
#: those of the plugins most often installed beside it (xdist, timeout,
#: randomly, rerunfailures, asyncio, html). A value can look like a path
#: (``--basetemp /tmp/x``, ``--cov src``), so the grammar has to consume it
#: before the operand test sees it. ``test_subagent_full_qa_blocker`` pins
#: this set against the parser of the pytest actually installed.
PYTEST_VALUE_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        # pytest core
        "-c",
        "-k",
        "-m",
        "-o",
        "-p",
        "-r",
        "-W",
        "--assert",
        "--basetemp",
        "--cache-show",
        "--capture",
        "--code-highlight",
        "--color",
        "--confcutdir",
        "--config-file",
        "--debug",
        "--deselect",
        "--doctest-glob",
        "--doctest-report",
        "--durations",
        "--durations-min",
        "--ignore",
        "--ignore-glob",
        "--import-mode",
        "--junit-prefix",
        "--junit-xml",
        "--junitprefix",
        "--junitxml",
        "--last-failed-no-failures",
        "--lfnf",
        "--log-auto-indent",
        "--log-cli-date-format",
        "--log-cli-format",
        "--log-cli-level",
        "--log-date-format",
        "--log-disable",
        "--log-file",
        "--log-file-date-format",
        "--log-file-format",
        "--log-file-level",
        "--log-file-mode",
        "--log-format",
        "--log-level",
        "--maxfail",
        "--override-ini",
        "--pastebin",
        "--pdbcls",
        "--pythonwarnings",
        "--rootdir",
        "--show-capture",
        "--tb",
        "--verbosity",
        # pytest-cov
        "--cov",
        "--cov-config",
        "--cov-context",
        "--cov-fail-under",
        "--cov-precision",
        "--cov-report",
        # pytest-xdist
        "-n",
        "--numprocesses",
        "--maxprocesses",
        "--max-worker-restart",
        "--dist",
        "--tx",
        "--rsyncdir",
        "--rsyncignore",
        "--maxschedchunk",
        # pytest-timeout
        "--timeout",
        "--timeout-method",
        "--timeout_method",
        # pytest-randomly, pytest-rerunfailures, pytest-asyncio, pytest-html
        "--randomly-seed",
        "--reruns",
        "--reruns-delay",
        "--only-rerun",
        "--asyncio-mode",
        "--html",
        "--css",
    }
)

#: Named grammars a pattern can adopt with ``option_grammar``.
_OPTION_GRAMMARS: Final[Mapping[str, frozenset[str]]] = {"pytest": PYTEST_VALUE_OPTIONS}
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
            means every run of it is full. Any other operand targets the run
            only when it is path-like: it contains ``/`` or ``::``, ends in
            ``.py``, or exists under the event's working directory.
        bare_is_full: With ``full_args`` set, a run naming no operand at all
            is full too (``pytest`` with no path collects the whole suite).
        read_only_flags: Flags that make the run a read rather than a run
            (``--read-only``, ``--collect-only``).
        value_flags: Flags whose next word is their value, so that word is not
            mistaken for an operand (``pytest -k expr``). A declared
            ``option_grammar`` is merged in here.
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

    grammar_name = entry.get(_KEY_OPTION_GRAMMAR)
    grammar: frozenset[str] = frozenset()
    if grammar_name is not None:
        if grammar_name not in _OPTION_GRAMMARS:
            known = ", ".join(sorted(_OPTION_GRAMMARS))
            return None, f"entry {position}: `{_KEY_OPTION_GRAMMAR}` must be one of: {known}"
        grammar = _OPTION_GRAMMARS[grammar_name]

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
            value_flags=(word_lists[_KEY_VALUE_FLAGS] or frozenset()) | grammar,
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


@dataclass(frozen=True, slots=True)
class _Runner:
    """A project runner: ``<runner> [global flags] run [run flags] [--] <command>``.

    Each flag table lists the flags whose NEXT word is their value, so the
    value is never mistaken for the subcommand or the command.
    """

    global_value_flags: frozenset[str]
    run_value_flags: frozenset[str]


#: What ``uv run``, ``uv tool run`` and ``uvx`` take a value for.
_UV_RUN_VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "--with",
        "--with-editable",
        "--with-requirements",
        "--from",
        "--python",
        "-p",
        "--package",
        "--extra",
        "--group",
        "--only-group",
        "--no-group",
        "--env-file",
        "--directory",
        "--project",
        "--index",
        "--default-index",
        "--index-url",
        "--extra-index-url",
        "--find-links",
        "-f",
        "--python-platform",
        "--config-file",
        "--cache-dir",
    }
)

#: Project runners whose ``run`` subcommand starts the command after it.
_PROJECT_RUNNERS: Final[Mapping[str, _Runner]] = {
    "uv": _Runner(
        global_value_flags=frozenset(
            {
                "--directory",
                "--project",
                "--config-file",
                "--cache-dir",
                "--python",
                "-p",
                "--color",
                "--allow-insecure-host",
            }
        ),
        run_value_flags=_UV_RUN_VALUE_FLAGS,
    ),
    "poetry": _Runner(
        global_value_flags=frozenset({"-C", "--directory", "-P", "--project"}),
        run_value_flags=frozenset(),
    ),
    "pipenv": _Runner(global_value_flags=frozenset(), run_value_flags=frozenset()),
    "pdm": _Runner(global_value_flags=frozenset({"-p", "--project"}), run_value_flags=frozenset()),
    "hatch": _Runner(global_value_flags=frozenset({"-e", "--env"}), run_value_flags=frozenset()),
}
_RUNNER_SUBCOMMAND: Final[str] = "run"
#: ``uv tool run`` and its alias ``uvx`` run a tool directly.
_UV: Final[str] = "uv"
_UV_TOOL_SUBCOMMAND: Final[str] = "tool"
_UVX: Final[str] = "uvx"

#: How deep ``bash -c '...'`` is followed. Deeper nesting is not a way anyone
#: runs a test suite by accident.
_MAX_NESTING: Final[int] = 3

_LONG_FLAG_PREFIX: Final[str] = "--"
_FLAG_VALUE_SEPARATOR: Final[str] = "="
_CURRENT_DIR: Final[str] = "."
_CURRENT_DIR_PREFIX: Final[str] = "./"
_PATH_SEPARATOR: Final[str] = "/"
_NODE_ID_SEPARATOR: Final[str] = "::"
_PYTHON_SUFFIX: Final[str] = ".py"

#: ``$PWD/tests`` and ``${PWD}/tests`` are ``./tests``.
_CWD_VARIABLE_PREFIXES: Final[tuple[str, ...]] = ("$PWD/", "${PWD}/")
_CWD_VARIABLES: Final[frozenset[str]] = frozenset({"$PWD", "${PWD}"})

#: The first redirection character inside a word: ``all>out.txt`` is the
#: operand ``all`` and a redirect, because shlex does not split at ``>``.
_ATTACHED_REDIRECT_START: Final[re.Pattern[str]] = re.compile(r"[<>]")
#: A redirection operator with its target in the NEXT word.
_BARE_REDIRECT_OPERATOR: Final[re.Pattern[str]] = re.compile(r"^(?:>>?|<<?<?|>&|<&|>\|)$")


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

    if name == _UVX:
        yield from _resolve(rest[_skip_flags(rest, _UV_RUN_VALUE_FLAGS, 0) :], segment, depth)
        return

    runner = _PROJECT_RUNNERS.get(name)
    if runner is not None:
        yield from _resolve_runner(name, runner, rest, segment, depth)
        return

    if _PYTHON_INTERPRETER.match(name):
        yield from _resolve_python(rest, segment)
        return

    if name in _SHELL_INTERPRETERS:
        yield from _resolve_shell(rest, segment, depth)
        return

    yield name, rest, segment


def _skip_flags(words: Sequence[str], value_flags: frozenset[str], start: int) -> int:
    """The index of the first word from ``start`` that is not a flag or a flag's value.

    A ``--`` ends the flags and is consumed; a ``--flag=value`` carries its
    value with it.
    """
    index = start
    while index < len(words):
        word = words[index]
        if word == END_OF_OPTIONS:
            return index + 1
        if not word.startswith(FLAG_PREFIX) or word == LONE_DASH:
            return index
        index += 2 if word in value_flags else 1
    return index


def _resolve_runner(
    name: str, runner: _Runner, rest: list[str], segment: str, depth: int
) -> Iterator[tuple[str, list[str], str]]:
    """``uv [flags] run [flags] [--] cmd`` and its siblings run ``cmd``."""
    index = _skip_flags(rest, runner.global_value_flags, 0)
    if index >= len(rest):
        return
    if rest[index] == _RUNNER_SUBCOMMAND:
        start = _skip_flags(rest, runner.run_value_flags, index + 1)
        yield from _resolve(rest[start:], segment, depth)
        return
    if (
        name == _UV
        and rest[index] == _UV_TOOL_SUBCOMMAND
        and index + 1 < len(rest)
        and rest[index + 1] == _RUNNER_SUBCOMMAND
    ):
        start = _skip_flags(rest, _UV_RUN_VALUE_FLAGS, index + 2)
        yield from _resolve(rest[start:], segment, depth)


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
        if argument.startswith(FLAG_PREFIX):
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
        if argument.startswith(FLAG_PREFIX) and not argument.startswith(_LONG_FLAG_PREFIX):
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
    """Spell a path operand one way: ``./tests/``, ``$PWD/tests`` and ``tests`` are one run."""
    if value in _CWD_VARIABLES:
        return _CURRENT_DIR
    for prefix in _CWD_VARIABLE_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    if value.startswith(_PATH_SEPARATOR):
        return value.rstrip(_PATH_SEPARATOR) or _PATH_SEPARATOR
    normalised = value
    while normalised.startswith(_CURRENT_DIR_PREFIX):
        normalised = normalised[len(_CURRENT_DIR_PREFIX) :]
    return normalised.rstrip(_PATH_SEPARATOR) or _CURRENT_DIR


def _is_path_like(operand: str, cwd: Path | None) -> bool:
    """Whether a non-flag word names what to test, rather than being a flag's value.

    A word after an undeclared flag is that flag's value far more often than
    a path (``--timeout 60``, ``--log-level DEBUG``). So only a word shaped
    like a path, or naming something that exists under ``cwd``, targets the
    run. Everything else is ignored, which judges the run by its real paths.
    """
    if _PATH_SEPARATOR in operand or _NODE_ID_SEPARATOR in operand:
        return True
    if operand.endswith(_PYTHON_SUFFIX):
        return True
    if cwd is None:
        return False
    try:
        return (cwd / operand).exists()
    except (OSError, ValueError):
        # Unrepresentable as a path (an embedded NUL, an over-long name): it
        # names nothing on disk, so it cannot be what the run targets.
        return False


def _split_attached_redirect(argument: str) -> tuple[str, bool]:
    """``all>out.txt`` is the word ``all`` and a redirect; shlex does not split at ``>``.

    Returns:
        ``(word, target_follows)``: the word before the redirect, and whether
        the redirect's target is the NEXT word (``all>`` then ``out.txt``).
    """
    found = _ATTACHED_REDIRECT_START.search(argument)
    if found is None or found.start() == 0:
        return argument, False
    return argument[: found.start()], bool(_BARE_REDIRECT_OPERATOR.match(argument[found.start() :]))


def _operand_is_full(operand: str, full_args: frozenset[str]) -> bool:
    """An operand names a full run directly, or as an absolute path ending in one."""
    if operand in full_args:
        return True
    if not operand.startswith(_PATH_SEPARATOR):
        return False
    return any(
        operand.endswith(_PATH_SEPARATOR + entry) for entry in full_args if entry != _CURRENT_DIR
    )


def _is_full_run(pattern: FullQaPattern, arguments: Sequence[str], cwd: Path | None) -> bool:
    """Whether these arguments make ``pattern.command`` run the whole suite.

    A word naming the whole suite (``full_args``) makes the run full wherever
    it sits. Otherwise the run is targeted only by a PATH-LIKE operand; any
    other word is a flag's value and is ignored (see :func:`_is_path_like`).
    """
    names_full_suite = False
    targets: list[str] = []
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
        if not options_ended and argument == END_OF_OPTIONS:
            options_ended = True
            continue
        if not options_ended and argument.startswith(FLAG_PREFIX) and argument != LONE_DASH:
            if argument.split(_FLAG_VALUE_SEPARATOR, 1)[0] in pattern.read_only_flags:
                return False
            if (
                argument in pattern.value_flags
                and index < len(arguments)
                and not arguments[index].startswith(FLAG_PREFIX)
            ):
                index += 1
            continue
        word, target_follows = _split_attached_redirect(argument)
        if target_follows:
            index += 1
        operand = _normalise_operand(word)
        if pattern.full_args is not None and _operand_is_full(operand, pattern.full_args):
            names_full_suite = True
        elif _is_path_like(operand, cwd):
            targets.append(operand)

    if pattern.full_args is None or names_full_suite:
        return True
    return not targets and pattern.bare_is_full


def find_full_qa_invocation(
    command: str, patterns: Sequence[FullQaPattern], *, cwd: Path | None = None
) -> FullQaMatch | None:
    """The first full-suite run in ``command``, or None.

    Args:
        command: The Bash command as the tool received it (line continuations
            already joined by ``get_bash_command``).
        patterns: The validated declaration.
        cwd: The directory the command runs in, so a bare word naming a
            directory there counts as a path. None judges by shape alone.

    Returns:
        The pattern that matched and the command segment it matched in.
    """
    if not patterns:
        return None
    for program, arguments, segment in _invocations(command):
        for pattern in patterns:
            if pattern.command == program and _is_full_run(pattern, arguments, cwd):
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

#: The hook payload field naming the directory the command runs in.
_CWD_FIELD: Final[str] = "cwd"

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
            read_only_flags?, value_flags?, option_grammar?}``. Default empty,
            which is inert.
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
        cwd = hook_input.get(_CWD_FIELD)
        return find_full_qa_invocation(
            command,
            self._patterns(),
            cwd=Path(cwd) if isinstance(cwd, str) and cwd else None,
        )

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
        if self.scope is not HandlerScope.SUB:
            lines.append(
                f"subagent_full_qa_blocker runs with scope {self.scope.value}, but it must be "
                f"{HandlerScope.SUB.value}: any other scope denies the coordinator's own full "
                "QA gate, and then nobody can run it. Remove the `scope:` override."
            )
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
            "thread is never affected. Enforcement is proven for Agent-tool sub-agents and "
            "in-process teammates; a Workflow-tool agent is unmeasured, so follow the "
            "split there whether or not a deny arrives.\n\n"
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
            "read_only_flags?, value_flags?, option_grammar?}`, where `command` is the "
            "program's basename and `full_args` are the operands that make it run the "
            "whole suite (omit it and every run is full). Any other operand narrows the "
            "run only if it is path-like; `option_grammar: pytest` supplies pytest's "
            "value-taking options so a flag's value is never read as a path. Ships off "
            "with no patterns; enabled with none, `hooks-daemon check` reports it as "
            "unable to fire. Keep `scope` at SUB: any other scope denies the "
            "coordinator's own run."
        )
