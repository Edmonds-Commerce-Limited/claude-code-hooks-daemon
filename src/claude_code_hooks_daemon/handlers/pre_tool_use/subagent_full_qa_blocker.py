"""SubagentFullQaBlockerHandler - a sub-agent does not start a full QA run.

Plan 00463. When the owner asked for this, five full-suite runs were executing
at once, one per worktree. Each took 15-20 minutes on an eight-core host. Each
agent then re-ran the suite after every fix round, and the coordinator ran it
again before merging. The full gate stays BEFORE the main branch moves,
because cross-cutting checks break from changes far away and a first full run
on the main branch would land every such break there. It moves to the
coordinator, which batches it: every ready branch merged into one integration
worktree, and one run on the combined head, rather than one run per branch or
per fix round.

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
launchers (``setsid``, ``flock``, ``parallel``), interpreters (``python3 x.py``, ``python -m pytest``, ``bash -c '...'``) and
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

This is a resource guard for cooperating agents, not a security boundary, and
it FAILS CLOSED on what it cannot see (review 5). A command that cannot be
parsed, is too long to parse, or nests past the depth followed is denied when
it names a declared program. A program named by a variable or a substitution
is judged as each program the command names; an operand built at run time may
be the suite, so it is judged as one; Python that imports a module by a
computed name is judged as pytest. Each such deny says why. Code a shell or
Python reads from a file on stdin is read (up to a size cap); a script RUN by
its own name is judged by that name, which is why a project declares its
full-suite scripts.
"""

from __future__ import annotations

import logging
import posixpath
import re
import shlex
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import islice, pairwise
from pathlib import Path, PurePosixPath
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

#: Every pytest option that takes NO value, from the same sources. With the
#: value options it completes the grammar, so a flag in neither is a plugin's
#: the grammar does not know. ``test_subagent_full_qa_blocker`` pins it too.
PYTEST_FLAG_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        # pytest core
        "-h",
        "-l",
        "-q",
        "-s",
        "-v",
        "-x",
        "-V",
        "--cache-clear",
        "--co",
        "--collect-in-virtualenv",
        "--collect-only",
        "--collectonly",
        "--continue-on-collection-errors",
        "--disable-plugin-autoload",
        "--disable-pytest-warnings",
        "--disable-warnings",
        "--doctest-continue-on-failure",
        "--doctest-ignore-import-errors",
        "--doctest-modules",
        "--exitfirst",
        "--failed-first",
        "--ff",
        "--fixtures",
        "--fixtures-per-test",
        "--force-short-summary",
        "--full-trace",
        "--fulltrace",
        "--funcargs",
        "--help",
        "--keep-duplicates",
        "--keepduplicates",
        "--last-failed",
        "--lf",
        "--markers",
        "--new-first",
        "--nf",
        "--no-fold-skipped",
        "--no-header",
        "--no-showlocals",
        "--no-summary",
        "--noconftest",
        "--pdb",
        "--pyargs",
        "--quiet",
        "--runxfail",
        "--setup-only",
        "--setup-plan",
        "--setup-show",
        "--setuponly",
        "--setupplan",
        "--setupshow",
        "--showlocals",
        "--stepwise",
        "--stepwise-reset",
        "--stepwise-skip",
        "--strict",
        "--strict-config",
        "--strict-markers",
        "--sw",
        "--sw-reset",
        "--sw-skip",
        "--trace",
        "--trace-config",
        "--traceconfig",
        "--verbose",
        "--version",
        "--xfail-tb",
        # pytest-cov
        "--cov-append",
        "--cov-branch",
        "--cov-reset",
        "--no-cov",
        "--no-cov-on-fail",
        # pytest-xdist, pytest-randomly, pytest-html
        "-f",
        "--looponfail",
        "--randomly-dont-reset-seed",
        "--randomly-dont-reorganize",
        "--self-contained-html",
    }
)


@dataclass(frozen=True, slots=True)
class _OptionGrammar:
    """A program's complete option set: what takes a value, and what does not."""

    value_options: frozenset[str]
    flag_options: frozenset[str]


#: Named grammars a pattern can adopt with ``option_grammar``.
_OPTION_GRAMMARS: Final[Mapping[str, _OptionGrammar]] = {
    "pytest": _OptionGrammar(value_options=PYTEST_VALUE_OPTIONS, flag_options=PYTEST_FLAG_OPTIONS)
}
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
            ``.py``, or exists in the directory the command runs in (the
            event's working directory, moved by any ``cd`` before it).
        bare_is_full: With ``full_args`` set, a run naming no operand at all
            is full too (``pytest`` with no path collects the whole suite).
        read_only_flags: Flags that make the run a read rather than a run
            (``--read-only``, ``--collect-only``).
        value_flags: Flags whose next word is their value, so that word is not
            mistaken for an operand (``pytest -k expr``). A declared
            ``option_grammar`` is merged in here.
        flag_options: With an ``option_grammar``, the options that take no
            value. A flag in neither set is then a plugin's the grammar does
            not know, and it is read as taking a value (fail closed). None
            without a grammar: an undeclared flag then takes no value.
    """

    pattern_id: str
    command: str
    full_args: frozenset[str] | None
    bare_is_full: bool
    read_only_flags: frozenset[str]
    value_flags: frozenset[str]
    flag_options: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class FullQaMatch:
    """The first full-suite invocation found in a command.

    ``fail_closed`` says why a run that could not be SEEN was judged as the
    full run it may be: a command that could not be parsed, one too long to
    parse, or one whose program or operands are only built at run time. It is
    empty for a run that was read in full.
    """

    pattern_id: str
    segment: str
    fail_closed: str = ""


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
    grammar: _OptionGrammar | None = None
    if grammar_name is not None:
        if grammar_name not in _OPTION_GRAMMARS:
            known = ", ".join(sorted(_OPTION_GRAMMARS))
            return None, f"entry {position}: `{_KEY_OPTION_GRAMMAR}` must be one of: {known}"
        grammar = _OPTION_GRAMMARS[grammar_name]

    full_args = word_lists[_KEY_FULL_ARGS]
    declared_value_flags = word_lists[_KEY_VALUE_FLAGS] or frozenset()
    return (
        FullQaPattern(
            pattern_id=str(entry[_KEY_ID]).strip(),
            command=command_word(str(entry[_KEY_COMMAND]).strip()),
            full_args=(
                None if full_args is None else frozenset(_normalise_operand(a) for a in full_args)
            ),
            bare_is_full=bare_is_full,
            read_only_flags=word_lists[_KEY_READ_ONLY_FLAGS] or frozenset(),
            value_flags=declared_value_flags | (grammar.value_options if grammar else frozenset()),
            flag_options=grammar.flag_options if grammar else None,
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
    {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "builtin"}
)
#: ``function t { ...; }`` defines ``t``: the keyword and the name precede the body.
_FUNCTION: Final[str] = "function"
_FUNCTION_HEADER_WORDS: Final[int] = 2

#: Builtins that set a variable rather than run a command (``export P=pytest``).
_DECLARATIONS: Final[frozenset[str]] = frozenset(
    {"export", "declare", "local", "readonly", "typeset"}
)
#: ``for NAME in a b; do ... $NAME ...; done`` gives ``$NAME`` each word in turn.
_FOR: Final[str] = "for"
_FOR_IN: Final[str] = "in"
_FOR_HEADER_WORDS: Final[int] = 3
#: ``$NAME`` and ``${NAME}``: a variable, expanded when the command sets it.
_VARIABLE: Final[re.Pattern[str]] = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
_VALUE_SEPARATOR: Final[str] = "="
#: Characters that stop a list of values being written as one brace group.
_BRACE_UNSAFE: Final[re.Pattern[str]] = re.compile(r"[{},\s]")

#: What a word the shell only builds at run time starts with.
_RUN_TIME_PREFIXES: Final[tuple[str, ...]] = ("$", "`")
_SUBSTITUTION_OPENER: Final[str] = "$("
_ARITHMETIC_OPENER: Final[str] = "$(("
_BACKTICK: Final[str] = "`"
#: Characters that mean a path's last part is itself still to be built.
_UNBUILT_CHARACTERS: Final[frozenset[str]] = frozenset("$`()")
#: An unquoted substitution is replaced by this while the command is split,
#: so ``$(which pytest) tests`` stays one command word and one operand.
_PLACEHOLDER_OPEN: Final[str] = ""
_PLACEHOLDER_CLOSE: Final[str] = ""
_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(f"{_PLACEHOLDER_OPEN}(\\d+){_PLACEHOLDER_CLOSE}")

#: ``git diff --name-only`` (and ``show``/``log``) lists the files a change
#: touches. Such a list, filtered or not, is a targeted run's operands.
_GIT: Final[str] = "git"
_GIT_LISTING_SUBCOMMANDS: Final[frozenset[str]] = frozenset({"diff", "show", "log"})
_GIT_NAME_ONLY: Final[str] = "--name-only"
_LIST_FILTERS: Final[frozenset[str]] = frozenset({"grep", "sort", "uniq"})
#: The operand standing for the files such a list names. Private-use
#: characters, not ``<...>``, which would read as a redirection.
_CHANGED_FILES: Final[str] = "the files a git listing names"

#: ``env -C DIR`` and ``env --chdir=DIR`` run the command in DIR.
_ENV: Final[str] = "env"
_ENV_SHORT_CHDIR: Final[str] = "-C"
_ENV_CHDIR_FLAGS: Final[frozenset[str]] = frozenset({_ENV_SHORT_CHDIR, "--chdir"})

#: ``command -v x`` and ``command -V x`` look ``x`` up without running it.
_COMMAND: Final[str] = "command"
_COMMAND_LOOKUP_FLAGS: Final[frozenset[str]] = frozenset({"-v", "-V"})

#: ``eval`` runs its joined arguments as shell code.
_EVAL: Final[str] = "eval"
#: ``source x`` and ``. x`` run the script ``x`` in this shell.
_SOURCE_COMMANDS: Final[frozenset[str]] = frozenset({"source", "."})
#: ``xargs [options] cmd args`` runs ``cmd`` with ``args`` plus words from
#: stdin, which cannot be seen: the explicit arguments are judged alone.
_XARGS: Final[str] = "xargs"
_XARGS_VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "-a",
        "-d",
        "-E",
        "-I",
        "-L",
        "-n",
        "-P",
        "-s",
        "--arg-file",
        "--delimiter",
        "--eof",
        "--max-args",
        "--max-chars",
        "--max-lines",
        "--max-procs",
        "--replace",
    }
)
#: ``bash <<< 'code'`` reads code from a here-string.
_HERE_STRING: Final[str] = "<<<"
#: Producers whose output is exactly their literal arguments, so code piped
#: from them into a shell can be read here.
_LITERAL_PRODUCERS: Final[frozenset[str]] = frozenset({"echo", "printf"})
_ECHO_OPTIONS: Final[frozenset[str]] = frozenset({"-n", "-e", "-E"})
_ESCAPED_NEWLINE: Final[str] = "\\n"
#: Where one pipeline ends; a pipe ``|`` then separates its stages.
_PIPELINE_BOUNDARIES: Final[tuple[str, ...]] = ("&&", "||", ";", "\n")
_PIPE: Final[tuple[str, ...]] = ("|",)
#: ``bash < <(producer)``: a process substitution feeding a shell's stdin.
_STDIN_PROCESS_SUBSTITUTION: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w.-])(?P<shell>bash|sh|zsh|dash|ksh)\b[^|;&\n()]*<\s*<\("
)

#: Characters the shell expands a word with, from the filesystem.
_GLOB_CHARACTERS: Final[re.Pattern[str]] = re.compile(r"[*?\[]")
_ANY_DEPTH: Final[str] = "**"
_BRACE_OPEN: Final[str] = "{"
_BRACE_CLOSE: Final[str] = "}"
_BRACE_SEPARATOR: Final[str] = ","
#: More alternatives than this is not how anyone names test paths; a word
#: past either limit is judged as the whole suite.
_MAX_BRACE_ALTERNATIVES: Final[int] = 64
_MAX_BRACE_GROUPS: Final[int] = 32

#: What marks the root of the repository an operand lies in.
_REPOSITORY_MARKERS: Final[tuple[str, ...]] = (".git", "pyproject.toml")

#: What ``_invocations`` yields for a command it could not split into words.
_UNPARSED: Final[str] = "<unparsed>"
#: What it yields for a command word the shell only builds at run time; the
#: first argument is that word, the rest are the command's arguments.
_OPAQUE: Final[str] = "<built at run time>"
#: What it yields for code an interpreter reads from a FILE on stdin; the
#: arguments are the interpreter kind, the path and the code's own argv.
_CODE_FILE: Final[str] = "<code read from a file>"
_SHELL_CODE: Final[str] = "shell"
_PYTHON_CODE: Final[str] = "python"
#: ``env -C DIR cmd``: DIR is the directory for ``cmd`` alone.
_CD_PUSH: Final[str] = "<enter a directory for one command>"
_CD_POP: Final[str] = "<leave that directory>"

#: Why a match was judged without being seen, as the deny states it.
_UNPARSED_REASON: Final[str] = (
    "this command could not be parsed (an unbalanced quote, or nesting deeper than is "
    "followed), and it names a full-suite program, so it is judged as the full run it may be. "
    "Quote it plainly, or split it into simpler commands."
)
_OPAQUE_REASON: Final[str] = (
    "part of this command is only built at run time (a program named by a variable or a "
    "substitution, or a module imported by a computed name), and the run it makes may be the "
    "whole suite, so it is judged as one. Spell the program and its test paths out literally."
)
_OVERSIZED_REASON: Final[str] = (
    "this command is too long to parse, and it names a full-suite program, so it is judged "
    "as the full run it may be. Split it into smaller commands."
)

#: Past this many characters a command is not parsed (review 5 n5): shlex
#: builds each token a character at a time, and a 1 MB word took 36 s. The
#: cap is on the raw text, because blanking a heredoc body is itself
#: quadratic in the number of unclosed openers.
_MAX_COMMAND_LENGTH: Final[int] = 32 * 1024
#: A file of code fed to an interpreter is read only up to this size.
_MAX_CODE_FILE_BYTES: Final[int] = 64 * 1024
#: How many launchers, runners and ``python -m`` hops are followed in one
#: command (review 5 n6). Past it the command is judged as unparsed.
_MAX_HOPS: Final[int] = 32
#: How much of an unparsed long command the deny quotes.
_QUOTED_SEGMENT_LENGTH: Final[int] = 200
_ELLIPSIS: Final[str] = "..."

#: ANSI-C quoting (``$'...'``): the escapes bash decodes inside it.
_ANSI_C_OPENER: Final[str] = "$'"
_ANSI_C_ESCAPES: Final[Mapping[str, str]] = {
    "\\": "\\",
    "'": "'",
    '"': '"',
    "?": "?",
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "e": "\x1b",
    "E": "\x1b",
}
#: Numeric ANSI-C escapes: ``\xHH``, ``\uHHHH`` and ``\UHHHHHHHH`` by letter,
#: each with its digits, base and most digits read; ``\NNN`` is octal.
_HEX_DIGITS: Final[str] = "0123456789abcdefABCDEF"
_HEX_BASE: Final[int] = 16
_ANSI_C_NUMERIC: Final[Mapping[str, tuple[str, int, int]]] = {
    "x": (_HEX_DIGITS, _HEX_BASE, 2),
    "u": (_HEX_DIGITS, _HEX_BASE, 4),
    "U": (_HEX_DIGITS, _HEX_BASE, 8),
}
_OCTAL_DIGITS: Final[str] = "01234567"
_OCTAL_BASE: Final[int] = 8
_OCTAL_WIDTH: Final[int] = 3

#: A redirection word. When nothing follows the operator, the target is the
#: next word (``> log``); otherwise it is attached (``2>&1``, ``>log``).
_REDIRECT: Final[re.Pattern[str]] = re.compile(r"^(?:\d*|&)(?:>>?|<<?<?|>&|<&)(?P<target>.*)$")

_PYTHON_INTERPRETER: Final[re.Pattern[str]] = re.compile(r"^python(?:\d+(?:\.\d+)*)?$")
_PYTHON_VALUE_FLAGS: Final[frozenset[str]] = frozenset({"-X", "-W"})
_PYTHON_MODULE_FLAG: Final[str] = "-m"
_PYTHON_CODE_FLAG: Final[str] = "-c"
_PYTEST: Final[str] = "pytest"
#: Python code CALLS pytest (review 5 m1): importing it, or reading its
#: version, runs nothing. The dunder spelling of the import builtin is
#: written ``_{2}import_{2}`` so this module does not read as a use of it.
_PYTEST_CALLS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(rf"\b{_PYTEST}\s*\.\s*(?:main|console_main)\s*\("),
    re.compile(rf"\b(?:_{{2}}import_{{2}}|import_module|run_module)\s*\(\s*(['\"]){_PYTEST}\1"),
)
_PYTEST_MAIN_IMPORT: Final[re.Pattern[str]] = re.compile(
    rf"\bfrom\s+{_PYTEST}\s+import\b[^\n;]*\b(?:main|console_main)\b"
)
_MAIN_CALL: Final[re.Pattern[str]] = re.compile(r"\b(?:main|console_main)\s*\(")
#: Code that imports or runs a module named only at run time, or runs a
#: string: which program it starts cannot be read from the code.
_DYNAMIC_EXECUTION: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(?:_{2}import_{2}|import_module)\s*\((?!\s*(['\"])[\w.]+\1\s*[,)])[^)]*\)\s*\."),
    re.compile(r"\brun_module\s*\((?!\s*(['\"])[\w.]+\1\s*[,)])"),
    re.compile(r"(?<![\w.])(?:[e]xec|[e]val)\s*\((?!\s*(['\"])[^'\"]*\1\s*\))"),
)
#: Code that starts a process: its string literals may be shell commands.
_PROCESS_CALL: Final[re.Pattern[str]] = re.compile(
    r"\b(?:os\s*\.\s*(?:system|popen|exec\w*|spawn\w*)|subprocess\s*\.\s*\w+)\s*\("
)
#: ``sys.argv`` in the code: the words after the code string reach it.
_SYS_ARGV: Final[re.Pattern[str]] = re.compile(r"\bsys\s*\.\s*argv\b")
#: A quoted string in Python code: its content is one word of the run.
_PYTHON_STRING_LITERAL: Final[re.Pattern[str]] = re.compile(r"'([^'\\]*)'|\"([^\"\\]*)\"")

_SHELL_INTERPRETERS: Final[frozenset[str]] = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
#: Cheap pre-check before looking for code fed to an interpreter on stdin.
_INTERPRETER_WORD: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w.-])(?:bash|sh|zsh|dash|ksh|python[\d.]*)(?![\w.-])"
)
#: ``cat FILE | bash``: the producer that passes a file through unchanged.
_CAT: Final[str] = "cat"
#: A redirection of stdin from a file: ``< f``, ``<f``, ``0< f``.
_STDIN_REDIRECT: Final[re.Pattern[str]] = re.compile(r"^0?<(?P<target>[^<&(].*)?$")
#: A heredoc opener; the body runs to a line holding only the delimiter.
_HEREDOC_OPENER: Final[re.Pattern[str]] = re.compile(
    r"(?<!<)<<(?P<strip>-?)[ \t]*(?P<quote>['\"]?)(?P<delim>[^\s'\"<>|&;()]+)(?P=quote)"
)
_TAB: Final[str] = "\t"
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
    "pipx": _Runner(
        global_value_flags=frozenset(),
        run_value_flags=frozenset({"--spec", "--python", "--pip-args", "--index-url"}),
    ),
    "pdm": _Runner(global_value_flags=frozenset({"-p", "--project"}), run_value_flags=frozenset()),
    "hatch": _Runner(global_value_flags=frozenset({"-e", "--env"}), run_value_flags=frozenset()),
    # `coverage run [-m] cmd`: `-m` is a flag here, so the next word is tried
    # both as its value and as the command, which is what it is.
    "coverage": _Runner(
        global_value_flags=frozenset(),
        run_value_flags=frozenset(
            {
                "--rcfile",
                "--source",
                "--omit",
                "--include",
                "--context",
                "--data-file",
                "--concurrency",
                "--debug",
            }
        ),
    ),
}
_RUNNER_SUBCOMMAND: Final[str] = "run"


@dataclass(frozen=True, slots=True)
class _Launcher:
    """A program that runs a command after its own flags and operands.

    ``chrt -f 10 pytest`` runs ``pytest`` after the flag ``-f`` and the
    priority ``10``. ``value_flags`` take the next word as their value,
    ``operands`` counts the positional words before the command, and a
    ``code_flags`` value is shell code the launcher runs (``flock f -c 'cmd'``).
    With ``runs_tail`` unset, only a code flag runs anything (``script out.log``
    starts an interactive shell).
    """

    value_flags: frozenset[str] = frozenset()
    operands: int = 0
    code_flags: frozenset[str] = frozenset()
    runs_tail: bool = True


#: Launchers the shared wrapper table does not peel, each with its own grammar.
_LAUNCHERS: Final[Mapping[str, _Launcher]] = {
    "setsid": _Launcher(),
    "ionice": _Launcher(value_flags=frozenset({"-c", "--class", "-n", "--classdata"})),
    "chrt": _Launcher(
        value_flags=frozenset(
            {"-T", "--sched-runtime", "-P", "--sched-period", "-D", "--sched-deadline"}
        ),
        operands=1,
    ),
    "taskset": _Launcher(operands=1),
    "flock": _Launcher(
        value_flags=frozenset({"-w", "--wait", "--timeout", "-E", "--conflict-exit-code"}),
        operands=1,
        code_flags=frozenset({"-c", "--command"}),
    ),
    "xvfb-run": _Launcher(
        value_flags=frozenset(
            {
                "-n",
                "--server-num",
                "-s",
                "--server-args",
                "-f",
                "--auth-file",
                "-e",
                "--error-file",
                "-p",
                "--xauth-protocol",
                "-w",
                "--wait",
            }
        )
    ),
    "script": _Launcher(
        value_flags=frozenset(
            {"-E", "--echo", "-I", "--log-in", "-O", "--log-out", "-B", "--log-io"}
            | {"-T", "--log-timing", "-m", "--logging-format"}
        ),
        code_flags=frozenset({"-c", "--command"}),
        runs_tail=False,
    ),
    # `/usr/bin/time -v cmd` and the `time -p` keyword alike.
    "time": _Launcher(value_flags=frozenset({"-o", "--output", "-f", "--format"})),
    # `exec -a NAME cmd` runs cmd under the name NAME.
    "exec": _Launcher(value_flags=frozenset({"-a"})),
    "strace": _Launcher(
        value_flags=frozenset(
            {"-a", "-b", "-e", "-E", "-I", "-o", "-O", "-p", "-P", "-s", "-S", "-u", "-U", "-X"}
            | {"--output", "--attach", "--string-limit", "--user", "--env", "--trace-path"}
        )
    ),
    "ltrace": _Launcher(
        value_flags=frozenset(
            {"-a", "-A", "-D", "-e", "-F", "-l", "-n", "-o", "-p", "-s", "-u", "-w", "-x"}
            | {"--output", "--library", "--indent", "--align"}
        )
    ),
    "caffeinate": _Launcher(value_flags=frozenset({"-t", "-w"})),
    "doas": _Launcher(value_flags=frozenset({"-u", "-C"})),
}
#: ``parallel [options] cmd ::: a b`` runs ``cmd a`` and ``cmd b``; the words
#: after ``::::`` are files the arguments are read from, which cannot be seen.
_PARALLEL: Final[str] = "parallel"
_PARALLEL_LITERAL_SEPARATORS: Final[frozenset[str]] = frozenset({":::", ":::+"})
_PARALLEL_ARGUMENT_SEPARATORS: Final[frozenset[str]] = _PARALLEL_LITERAL_SEPARATORS | frozenset(
    {"::::", "::::+"}
)
_PARALLEL_VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "-j",
        "--jobs",
        "-N",
        "-n",
        "--max-args",
        "-S",
        "--sshlogin",
        "--joblog",
        "--results",
        "--tmpdir",
        "-I",
        "--delay",
        "--timeout",
        "--retries",
        "--halt",
        "-a",
        "--arg-file",
        "-d",
        "--delimiter",
        "--colsep",
    }
)
#: Programs installed under a second name: `py.test` is pytest's older name.
_PROGRAM_ALIASES: Final[Mapping[str, str]] = {"py.test": "pytest"}
#: ``uv tool run`` and its alias ``uvx`` run a tool directly.
_UV: Final[str] = "uv"
_UV_TOOL_SUBCOMMAND: Final[str] = "tool"
_UVX: Final[str] = "uvx"
#: ``uvx pytest@8`` runs ``pytest``, pinned to version 8.
_VERSION_PIN: Final[str] = "@"
#: ``hatch run env:command`` runs ``command`` in ``env``.
_HATCH: Final[str] = "hatch"
_HATCH_ENV_SEPARATOR: Final[str] = ":"
#: ``hatch test [options] [args]`` runs pytest with ``args``; these are its own.
_HATCH_TEST_SUBCOMMAND: Final[str] = "test"
_HATCH_TEST_VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {"-py", "--python", "-i", "--include", "-x", "--exclude"}
)
_HATCH_TEST_FLAGS: Final[frozenset[str]] = frozenset(
    {"-r", "--randomize", "-d", "--dist", "-p", "--parallel", "-c", "--cover"}
    | {"--cover-quiet", "-a", "--all", "-s", "--show"}
)

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

#: ``$PWD/tests``, ``${PWD}/tests`` and ``$(pwd)/tests`` are ``./tests``.
_CWD_VARIABLE_PREFIXES: Final[tuple[str, ...]] = ("$PWD/", "${PWD}/", "$(pwd)/", "`pwd`/")
_CWD_VARIABLES: Final[frozenset[str]] = frozenset({"$PWD", "${PWD}", "$(pwd)", "`pwd`"})
#: A path from the home directory is absolute: it does not depend on the cwd.
_HOME_PREFIXES: Final[tuple[str, ...]] = ("~/", "$HOME/", "${HOME}/")
#: ``cd`` moves the directory later words are looked up in; a target that
#: starts with an expansion goes somewhere this cannot see.
_CD: Final[str] = "cd"
#: A path operand that lands above where the command started runs all of it.
_ABOVE_START: Final[str] = "<above the starting directory>"
_UNSEEN_CD_PREFIXES: Final[tuple[str, ...]] = ("$", "~", "`")
#: ``-n`` of ``-n8``: a short option is a dash and one letter.
_SHORT_OPTION: Final[int] = 2

#: The first redirection inside a word: ``all>out.txt`` and ``all&>out.txt``
#: are the operand ``all`` and a redirect, because shlex splits at neither.
_ATTACHED_REDIRECT_START: Final[re.Pattern[str]] = re.compile(r"&?[<>]")
#: A redirection operator with its target in the NEXT word.
_BARE_REDIRECT_OPERATOR: Final[re.Pattern[str]] = re.compile(r"^(?:&?>>?|<<?<?|>&|<&|>\|)$")


def _ansi_c_to_single_quoted(text: str) -> str:
    """Rewrite each ``$'...'`` as the plain single-quoted word bash makes of it.

    Inside ANSI-C quoting ``\\'`` is an escaped quote, while every other
    splitter here reads it as the quote closing, which hid the rest of the
    command inside one quoted word (review 4 N5).
    """
    out: list[str] = []
    index = 0
    in_single = in_double = False
    while index < len(text):
        char = text[index]
        if char == "\\" and not in_single:
            out.append(text[index : index + 2])
            index += 2
            continue
        if not in_single and not in_double and text.startswith(_ANSI_C_OPENER, index):
            decoded, index = _decode_ansi_c(text, index + len(_ANSI_C_OPENER))
            out.append("'" + decoded.replace("'", "'\\''") + "'")
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        out.append(char)
        index += 1
    return "".join(out)


def _decode_ansi_c(text: str, index: int) -> tuple[str, int]:
    """Decode an ANSI-C body from ``index``; return it and the index after its quote."""
    decoded: list[str] = []
    while index < len(text):
        char = text[index]
        if char == "'":
            return "".join(decoded), index + 1
        if char == "\\" and index + 1 < len(text):
            numeric = _ansi_c_number(text, index + 1)
            if numeric is not None:
                value, index = numeric
                decoded.append(value)
                continue
            escaped = text[index + 1]
            decoded.append(_ANSI_C_ESCAPES.get(escaped, "\\" + escaped))
            index += 2
            continue
        decoded.append(char)
        index += 1
    return "".join(decoded), index


def _ansi_c_number(text: str, at: int) -> tuple[str, int] | None:
    """Decode a numeric escape whose letter or first digit is at ``at``.

    ``$'py\\x74est'`` and ``$'py\\164est'`` are both ``pytest`` (review 5 n4).
    Returns the character and the index after the digits, or None when no
    digits follow or the value is no character.
    """
    letter = text[at]
    if letter in _ANSI_C_NUMERIC:
        digits, base, width = _ANSI_C_NUMERIC[letter]
        start = at + 1
    elif letter in _OCTAL_DIGITS:
        digits, base, width, start = _OCTAL_DIGITS, _OCTAL_BASE, _OCTAL_WIDTH, at
    else:
        return None
    end = start
    while end < len(text) and end - start < width and text[end] in digits:
        end += 1
    if end == start:
        return None
    value = int(text[start:end], base)
    if value > sys.maxunicode:
        return None
    return chr(value), end


def _closing_paren(text: str, index: int) -> int:
    """The index of the ``)`` closing a ``(`` opened just before ``index``, or len(text)."""
    depth = 1
    in_single = in_double = False
    while index < len(text):
        char = text[index]
        if char == "\\" and not in_single:
            index += 2
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index
        index += 1
    return len(text)


def _double_quoted_substitutions(text: str) -> list[str]:
    """The code of every ``$(...)`` and backtick substitution inside double quotes.

    Bash runs them: ``x="$(pytest tests)"`` runs pytest (review 4 N4). One
    outside quotes is already a command boundary; one inside single quotes is
    text. An unclosed one runs to the end, so it is judged rather than lost.
    """
    found: list[str] = []
    index = 0
    in_single = in_double = False
    while index < len(text):
        char = text[index]
        if char == "\\" and not in_single:
            index += 2
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif in_double and text.startswith("$(", index) and not text.startswith("$((", index):
            end = _closing_paren(text, index + 2)
            found.append(text[index + 2 : end])
            index = end + 1
            continue
        elif in_double and char == "`":
            end = text.find("`", index + 1)
            end = len(text) if end == -1 else end
            found.append(text[index + 1 : end])
            index = end + 1
            continue
        index += 1
    return found


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
    text = _ansi_c_to_single_quoted(normalise_line_continuations(command))
    scan_target = strip_inert_spans(text)
    protected, substitutions = _protect_substitutions(scan_target)
    nested = _double_quoted_substitutions(scan_target) + [
        _substitution_code(original) for original in substitutions
    ]
    for code in nested:
        yield from _nested(code, code, depth)
    if _INTERPRETER_WORD.search(scan_target) is not None:
        yield from _code_on_stdin(scan_target, depth)
    fed_a_listing = _consumers_of_a_listing(protected)
    parsed: list[tuple[str, list[str] | None]] = []
    for segment in split_unquoted(protected, _COMMAND_BOUNDARIES):
        restored = _restore(segment, substitutions)
        try:
            words = [_restore(word, substitutions) for word in shlex.split(segment)]
        except ValueError:
            # An unbalanced quote: judged as unparsed, never guessed at.
            parsed.append((restored, None))
            continue
        if segment.strip() in fed_a_listing:
            words.append(_CHANGED_FILES)
        parsed.append((restored, words))
    variables = _variables(split for _, split in parsed if split)
    for segment, split in parsed:
        if split is None:
            yield _UNPARSED, [], segment
            continue
        for background in _split_background(_expand_variables(split, variables)):
            yield from _resolve(background, segment, depth)


def _nested(code: str, segment: str, depth: int) -> Iterator[tuple[str, list[str], str]]:
    """The invocations of code the shell runs one level down, or unparsed past the depth."""
    if depth < _MAX_NESTING:
        yield from _invocations(code, depth + 1)
    else:
        yield _UNPARSED, [], segment


def _protect_substitutions(text: str) -> tuple[str, list[str]]:
    """Replace each unquoted ``$(...)`` and backtick span with a placeholder.

    Parentheses and backticks split commands, so ``$(which pytest) tests``
    fell apart into ``$``, ``which pytest`` and ``tests``: the command word
    was lost. A placeholder keeps the span one word while the command is
    split, and :func:`_restore` puts the original back into that word.

    Returns:
        The text with placeholders, and the originals in placeholder order.
    """
    out: list[str] = []
    originals: list[str] = []
    index = 0
    in_single = in_double = False
    while index < len(text):
        char = text[index]
        if char == "\\" and not in_single:
            out.append(text[index : index + 2])
            index += 2
            continue
        end = -1
        if not in_single and not in_double:
            if text.startswith(_SUBSTITUTION_OPENER, index) and not text.startswith(
                _ARITHMETIC_OPENER, index
            ):
                end = _closing_paren(text, index + len(_SUBSTITUTION_OPENER))
            elif char == _BACKTICK:
                end = text.find(_BACKTICK, index + 1)
        if end != -1:
            originals.append(text[index : end + 1])
            out.append(f"{_PLACEHOLDER_OPEN}{len(originals) - 1}{_PLACEHOLDER_CLOSE}")
            index = end + 1
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        out.append(char)
        index += 1
    return "".join(out), originals


def _restore(text: str, originals: Sequence[str]) -> str:
    """Put each substitution :func:`_protect_substitutions` replaced back."""
    return _PLACEHOLDER.sub(lambda found: originals[int(found.group(1))], text)


def _substitution_code(word: str) -> str:
    """The code inside a ``$(...)`` or backtick substitution word."""
    if word.startswith(_SUBSTITUTION_OPENER):
        return word[len(_SUBSTITUTION_OPENER) :].removesuffix(")")
    return word.strip(_BACKTICK)


def _variables(word_lists: Iterable[list[str]]) -> dict[str, list[str]]:
    """The values each variable the command sets can take.

    ``P=pytest`` and ``export P=pytest`` give one value; ``for t in a b``
    gives each word in turn (review 5 n4). Only a command that consists of
    assignments sets a variable: ``FOO=1 pytest`` sets FOO for pytest alone.
    """
    found: dict[str, list[str]] = {}
    for words in word_lists:
        if len(words) >= _FOR_HEADER_WORDS and words[0] == _FOR and words[2] == _FOR_IN:
            found[words[1]] = words[_FOR_HEADER_WORDS:]
            continue
        body = [w for w in words[1:] if not _is_flag(w)] if words[0] in _DECLARATIONS else words
        if body and all(_ASSIGNMENT.match(word) for word in body):
            for word in body:
                name, _, value = word.partition(_VALUE_SEPARATOR)
                found[name] = [value]
    return found


def _expand_variables(words: list[str], variables: Mapping[str, list[str]]) -> list[str]:
    """Each word with the variables the command sets expanded.

    A whole-word ``$P`` is split as bash splits an unquoted expansion; one
    with several values becomes a brace group, so each value is judged. A
    variable the command does not set is left as written.
    """
    expanded: list[str] = []
    for word in words:
        whole = _VARIABLE.fullmatch(word)
        values = variables.get(whole.group(1) or whole.group(2)) if whole else None
        if values is None:
            expanded.append(_VARIABLE.sub(lambda found: _single_value(found, variables), word))
        elif len(values) == 1:
            value = values[0]
            built = value.startswith(_RUN_TIME_PREFIXES)
            expanded.extend([value] if built else value.split())
        elif not any(_BRACE_UNSAFE.search(value) for value in values):
            expanded.append(_BRACE_OPEN + _BRACE_SEPARATOR.join(values) + _BRACE_CLOSE)
        else:
            expanded.append(word)
    return expanded


def _single_value(found: re.Match[str], variables: Mapping[str, list[str]]) -> str:
    """The one value of a variable inside a word, or the variable as written."""
    values = variables.get(found.group(1) or found.group(2))
    return values[0] if values is not None and len(values) == 1 else found.group(0)


def _literal_output(words: list[str]) -> str | None:
    """What ``echo``/``printf`` prints, when it is exactly its arguments; else None."""
    argv = _strip_prefixes(words)
    if not argv or command_word(argv[0]) not in _LITERAL_PRODUCERS:
        return None
    rest = argv[1:]
    while rest and rest[0] in _ECHO_OPTIONS:
        rest = rest[1:]
    return " ".join(rest).replace(_ESCAPED_NEWLINE, "\n")


def _reads_code_from_stdin(words: list[str]) -> bool:
    """Whether this runs a shell that takes its code from stdin (no script, no ``-c``)."""
    argv = _strip_prefixes(words)
    if not argv or command_word(argv[0]) not in _SHELL_INTERPRETERS:
        return False
    rest = argv[1:]
    index = 0
    while index < len(rest):
        argument = rest[index]
        redirect = _REDIRECT.match(argument)
        if redirect is not None:
            index += 1 if redirect.group("target") else 2
            continue
        if argument in _SHELL_VALUE_FLAGS:
            index += 2
            continue
        if not _is_flag(argument):
            return False
        if not argument.startswith(_LONG_FLAG_PREFIX) and _SHELL_CODE_LETTER in argument[1:]:
            return False
        index += 1
    return True


def _is_a_listing(stages: Sequence[str]) -> bool:
    """Whether a pipeline writes the files a change touches (review 5 n3).

    ``git diff --name-only`` (or ``show``/``log``), optionally filtered by
    ``grep``, ``sort`` or ``uniq``: its output is a set of changed files,
    which is the targeted run the guidance asks for.
    """
    try:
        words = [shlex.split(stage) for stage in stages]
    except ValueError as error:
        logger.debug("Listing not recognised, unsplittable (%s)", error)
        return False
    if not words or not all(words):
        return False
    first = _strip_prefixes(words[0])
    subcommands = [word for word in first[1:] if not _is_flag(word)]
    return (
        bool(first)
        and command_word(first[0]) == _GIT
        and bool(subcommands)
        and subcommands[0] in _GIT_LISTING_SUBCOMMANDS
        and _GIT_NAME_ONLY in first
        and all(command_word(stage[0]) in _LIST_FILTERS for stage in words[1:])
    )


def _lists_changed_files(word: str) -> bool:
    """Whether a substitution operand is a listing of changed files."""
    return _is_a_listing(split_unquoted(_substitution_code(word), _PIPE))


def _consumers_of_a_listing(text: str) -> frozenset[str]:
    """Each ``xargs`` stage whose stdin is a listing of changed files, as written."""
    consumers: set[str] = set()
    for pipeline in split_unquoted(text, _PIPELINE_BOUNDARIES):
        stages = split_unquoted(pipeline, _PIPE)
        for position in range(1, len(stages)):
            try:
                consumer = _strip_prefixes(shlex.split(stages[position]))
            except ValueError as error:
                logger.debug("Consumer left to the unparsed check (%s)", error)
                continue
            if consumer and consumer[0] == _XARGS and _is_a_listing(stages[:position]):
                consumers.add(stages[position].strip())
    return frozenset(consumers)


def _python_stdin_argv(words: list[str]) -> list[str] | None:
    """The argv of Python code read from stdin (no script, ``-c`` or ``-m``), else None.

    ``python3 - a b`` reads code from stdin with ``sys.argv[1:]`` of
    ``['a', 'b']``; ``python3 script.py`` reads DATA from stdin.
    """
    argv = _strip_prefixes(words)
    if not argv or _PYTHON_INTERPRETER.match(command_word(argv[0])) is None:
        return None
    rest = argv[1:]
    index = 0
    while index < len(rest):
        argument = rest[index]
        redirect = _REDIRECT.match(argument)
        if redirect is not None:
            index += 1 if redirect.group("target") else 2
            continue
        if argument == LONE_DASH:
            return [word for word in rest[index + 1 :] if _REDIRECT.match(word) is None]
        if argument in _PYTHON_VALUE_FLAGS:
            index += 2
            continue
        if not _is_flag(argument) or argument.startswith((_PYTHON_MODULE_FLAG, _PYTHON_CODE_FLAG)):
            return None
        index += 1
    return []


def _producer_output(words: list[str]) -> tuple[str | None, str | None]:
    """What a pipe producer writes: ``(literal text, None)``, ``(None, file)`` or neither.

    ``echo``/``printf`` write their arguments; ``cat FILE`` writes one file.
    """
    printed = _literal_output(words)
    if printed is not None:
        return printed, None
    argv = _strip_prefixes(words)
    operands = [word for word in argv[1:] if not _is_flag(word)]
    if argv and command_word(argv[0]) == _CAT and len(operands) == 1:
        return None, operands[0]
    return None, None


def _code_on_stdin(text: str, depth: int) -> Iterator[tuple[str, list[str], str]]:
    """Code a shell or Python reads on stdin: piped, from ``< <(...)``, or a Python heredoc.

    Literal code (from ``echo``/``printf``) is judged here; a file (``cat
    f | bash``) is yielded as ``_CODE_FILE`` for the caller, which knows the
    directory, to read. A shell heredoc needs nothing here: its body is not
    blanked, so its lines are judged as commands already. Text that cannot
    be split into words is left to :func:`_invocations`, which judges the
    same segment as unparsed.
    """
    for pipeline in split_unquoted(text, _PIPELINE_BOUNDARIES):
        try:
            stages = [shlex.split(stage) for stage in split_unquoted(pipeline, _PIPE)]
        except ValueError as error:
            logger.debug("Pipeline left to the unparsed check (%s): %r", error, pipeline)
            continue
        for producer, consumer in pairwise(stages):
            yield from _fed(_producer_output(producer), consumer, pipeline, depth)
    for found in _STDIN_PROCESS_SUBSTITUTION.finditer(text):
        end = _closing_paren(text, found.end())
        try:
            producer = shlex.split(text[found.end() : end])
        except ValueError as error:
            logger.debug("Substitution left to the unparsed check (%s)", error)
            continue
        yield from _fed(_producer_output(producer), [found.group("shell")], found.group(0), depth)
    for receiver, body in _heredoc_bodies(text):
        argv = _python_stdin_argv(receiver)
        if argv is not None:
            yield from _python_code_runs(body, argv, body, depth)


def _fed(
    output: tuple[str | None, str | None], consumer: list[str], segment: str, depth: int
) -> Iterator[tuple[str, list[str], str]]:
    """What a consumer runs when a producer's output is its code."""
    printed, path = output
    python_argv = _python_stdin_argv(consumer)
    if python_argv is not None:
        if printed is not None:
            yield from _python_code_runs(printed, python_argv, segment, depth)
        elif path is not None:
            yield _CODE_FILE, [_PYTHON_CODE, path, *python_argv], segment
    elif _reads_code_from_stdin(consumer):
        if printed is not None:
            yield from _nested(printed, segment, depth)
        elif path is not None:
            yield _CODE_FILE, [_SHELL_CODE, path], segment


def _heredoc_bodies(text: str) -> Iterator[tuple[list[str], str]]:
    """Each heredoc's receiving command words and its body.

    Quoted or not: whether the OUTER shell expands the body does not change
    what the receiver does with it. A receiver that cannot be split is
    skipped; its line is judged as unparsed by :func:`_invocations`.
    """
    for found in _HEREDOC_OPENER.finditer(text):
        line_start = text.rfind("\n", 0, found.start()) + 1
        body_start = text.find("\n", found.end())
        if body_start == -1:
            continue
        delimiter = found.group("delim")
        body: list[str] = []
        for line in text[body_start + 1 :].split("\n"):
            candidate = line.lstrip(_TAB) if found.group("strip") else line
            if candidate == delimiter:
                break
            body.append(candidate)
        stages = split_unquoted(text[line_start : found.start()], (*_PIPELINE_BOUNDARIES, *_PIPE))
        try:
            receiver = shlex.split(stages[-1]) if stages else []
        except ValueError as error:
            logger.debug("Heredoc receiver left to the unparsed check (%s)", error)
            continue
        yield receiver, "\n".join(body)


def _strip_prefixes(argv: list[str]) -> list[str]:
    """Drop assignments, keywords and wrappers until the command word leads."""
    return _peel(argv)[0]


def _peel(argv: list[str]) -> tuple[list[str], str | None]:
    """Drop assignments, keywords and wrappers; also return an ``env -C`` directory.

    ``env -C DIR cmd`` runs ``cmd`` in DIR (review 5 n3), so the directory
    is returned for the caller to apply to that command alone.
    """
    directory: str | None = None
    while True:
        start = 0
        while start < len(argv):
            if _ASSIGNMENT.match(argv[start]) or argv[start] in _SHELL_KEYWORDS:
                start += 1
            elif argv[start] == _FUNCTION:
                # `function t { pytest; }`: the body is judged as `t() { ...; }` is.
                start += _FUNCTION_HEADER_WORDS
            else:
                break
        if (
            start + 1 < len(argv)
            and argv[start] == _COMMAND
            and argv[start + 1] in _COMMAND_LOOKUP_FLAGS
        ):
            # `command -v pytest` prints where pytest is; it runs nothing.
            return argv[start:], directory
        _, peeled = peel_command_wrappers(argv[start:])
        if start == 0 and peeled == 0:
            return argv, directory
        directory = _env_directory(argv[start : start + peeled]) or directory
        argv = argv[start + peeled :]


def _env_directory(wrapper_words: Sequence[str]) -> str | None:
    """The directory ``env -C DIR`` / ``env --chdir=DIR`` moves to, among peeled words."""
    in_env = False
    for index, word in enumerate(wrapper_words):
        if command_word(word) == _ENV:
            in_env = True
            continue
        if not in_env:
            continue
        if word in _ENV_CHDIR_FLAGS and index + 1 < len(wrapper_words):
            return wrapper_words[index + 1]
        flag, separator, value = word.partition(_FLAG_VALUE_SEPARATOR)
        if separator and flag in _ENV_CHDIR_FLAGS:
            return value
        if word.startswith(_ENV_SHORT_CHDIR) and len(word) > len(_ENV_SHORT_CHDIR):
            return word[len(_ENV_SHORT_CHDIR) :]
    return None


def _resolve(
    words: list[str], segment: str, depth: int, hops: int = 0
) -> Iterator[tuple[str, list[str], str]]:
    """Resolve one word list to the program it starts.

    ``hops`` counts the launchers, runners and modules already followed to
    get here; past ``_MAX_HOPS`` the command is judged as unparsed (fail
    closed) rather than followed until the interpreter's stack runs out.
    """
    if hops > _MAX_HOPS:
        yield _UNPARSED, [], segment
        return
    argv, directory = _peel(words)
    if directory is None:
        yield from _resolve_command(argv, segment, depth, hops)
        return
    yield _CD_PUSH, [directory], segment
    yield from _resolve_command(argv, segment, depth, hops)
    yield _CD_POP, [], segment


def _is_built_at_run_time(word: str) -> bool:
    """A command word naming its program by a variable or a substitution.

    ``$P``, ``$(which pytest)`` and a backtick span are; ``$HOME/bin/pytest``
    and ``$(dirname "$0")/run.sh`` are not, as their last part is literal.
    """
    if not word.startswith(_RUN_TIME_PREFIXES):
        return False
    if _PATH_SEPARATOR not in word:
        return True
    return any(char in _UNBUILT_CHARACTERS for char in word.rsplit(_PATH_SEPARATOR, 1)[-1])


def _resolve_command(
    argv: list[str], segment: str, depth: int, hops: int
) -> Iterator[tuple[str, list[str], str]]:
    """Resolve a word list whose first word is the command."""
    if not argv:
        return
    rest = argv[1:]
    unquoted = argv[0].replace('"', "").replace("'", "")
    if _is_built_at_run_time(unquoted):
        yield _OPAQUE, [unquoted, *rest], segment
        return
    alternatives = _expand_braces(unquoted) if _BRACE_OPEN in unquoted else None
    if alternatives is not None and len(alternatives) > 1:
        # `for p in pytest ruff; do $p tests; done` runs each in turn.
        for alternative in alternatives:
            yield from _resolve([alternative, *rest], segment, depth, hops + 1)
        return
    name = command_word(argv[0])
    if not name:
        return

    if name == _UVX:
        yield from _resolve_run_tail(rest, 0, _UV_RUN_VALUE_FLAGS, segment, depth, hops, tool=True)
        return

    if name == _EVAL:
        yield from _nested(" ".join(rest), segment, depth)
        return

    if name in _SOURCE_COMMANDS:
        if rest:
            yield command_word(rest[0]), rest[1:], segment
        return

    if name == _XARGS:
        yield from _resolve_run_tail(rest, 0, _XARGS_VALUE_FLAGS, segment, depth, hops)
        return

    launcher = _LAUNCHERS.get(name)
    if launcher is not None:
        yield from _resolve_launcher(launcher, rest, segment, depth, hops)
        return

    if name == _PARALLEL:
        yield from _resolve_parallel(rest, segment, depth, hops)
        return

    runner = _PROJECT_RUNNERS.get(name)
    if runner is not None:
        yield from _resolve_runner(name, runner, rest, segment, depth, hops)
        return

    if _PYTHON_INTERPRETER.match(name):
        yield from _resolve_python(rest, segment, depth, hops)
        return

    if name in _SHELL_INTERPRETERS:
        yield from _resolve_shell(rest, segment, depth)
        return

    yield _PROGRAM_ALIASES.get(name, name), rest, segment


def _is_flag(word: str) -> bool:
    return word.startswith(FLAG_PREFIX) and word != LONE_DASH


def _command_positions(
    words: Sequence[str], value_flags: frozenset[str], start: int
) -> Iterator[int]:
    """Each position from ``start`` where the next command word may begin.

    A word after a listed value flag is that flag's value. A word after an
    UNLISTED flag may be its value or the command, since no table lists every
    runner flag (``--color never``, ``--resolution lowest``): it is yielded,
    and the scan goes on as though it were the value. The first word no flag
    can claim ends the scan, and so does the word after ``--``.
    """
    index = start
    after_unlisted_flag = False
    while index < len(words):
        word = words[index]
        if word == END_OF_OPTIONS:
            yield index + 1
            return
        if _is_flag(word):
            listed = word in value_flags
            index += 2 if listed else 1
            after_unlisted_flag = not listed and _FLAG_VALUE_SEPARATOR not in word
            continue
        yield index
        if not after_unlisted_flag:
            return
        after_unlisted_flag = False
        index += 1


def _resolve_run_tail(
    words: list[str],
    start: int,
    value_flags: frozenset[str],
    segment: str,
    depth: int,
    hops: int,
    *,
    tool: bool = False,
) -> Iterator[tuple[str, list[str], str]]:
    """Resolve what ``run`` starts, trying each word that may be the command.

    A candidate that is really a flag's value names a program no pattern
    declares, so trying it costs nothing; skipping it could skip the command.
    ``tool`` strips a version pin (``pytest@8``), as ``uvx`` accepts one.
    """
    for index in _command_positions(words, value_flags, start):
        tail = list(words[index:])
        if tool and tail:
            tail[0] = tail[0].split(_VERSION_PIN, 1)[0]
        yield from _resolve(tail, segment, depth, hops + 1)


def _code_flag_value(launcher: _Launcher, words: list[str], index: int) -> str | None:
    """The code a launcher's code flag at ``index`` carries, or None when it is no code flag.

    ``-c 'cmd'``, ``--command='cmd'`` and a short cluster ending in the code
    letter (``script -qc 'cmd'``, review 5 m3) all carry it.
    """
    word = words[index]
    following = words[index + 1] if index + 1 < len(words) else ""
    flag, separator, attached = word.partition(_FLAG_VALUE_SEPARATOR)
    if flag in launcher.code_flags:
        return attached if separator else following
    if not _is_flag(word) or word.startswith(_LONG_FLAG_PREFIX):
        return None
    for code_flag in launcher.code_flags:
        if len(code_flag) != _SHORT_OPTION or code_flag.startswith(_LONG_FLAG_PREFIX):
            continue
        position = word.find(code_flag[1], 1)
        if position != -1:
            return word[position + 1 :] or following
    return None


def _resolve_launcher(
    launcher: _Launcher, words: list[str], segment: str, depth: int, hops: int
) -> Iterator[tuple[str, list[str], str]]:
    """``<launcher> [flags] [operands] <command>`` runs ``<command>``, or a code flag's value."""
    index, operands = 0, launcher.operands
    while index < len(words):
        word = words[index]
        code = _code_flag_value(launcher, words, index)
        if code is not None:
            if code:
                yield from _nested(code, segment, depth)
            return
        if word == END_OF_OPTIONS:
            index += 1 + operands
            break
        if _is_flag(word):
            index += 2 if word in launcher.value_flags else 1
            continue
        if launcher.runs_tail and operands == 0:
            break
        operands -= 1
        index += 1
    if launcher.runs_tail:
        yield from _resolve(words[index:], segment, depth, hops + 1)


def _parallel_inputs(words: Sequence[str]) -> list[str]:
    """The literal arguments after each ``:::``; those after ``::::`` name files."""
    inputs: list[str] = []
    literal = False
    for word in words:
        if word in _PARALLEL_ARGUMENT_SEPARATORS:
            literal = word in _PARALLEL_LITERAL_SEPARATORS
        elif literal:
            inputs.append(word)
    return inputs


def _resolve_parallel(
    words: list[str], segment: str, depth: int, hops: int
) -> Iterator[tuple[str, list[str], str]]:
    """``parallel [options] cmd ::: a b`` runs ``cmd a`` and ``cmd b``.

    Arguments read from ``::::`` files or stdin cannot be seen, so the command
    is then judged with its explicit words alone. With no command before
    ``:::``, each argument is itself a command.
    """
    for index in _command_positions(words, _PARALLEL_VALUE_FLAGS, 0):
        tail = words[index:]
        split = next(
            (at for at, word in enumerate(tail) if word in _PARALLEL_ARGUMENT_SEPARATORS),
            len(tail),
        )
        command, inputs = tail[:split], _parallel_inputs(tail[split:])
        if not command:
            for code in inputs:
                yield from _nested(code, segment, depth)
        elif not inputs:
            yield from _resolve(command, segment, depth, hops + 1)
        else:
            for value in inputs:
                yield from _resolve([*command, value], segment, depth, hops + 1)


def _resolve_runner(
    name: str, runner: _Runner, rest: list[str], segment: str, depth: int, hops: int
) -> Iterator[tuple[str, list[str], str]]:
    """``uv [flags] run [flags] [--] cmd`` and its siblings run ``cmd``.

    The subcommand is looked for the same way as the command, so an
    unlisted global flag's value cannot hide ``run`` either.
    """
    for index in _command_positions(rest, runner.global_value_flags, 0):
        if index >= len(rest):
            return
        if rest[index] == _RUNNER_SUBCOMMAND:
            tail = rest[: index + 1] + _hatch_command(rest[index + 1 :]) if name == _HATCH else rest
            yield from _resolve_run_tail(
                tail, index + 1, runner.run_value_flags, segment, depth, hops
            )
            return
        if name == _HATCH and rest[index] == _HATCH_TEST_SUBCOMMAND:
            yield _PYTEST, _hatch_test_arguments(rest[index + 1 :]), segment
            return
        if (
            name == _UV
            and rest[index] == _UV_TOOL_SUBCOMMAND
            and index + 1 < len(rest)
            and rest[index + 1] == _RUNNER_SUBCOMMAND
        ):
            yield from _resolve_run_tail(
                rest, index + 2, _UV_RUN_VALUE_FLAGS, segment, depth, hops, tool=True
            )
            return


def _hatch_test_arguments(words: list[str]) -> list[str]:
    """The pytest arguments of ``hatch test``: its own options dropped, the rest passed on."""
    passed: list[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        if word == END_OF_OPTIONS:
            passed.extend(words[index + 1 :])
            break
        if word in _HATCH_TEST_VALUE_FLAGS:
            index += 2
            continue
        if word not in _HATCH_TEST_FLAGS:
            passed.append(word)
        index += 1
    return passed


def _hatch_command(words: list[str]) -> list[str]:
    """``hatch run test:pytest`` runs ``pytest`` in the ``test`` environment."""
    for position, word in enumerate(words):
        if _is_flag(word):
            continue
        env, separator, command = word.partition(_HATCH_ENV_SEPARATOR)
        if not (separator and env and command):
            return words
        resolved = list(words)
        resolved[position] = command
        return resolved
    return words


def _string_literals(code: str) -> list[str]:
    """The content of each quoted string in Python code, in order."""
    return [single or double for single, double in _PYTHON_STRING_LITERAL.findall(code)]


def _pytest_in_code(code: str, argv: Sequence[str] = ()) -> list[str] | None:
    """The operands of the pytest run Python code makes, or None when it makes none.

    Code runs pytest when it CALLS it (review 5 m1): ``pytest.main(...)``,
    ``from pytest import main`` then ``main(...)``, an import of the literal
    module ``pytest`` by function, or a ``"pytest"`` string literal (a
    process argv, or the module after ``"-m"``). Importing pytest, or
    reading its version, runs nothing.

    The string literals are the run's words, so ``pytest.main(
    ["tests/unit/x.py"])`` is targeted and ``pytest.main()`` is a bare run;
    a ``"-m"`` before ``"pytest"`` selects the module and is dropped. When the
    code reads ``sys.argv``, the words after the code (``argv``) are words of
    the run too.
    """
    literals = _string_literals(code)
    calls = any(pattern.search(code) for pattern in _PYTEST_CALLS) or (
        _PYTEST_MAIN_IMPORT.search(code) is not None and _MAIN_CALL.search(code) is not None
    )
    starts_pytest = _PYTEST in literals and _PROCESS_CALL.search(code) is not None
    if not calls and not starts_pytest:
        return None
    operands: list[str] = []
    for literal in literals:
        if literal == _PYTEST:
            if operands and operands[-1] == _PYTHON_MODULE_FLAG:
                operands.pop()
            continue
        operands.append(literal)
    if _SYS_ARGV.search(code) is not None:
        operands.extend(argv)
    return operands


def _python_code_runs(
    code: str, argv: Sequence[str], segment: str, depth: int
) -> Iterator[tuple[str, list[str], str]]:
    """What Python code runs: pytest, a shell command it hands to a process, or neither.

    When the code starts a process, a string literal holding a command line
    is judged as shell code. Code that imports or runs a module named only
    at run time is yielded as ``_OPAQUE``, so the caller can fail closed.
    """
    if _PROCESS_CALL.search(code) is not None:
        for literal in _string_literals(code):
            if literal.split(maxsplit=1)[1:]:
                yield from _nested(literal, segment, depth)
    operands = _pytest_in_code(code, argv)
    if operands is not None:
        yield _PYTEST, operands, segment
    elif any(pattern.search(code) for pattern in _DYNAMIC_EXECUTION):
        yield _OPAQUE, [_PYTEST, *_string_literals(code), *argv], segment


def _resolve_python(
    rest: list[str], segment: str, depth: int, hops: int
) -> Iterator[tuple[str, list[str], str]]:
    """``python [flags] script args``, ``-m module args``, ``-c code`` or code on stdin.

    A module is resolved like a command, so ``python -m coverage run -m
    pytest`` reaches pytest and ``python -m py.test`` is pytest. Code is
    judged by :func:`_python_code_runs`, whether it comes from ``-c``, a
    here-string, or a file on stdin (``python3 < f.py``, which the caller
    reads).
    """
    index = 0
    stdin_file: str | None = None
    while index < len(rest):
        argument = rest[index]
        following = rest[index + 1] if index + 1 < len(rest) else ""
        if argument.startswith(_HERE_STRING):
            code = argument[len(_HERE_STRING) :] or following
            yield from _python_code_runs(code, [], segment, depth)
            return
        stdin = _STDIN_REDIRECT.match(argument)
        if stdin is not None:
            stdin_file = stdin.group("target") or following
            index += 1 if stdin.group("target") else 2
            continue
        redirect = _REDIRECT.match(argument)
        if redirect is not None:
            index += 1 if redirect.group("target") else 2
            continue
        if argument == _PYTHON_MODULE_FLAG:
            if following:
                yield from _resolve(rest[index + 1 :], segment, depth, hops + 1)
            return
        if argument.startswith(_PYTHON_MODULE_FLAG) and not argument.startswith(_LONG_FLAG_PREFIX):
            module = argument[len(_PYTHON_MODULE_FLAG) :]
            yield from _resolve([module, *rest[index + 1 :]], segment, depth, hops + 1)
            return
        if argument.startswith(_PYTHON_CODE_FLAG) and not argument.startswith(_LONG_FLAG_PREFIX):
            attached = argument[len(_PYTHON_CODE_FLAG) :]
            code_at = index if attached else index + 1
            code = attached or following
            yield from _python_code_runs(code, rest[code_at + 1 :], segment, depth)
            return
        if argument in _PYTHON_VALUE_FLAGS:
            index += 2
            continue
        if argument == LONE_DASH:
            break
        if argument.startswith(FLAG_PREFIX):
            index += 1
            continue
        yield command_word(argument), rest[index + 1 :], segment
        return
    if stdin_file:
        yield _CODE_FILE, [_PYTHON_CODE, stdin_file], segment


def _resolve_shell(
    rest: list[str], segment: str, depth: int
) -> Iterator[tuple[str, list[str], str]]:
    """``bash script args`` runs the script; ``-c 'code'``, ``<<< 'code'`` and ``< file`` run code."""
    index = 0
    runs_code = False
    stdin_file = ""
    while index < len(rest):
        argument = rest[index]
        following = rest[index + 1] if index + 1 < len(rest) else ""
        if argument.startswith(_HERE_STRING):
            code = argument[len(_HERE_STRING) :] or following
            yield from _nested(code, segment, depth)
            return
        stdin = _STDIN_REDIRECT.match(argument)
        if stdin is not None:
            stdin_file = stdin.group("target") or following
            index += 1 if stdin.group("target") else 2
            continue
        redirect = _REDIRECT.match(argument)
        if redirect is not None:
            index += 1 if redirect.group("target") else 2
            continue
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
            yield from _nested(argument, segment, depth)
            return
        yield command_word(argument), rest[index + 1 :], segment
        return
    if stdin_file and not runs_code:
        yield _CODE_FILE, [_SHELL_CODE, stdin_file], segment


def _normalise_operand(value: str) -> str:
    """Spell a path operand one way.

    ``./tests/``, ``$PWD/tests``, ``tests//unit/..`` and ``tests`` are one
    run: ``.``, ``..`` and repeated separators are folded as the filesystem
    would fold them (review 3 R7).
    """
    if value in _CWD_VARIABLES:
        return _CURRENT_DIR
    for prefix in _CWD_VARIABLE_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    if not value or _NODE_ID_SEPARATOR in value:
        return value or _CURRENT_DIR
    return posixpath.normpath(value)


def _relative_to_start(operand: str, here: Path | None, start: Path | None) -> str | None:
    """Where a path operand lands, relative to where the command started.

    Returns ``.`` for the starting directory itself, ``_ABOVE_START`` for a
    directory that contains it, or None when it cannot be placed (no
    directory is known, it lies elsewhere, or the shell would expand it).
    """
    if start is None or operand.startswith(_UNSEEN_CD_PREFIXES):
        return None
    if operand.startswith(_PATH_SEPARATOR):
        resolved = PurePosixPath(posixpath.normpath(operand))
    elif here is not None:
        resolved = PurePosixPath(posixpath.normpath(str(PurePosixPath(here) / operand)))
    else:
        return None
    origin = PurePosixPath(posixpath.normpath(str(start)))
    if resolved == origin:
        return _CURRENT_DIR
    if origin.is_relative_to(resolved):
        return _ABOVE_START
    if resolved.is_relative_to(origin):
        return resolved.relative_to(origin).as_posix()
    return None


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


def _takes_next_word(flag: str, pattern: FullQaPattern) -> bool:
    """Whether ``flag`` consumes the word after it as its value.

    A declared or grammar value flag does. Without a grammar nothing else
    does. Under a grammar, a known option, a cluster of known short options
    (``-xvs``) and a short value option with its value attached (``-n8``)
    take nothing, and any other flag is a plugin's the grammar does not know:
    it is read as taking a value, so a path-shaped value
    (``--json-report-file out/r.json``) never passes for a target.
    """
    if _FLAG_VALUE_SEPARATOR in flag:
        return False
    if flag in pattern.value_flags:
        return True
    known = pattern.flag_options
    if known is None or flag in known:
        return False
    if flag.startswith(_LONG_FLAG_PREFIX):
        return True
    if flag[:_SHORT_OPTION] in pattern.value_flags:
        return False
    return not all(f"{FLAG_PREFIX}{letter}" in known for letter in flag[1:])


def _is_absolute(operand: str) -> bool:
    """A path from the filesystem root, or from the home directory (``~/``, ``$HOME/``)."""
    return operand.startswith((_PATH_SEPARATOR, *_HOME_PREFIXES))


def _repository_root(path: PurePosixPath) -> PurePosixPath | None:
    """The nearest directory at or above ``path`` holding a repository marker."""
    for candidate in (path, *path.parents):
        if any((Path(candidate) / marker).exists() for marker in _REPOSITORY_MARKERS):
            return candidate
    return None


def _names_the_suite(relative: str, full_args: frozenset[str]) -> bool:
    """A path relative to its root that is the root, a ``full_args`` entry or an ancestor of one."""
    return (
        relative == _CURRENT_DIR
        or relative in full_args
        or any(entry.startswith(relative + _PATH_SEPARATOR) for entry in full_args)
    )


def _operand_is_full(
    operand: str, full_args: frozenset[str], here: Path | None, start: Path | None
) -> bool:
    """Whether an operand names the whole suite.

    The operand is resolved from the directory the command runs in and judged
    against the repository CONTAINING it (review 4 N6): at its root, at a
    ``full_args`` entry, or at an ancestor of one. Where no repository marker
    is found, the starting directory stands in for the root. At or above the
    starting directory is always full. An operand that cannot be placed at
    all is compared literally, or by its tail when absolute.

    A plain-word entry (``all``, ``tests``) is matched literally FIRST, unless
    it names something where the command stands: ``llm_qa.py all`` runs the
    whole suite from any directory, because the script finds its project from
    its own location (review 5 M1).
    """
    if _is_subcommand_word(operand, full_args, here):
        return True
    placed = _relative_to_start(operand, here, start)
    if placed == _ABOVE_START:
        return True
    resolved = _resolved(operand, here)
    root = _repository_root(resolved) if resolved is not None else None
    if resolved is not None and root is not None and resolved.is_relative_to(root):
        return _names_the_suite(resolved.relative_to(root).as_posix(), full_args)
    if placed is not None:
        return _names_the_suite(placed, full_args)
    if operand in full_args:
        return True
    return _is_absolute(operand) and any(
        operand.endswith(_PATH_SEPARATOR + entry) for entry in full_args if entry != _CURRENT_DIR
    )


def _is_subcommand_word(operand: str, full_args: frozenset[str], here: Path | None) -> bool:
    """A ``full_args`` word with no path in it, and nothing of that name where the command runs."""
    if operand not in full_args or _PATH_SEPARATOR in operand or operand == _CURRENT_DIR:
        return False
    if here is None:
        return True
    try:
        return not (here / operand).exists()
    except OSError as error:
        logger.debug("Cannot look up %r under %s (%s): read as a word", operand, here, error)
        return True


def _resolved(operand: str, here: Path | None) -> PurePosixPath | None:
    """The absolute path an operand names, or None when that cannot be known."""
    if operand.startswith(_UNSEEN_CD_PREFIXES):
        return None
    if operand.startswith(_PATH_SEPARATOR):
        return PurePosixPath(posixpath.normpath(operand))
    if here is None:
        return None
    return PurePosixPath(posixpath.normpath(str(PurePosixPath(here) / operand)))


def _expand_braces(word: str) -> list[str] | None:
    """Every word bash's brace expansion makes of ``word`` (``a/{b,c}`` is ``a/b a/c``).

    None when there are more than the cap, or more groups than can be walked:
    too many to judge, so the caller treats the word as the whole suite. The
    work is bounded by the cap, never by the full expansion (review 5 M2).
    """
    if word.count(_BRACE_OPEN) > _MAX_BRACE_GROUPS:
        return None
    expanded = list(islice(_brace_alternatives(word), _MAX_BRACE_ALTERNATIVES + 1))
    return None if len(expanded) > _MAX_BRACE_ALTERNATIVES else expanded


def _brace_alternatives(word: str) -> Iterator[str]:
    """Lazily, each word bash's brace expansion makes of ``word``."""
    open_at = word.find(_BRACE_OPEN)
    while open_at != -1:
        depth, index, commas = 0, open_at, []
        while index < len(word):
            char = word[index]
            if char == _BRACE_OPEN:
                depth += 1
            elif char == _BRACE_CLOSE:
                depth -= 1
                if depth == 0:
                    break
            elif char == _BRACE_SEPARATOR and depth == 1:
                commas.append(index)
            index += 1
        if index < len(word) and commas:
            bounds = [open_at, *commas, index]
            head, tail = word[:open_at], word[index + 1 :]
            for left, right in pairwise(bounds):
                yield from _brace_alternatives(head + word[left + 1 : right] + tail)
            return
        open_at = word.find(_BRACE_OPEN, open_at + 1)
    yield word


def _is_run_time_operand(word: str) -> bool:
    """An operand from a variable or a substitution, other than the cwd and home forms."""
    return (
        word.startswith(_RUN_TIME_PREFIXES)
        and word not in _CWD_VARIABLES
        and not word.startswith((*_CWD_VARIABLE_PREFIXES, *_HOME_PREFIXES))
    )


def _glob_reach(operand: str) -> str | None:
    """The directory a glob can reach all of, or None when it names files in one place.

    ``tests/*`` and ``tests/unit/**/test_*.py`` reach every test under
    ``tests`` and ``tests/unit``; ``tests/unit/handlers/test_*.py`` names only
    files in one directory, which is as narrow as naming them (review 4 N5).
    """
    first = _GLOB_CHARACTERS.search(operand)
    if first is None:
        return None
    literal = operand[: first.start()]
    directory = literal.rsplit(_PATH_SEPARATOR, 1)[0] if _PATH_SEPARATOR in literal else ""
    pattern = operand[len(directory) :].lstrip(_PATH_SEPARATOR)
    last = pattern.rsplit(_PATH_SEPARATOR, 1)[-1]
    if _ANY_DEPTH not in pattern and last.endswith(_PYTHON_SUFFIX):
        return None
    return directory or _CURRENT_DIR


def _is_full_run(
    pattern: FullQaPattern,
    arguments: Sequence[str],
    cwd: Path | None,
    start: Path | None = None,
) -> bool:
    """Whether these arguments make ``pattern.command`` run the whole suite.

    A word naming the whole suite (``full_args``) makes the run full wherever
    it sits. Otherwise the run is targeted only by a PATH-LIKE operand; any
    other word is a flag's value and is ignored (see :func:`_is_path_like`).
    ``cwd`` is where the command runs (moved by any ``cd``), ``start`` where
    the event began, which ``full_args`` are relative to.
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
                _takes_next_word(argument, pattern)
                and index < len(arguments)
                and not arguments[index].startswith(FLAG_PREFIX)
            ):
                index += 1
            continue
        word, target_follows = _split_attached_redirect(argument)
        if target_follows:
            index += 1
        if word == _CHANGED_FILES or (
            word.startswith((_SUBSTITUTION_OPENER, _BACKTICK)) and _lists_changed_files(word)
        ):
            targets.append(word)
            continue
        if _is_run_time_operand(word):
            # Built only when the command runs, so it may be the suite (review 5).
            names_full_suite = True
            continue
        alternatives = _expand_braces(word)
        if alternatives is None:
            names_full_suite = True
            continue
        for expanded in alternatives:
            reach = _glob_reach(expanded)
            operand = _normalise_operand(expanded if reach is None else reach)
            if pattern.full_args is not None and _operand_is_full(
                operand, pattern.full_args, cwd, start
            ):
                names_full_suite = True
            elif reach is not None or _is_path_like(operand, cwd):
                targets.append(operand)

    if pattern.full_args is None or names_full_suite:
        return True
    if targets or not pattern.bare_is_full:
        return False
    # A bare run collects the directory it runs in, so below the repository
    # root it is as narrow as that directory.
    return cwd is None or _operand_is_full(_CURRENT_DIR, pattern.full_args, cwd, start)


def find_full_qa_invocation(
    command: str, patterns: Sequence[FullQaPattern], *, cwd: Path | None = None
) -> FullQaMatch | None:
    """The first full-suite run in ``command``, or None.

    Args:
        command: The Bash command as the tool received it (line continuations
            already joined by ``get_bash_command``).
        patterns: The validated declaration.
        cwd: The directory the command starts in, so a bare word naming a
            directory there counts as a path. Each ``cd`` in the command
            moves it on. None judges by shape alone.

    Returns:
        The pattern that matched and the command segment it matched in.
    """
    if not patterns:
        return None
    if len(command) > _MAX_COMMAND_LENGTH:
        named = next((p for p in patterns if _names_program(command, p.command)), None)
        if named is None:
            return None
        quoted = command[:_QUOTED_SEGMENT_LENGTH] + _ELLIPSIS
        return FullQaMatch(named.pattern_id, quoted, fail_closed=_OVERSIZED_REASON)
    return _first_full_run(_invocations(command), patterns, command, cwd, cwd, 0)


def _first_full_run(
    invocations: Iterable[tuple[str, list[str], str]],
    patterns: Sequence[FullQaPattern],
    command: str,
    here: Path | None,
    start: Path | None,
    files_deep: int,
) -> FullQaMatch | None:
    """The first full run among ``invocations``, following each ``cd`` in order.

    ``command`` is the whole Bash command, searched for a program when a
    command word is a variable the command does not set. ``files_deep``
    counts code files already read on the way here, so a file that feeds
    itself to a shell is not read for ever.
    """
    directories: list[Path | None] = []
    for program, arguments, segment in invocations:
        if program == _CD:
            here = _changed_directory(here, arguments)
        elif program == _CD_PUSH:
            directories.append(here)
            here = _changed_directory(here, arguments)
        elif program == _CD_POP:
            here = directories.pop() if directories else here
        elif program == _CODE_FILE:
            found = _full_run_in_code_file(
                arguments, segment, patterns, command, here, start, files_deep
            )
            if found is not None:
                return found
        else:
            found = _full_run_of(program, arguments, segment, patterns, command, here, start)
            if found is not None:
                return found
    return None


def _full_run_of(
    program: str,
    arguments: list[str],
    segment: str,
    patterns: Sequence[FullQaPattern],
    command: str,
    here: Path | None,
    start: Path | None,
) -> FullQaMatch | None:
    """Whether one invocation is a declared full run, read or judged unseen."""
    if program == _UNPARSED:
        named = next((p for p in patterns if _names_program(segment, p.command)), None)
        if named is None:
            return None
        return FullQaMatch(named.pattern_id, segment.strip(), fail_closed=_UNPARSED_REASON)
    if program == _OPAQUE:
        word, rest = arguments[0], arguments[1:]
        # A variable the command does not set may hold any program the command
        # names; a substitution names its program in its own text.
        haystack = command if _VARIABLE.fullmatch(word) else word
        for pattern in patterns:
            if _names_program(haystack, pattern.command) and _is_full_run(
                pattern, rest, here, start
            ):
                return FullQaMatch(pattern.pattern_id, segment.strip(), fail_closed=_OPAQUE_REASON)
        return None
    for pattern in patterns:
        if pattern.command == program and _is_full_run(pattern, arguments, here, start):
            return FullQaMatch(pattern_id=pattern.pattern_id, segment=segment.strip())
    return None


def _full_run_in_code_file(
    arguments: list[str],
    segment: str,
    patterns: Sequence[FullQaPattern],
    command: str,
    here: Path | None,
    start: Path | None,
    files_deep: int,
) -> FullQaMatch | None:
    """A full run in code an interpreter reads from a file, or in the file's own name.

    The name is judged as ``bash FILE`` would be, so a declared script
    matches whatever the file holds. The content is read when the file is a
    regular file within the size cap; a cd inside it stays inside it.
    """
    kind, path, argv = arguments[0], arguments[1], arguments[2:]
    by_name = _full_run_of(command_word(path), [], segment, patterns, command, here, start)
    if by_name is not None or files_deep >= _MAX_NESTING:
        return by_name
    content = _read_code_file(path, here)
    if content is None:
        return None
    invocations = (
        _invocations(content)
        if kind == _SHELL_CODE
        else _python_code_runs(content, argv, segment, 0)
    )
    found = _first_full_run(invocations, patterns, command, here, start, files_deep + 1)
    # The deny quotes the command that fed the file, never the file's own text.
    return (
        None if found is None else FullQaMatch(found.pattern_id, segment.strip(), found.fail_closed)
    )


def _read_code_file(path: str, here: Path | None) -> str | None:
    """The text of a code file within the size cap, or None when there is none to read.

    None for no known directory, no regular file, or a file past the cap:
    the file is then judged by its name alone. A file that exists but cannot
    be read raises ``OSError``, which the daemon turns into a deny: the code
    may be a run, and it could not be seen.
    """
    if path.startswith(_PATH_SEPARATOR):
        target = Path(path)
    elif here is not None:
        target = here / path
    else:
        return None
    if not target.is_file() or target.stat().st_size > _MAX_CODE_FILE_BYTES:
        return None
    return target.read_bytes().decode("utf-8", errors="replace")


def _names_program(text: str, program: str) -> bool:
    """Whether ``program`` appears in ``text`` as a word or a path's last part."""
    return re.search(rf"(?<![\w.-]){re.escape(program)}(?![\w.-])", text) is not None


def _changed_directory(current: Path | None, arguments: Sequence[str]) -> Path | None:
    """Where ``cd <arguments>`` leaves the command, or None when it cannot be known.

    An argument the shell would expand (``$X``, ``~``), ``cd -`` and a bare
    ``cd`` all lead somewhere this cannot see, so the path shape decides
    from there on. Commands are followed in order, which treats a ``cd``
    inside a subshell as though it persisted: a bounded approximation.
    """
    operands = [word for word in arguments if not _is_flag(word)]
    if len(operands) != 1:
        return None
    target = operands[0]
    if target == LONE_DASH or target.startswith(_UNSEEN_CD_PREFIXES):
        return None
    if target.startswith(_PATH_SEPARATOR):
        return Path(target)
    return None if current is None else current / target


# ── The handler ────────────────────────────────────────────────────────────

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.SUBAGENT_FULL_QA,
    blocked="a full-suite QA run inside a sub-agent (a declared `full_qa_patterns` command)",
    why="Concurrent full runs across agents exhaust the host, and the coordinator runs the full gate over every ready branch anyway",
    fix="Run targeted QA on what you changed, commit, and hand the commit to the coordinator",
    verbose=(
        "WHY BLOCKED:\n"
        "The full QA suite is the COORDINATOR's gate. It merges every ready branch\n"
        "into one integration worktree and runs the suite ONCE over all of them.\n"
        "Several agents each running the whole suite exhaust the host, and the\n"
        "coordinator's run covers your branch anyway.\n\n"
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
        unseen = f"\n\nJUDGED UNSEEN: {match.fail_closed}" if match.fail_closed else ""
        return GatingResult.deny(
            f"{RuleFormatter().verbose(_RULE)}\n\n"
            f"MATCHED: `{match.pattern_id}` in `{match.segment}`{unseen}\n\n"
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
            "gate as a batch: every ready branch merged into one integration worktree, "
            "then one run on the combined head. The main thread is never affected. Enforcement is proven for Agent-tool sub-agents and "
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
            "run only if it is path-like, looked up in the directory the command `cd`s "
            "to. `option_grammar: pytest` supplies pytest's complete option set, so a "
            "flag's value is never read as a path, and a plugin flag it does not know "
            "is read as taking a value: name test paths BEFORE such a flag, or write "
            "`--flag=value`. Ships off with no patterns; enabled with none, "
            "`hooks-daemon check` reports it as unable to fire. Keep `scope` at SUB: "
            "any other scope denies the coordinator's own run."
        )
