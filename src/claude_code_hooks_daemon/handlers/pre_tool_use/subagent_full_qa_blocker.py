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
computed name is judged as pytest. Each such deny says why.

**Code in files is read, within one budget per event (review 6).** A script
run by its name or path, and a file fed to a shell or Python, is read and
judged with its own arguments, unless it is a program the project declares,
which its pattern judges. Each path is read once; past the parse budget a
file is only scanned for a declared program's name, and code that cannot be
read at all (a producer that is not understood, a FIFO, a file the same
command writes) fails closed. The one run that is not seen is a program whose
NAME is built at run time from pieces (``$(printf 'py%s' test)``, or
``"py" + "test"`` in Python).
"""

from __future__ import annotations

import errno
import io
import logging
import posixpath
import re
import shlex
import stat
import sys
import tokenize
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from itertools import islice, pairwise
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
from claude_code_hooks_daemon.utils.path_predicates import path_exists
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
_KEY_FULL_WORDS: Final[str] = "full_words"
_KEY_BARE_IS_FULL: Final[str] = "bare_is_full"
_KEY_READ_ONLY_FLAGS: Final[str] = "read_only_flags"
_KEY_VALUE_FLAGS: Final[str] = "value_flags"
_KEY_OPTION_GRAMMAR: Final[str] = "option_grammar"

_KNOWN_KEYS: Final[frozenset[str]] = frozenset(
    {
        _KEY_ID,
        _KEY_COMMAND,
        _KEY_FULL_ARGS,
        _KEY_FULL_WORDS,
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
_WORD_LIST_KEYS: Final[tuple[str, ...]] = (
    _KEY_FULL_ARGS,
    _KEY_FULL_WORDS,
    _KEY_READ_ONLY_FLAGS,
    _KEY_VALUE_FLAGS,
)

#: The option names, for messages that tell a project what to fix.
_OPTION_PATTERNS: Final[str] = "full_qa_patterns"


@dataclass(frozen=True, slots=True)
class FullQaPattern:
    """One declared full-suite command.

    Attributes:
        pattern_id: Names the pattern in the deny, so an agent can see WHICH
            declaration it hit.
        command: The basename of the program the command runs.
        full_args: PATHS that make the program run the whole suite, judged
            from the repository holding them. None, with no ``full_words``
            either, means every run of it is full. Without a grammar, any other
            operand targets the run only when it is path-like: it contains
            ``/`` or ``::``, ends in ``.py``, or exists in the directory the
            command runs in (the event's working directory, moved by any
            ``cd`` before it). Under a grammar every operand is a target.
        full_words: WORDS that make the program run the whole suite wherever
            it runs (``llm_qa.py all``): matched literally, never as paths.
        bare_is_full: With ``full_args`` or ``full_words`` set, a run naming
            no operand at all is full too (``pytest`` with no path collects the
            whole suite).
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
    full_words: frozenset[str] = frozenset()


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
    full_words = word_lists[_KEY_FULL_WORDS]
    if full_args is None and full_words is not None:
        full_args = frozenset()
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
            full_words=full_words or frozenset(),
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
#: ``$1`` to ``$9``: a script's positional parameters by number.
_POSITIONAL_PARAMETERS: Final[int] = 9
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
#: ``${NAME:-word}`` and ``${NAME:=word}`` are ``word`` when NAME is unset.
_DEFAULT_EXPANSION: Final[re.Pattern[str]] = re.compile(
    r"\$\{(?P<name>\w+)(?P<colon>:?)[-=](?P<default>[^{}$`]*)\}"
)
#: ``"$@"`` and ``$*``: every positional parameter, as separate words.
_ALL_POSITIONAL: Final[frozenset[str]] = frozenset({"$@", "${@}", "$*", "${*}"})
#: An unquoted substitution is replaced by this while the command is split,
#: so ``$(which pytest) tests`` stays one command word and one operand.
_PLACEHOLDER_OPEN: Final[str] = ""
_PLACEHOLDER_CLOSE: Final[str] = ""
_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(f"{_PLACEHOLDER_OPEN}(\\d+){_PLACEHOLDER_CLOSE}")

#: ``git diff --name-only`` lists the files a change touches. Such a list,
#: filtered or not, is a targeted run's operands when it is not empty.
#: ``git log``/``show`` are not listings: they print commit messages unless a
#: format is given, and a format can print any word (review 6 M2).
_GIT: Final[str] = "git"
_GIT_LISTING_SUBCOMMAND: Final[str] = "diff"
#: Always prints a commit, never the empty tree, so it cannot steer a
#: listing the way an arbitrary run-time word can (review 7 m3).
_GIT_MERGE_BASE_SUBCOMMAND: Final[str] = "merge-base"
_GIT_NAME_ONLY: Final[str] = "--name-only"
#: Options that make a listing print words other than the changed paths.
_GIT_STEERING_OPTIONS: Final[tuple[str, ...]] = (
    "--format",
    "--pretty",
    "--line-prefix",
    "--output",
    "--src-prefix",
    "--dst-prefix",
    "--no-index",
)
#: The empty tree: a diff against it lists every tracked file.
_EMPTY_TREE: Final[str] = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_ABBREVIATED_OBJECT: Final[int] = 4
_HEX_RUN: Final[re.Pattern[str]] = re.compile(r"[0-9a-fA-F]+")
_LIST_FILTERS: Final[frozenset[str]] = frozenset({"grep", "sort", "uniq"})
#: ``grep -H --label=TEXT`` prints TEXT beside each line: a steered word.
_GREP_LABEL: Final[str] = "--label"
#: The operand standing for words ``xargs`` reads from stdin: unseen, and
#: possibly none.
_STDIN_WORDS: Final[str] = "the words xargs reads from stdin"
#: ``xargs -r`` runs nothing on empty input; plain ``xargs`` runs once.
_XARGS_NO_RUN_IF_EMPTY: Final[str] = "--no-run-if-empty"
_XARGS_NO_RUN_LETTER: Final[str] = "r"
_XARGS_VALUE_LETTERS: Final[frozenset[str]] = frozenset("adEILnPs")
#: The operand standing for the files a NON-EMPTY list names. Private-use
#: characters, not ``<...>``, which would read as a redirection.
_CHANGED_FILES: Final[str] = "the files a git listing names"

#: ``env -C DIR`` and ``env --chdir=DIR`` run the command in DIR; in a short
#: cluster ``C`` takes the rest of the word or the next one, as ``u`` does.
_ENV: Final[str] = "env"
_ENV_SHORT_CHDIR: Final[str] = "-C"
_ENV_CHDIR_FLAGS: Final[frozenset[str]] = frozenset({_ENV_SHORT_CHDIR, "--chdir"})
_ENV_CHDIR_LETTER: Final[str] = "C"
_ENV_UNSET_LETTER: Final[str] = "u"

#: ``coproc [NAME] command`` runs the command; a NAME precedes only a group.
_COPROC: Final[str] = "coproc"
_GROUP_OPENERS: Final[frozenset[str]] = frozenset({"{", "("})
#: ``alias NAME=VALUE`` (under ``shopt -s expand_aliases``) and ``hash -p PATH
#: NAME`` make NAME run something else.
_ALIAS: Final[str] = "alias"
_EXPAND_ALIASES: Final[re.Pattern[str]] = re.compile(r"\bshopt\s+-s\s+(?:\w+\s+)*expand_aliases\b")
_HASH: Final[str] = "hash"
_HASH_PATH_FLAG: Final[str] = "-p"
_HASH_WORDS: Final[int] = 4

#: ``command -v x`` and ``command -V x`` look ``x`` up without running it.
_COMMAND: Final[str] = "command"
_COMMAND_LOOKUP_FLAGS: Final[frozenset[str]] = frozenset({"-v", "-V"})

#: ``eval`` runs its joined arguments as shell code.
_EVAL: Final[str] = "eval"
#: ``source x`` and ``. x`` run the script ``x`` in this shell.
_SOURCE_COMMANDS: Final[frozenset[str]] = frozenset({"source", "."})
#: ``find [paths] [tests] -exec cmd {} ;`` runs ``cmd`` on what find selects
#: (review 7 m4): its start paths, whatever a ``-name``/``-path`` test
#: narrows them by (review 8 minor m3) -- a test can only select a SUBSET of
#: the start paths, so a targeted start path stays targeted under any
#: narrowing, and this is left for the same downstream check that judges a
#: bare ``pytest tests``. Only a BARE find (no path operand at all, which
#: searches ``.``) has no path text to read at all, and is unseen.
_FIND: Final[str] = "find"
_FIND_PLACEHOLDER: Final[str] = "{}"
_FIND_EXEC_ACTIONS: Final[frozenset[str]] = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_FIND_ACTION_TERMINATORS: Final[frozenset[str]] = frozenset({";", "+"})
_FIND_PATH_STOP: Final[frozenset[str]] = frozenset({"!", "("})
_FIND_SELECTED_FILES: Final[str] = "the files find selects"
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
_PRINTF: Final[str] = "printf"
_PRINTF_ASSIGN: Final[str] = "-v"
_PRINTF_PERCENT: Final[str] = "%%"
_PRINTF_CONVERSION: Final[re.Pattern[str]] = re.compile(r"%(?:%|[-+ #0]*\d*(?:\.\d+)?[a-zA-Z])")
_ESCAPED_NEWLINE: Final[str] = "\\n"
#: Where one pipeline ends; a pipe ``|`` then separates its stages.
_PIPELINE_BOUNDARIES: Final[tuple[str, ...]] = ("&&", "||", ";", "\n")
_PIPE: Final[tuple[str, ...]] = ("|",)
#: ``<(producer)``: a process substitution, read as a file. ``bash < <(p)``
#: feeds it on stdin, ``bash <(p)`` names it as the script.
_PROCESS_SUBSTITUTION_OPENER: Final[str] = "<("
_STDIN_REDIRECT_WORD: Final[str] = "<"
#: Where the command holding a process substitution starts.
_COMMAND_START_CHARACTERS: Final[str] = "|;&\n()"
#: A redirection that writes a file, and the file: ``> f``, ``>> f``, ``&> f``.
_WRITE_REDIRECT: Final[re.Pattern[str]] = re.compile(
    r"(?<![<>&\d])(?:\d|&)?>>?\|?\s*(?P<target>\"[^\"]*\"|'[^']*'|[^\s;&|<>()]+)"
)
#: ``tee FILE...`` writes each FILE.
_TEE: Final[re.Pattern[str]] = re.compile(r"(?<![\w./-])tee\b(?P<operands>[^;&|\n()]*)")
_QUOTES: Final[str] = "'\""

#: Characters the shell expands a word with, from the filesystem.
_GLOB_CHARACTERS: Final[re.Pattern[str]] = re.compile(r"[*?\[]")
_ANY_DEPTH: Final[str] = "**"
_BRACE_OPEN: Final[str] = "{"
_BRACE_CLOSE: Final[str] = "}"
_BRACE_SEPARATOR: Final[str] = ","
#: ``{1..9}``, ``{a..z}`` and ``{1..9..2}``: a sequence expression.
_SEQUENCE: Final[re.Pattern[str]] = re.compile(
    r"(?:(?P<first_number>-?\d+)\.\.(?P<last_number>-?\d+)"
    r"|(?P<first_letter>[A-Za-z])\.\.(?P<last_letter>[A-Za-z]))(?:\.\.(?P<step>-?\d+))?"
)
#: Past either limit a word is not expanded: each group is read as ``*``, a
#: glob of the same reach, unless an alternative holds a ``/`` and could
#: reach anywhere, which is judged unseen.
_MAX_BRACE_ALTERNATIVES: Final[int] = 64
_MAX_BRACE_GROUPS: Final[int] = 32
_GLOB_ANY: Final[str] = "*"

#: What marks the root of the repository an operand lies in.
_REPOSITORY_MARKERS: Final[tuple[str, ...]] = (".git", "pyproject.toml")

#: What ``_invocations`` yields for a command it could not split into words.
_UNPARSED: Final[str] = "<unparsed>"
#: What it yields for a command word the shell only builds at run time; the
#: first argument is that word, the rest are the command's arguments.
_OPAQUE: Final[str] = "<built at run time>"
#: What it yields for code an interpreter reads from a FILE, on stdin or as
#: a script; the arguments are the code's kind, the path and its own argv.
_CODE_FILE: Final[str] = "<code read from a file>"
_SHELL_CODE: Final[str] = "shell"
_PYTHON_CODE: Final[str] = "python"
#: A file run by its own path: its first line says which kind of code it is.
_EXECUTABLE_CODE: Final[str] = "executable"
#: What it yields for code a shell or Python reads that cannot be seen: from
#: a producer this does not understand, or from another descriptor.
_UNREAD_CODE: Final[str] = "<code that cannot be read>"
#: Marks code the parse meter refused: more than one judgement parses.
_OVER_BUDGET: Final[str] = "<more code than one judgement parses>"
#: What it yields for the paths a command writes (``>``, ``>>``, ``tee``):
#: code read from one of them is not what is on disk now.
_WRITES: Final[str] = "<paths this command writes>"
#: ``env -C DIR cmd``: DIR is the directory for ``cmd`` alone.
_CD_PUSH: Final[str] = "<enter a directory for one command>"
_CD_POP: Final[str] = "<leave that directory>"
#: ``pushd DIR`` and ``popd`` move the directory as a stack.
_PUSHD: Final[str] = "pushd"
_POPD: Final[str] = "popd"

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
_RUN_TIME_OPERAND_REASON: Final[str] = (
    "an operand of this run is only built at run time (a variable or a substitution), so it "
    "may name the whole suite. Spell the test paths out literally."
)
_EMPTY_LISTING_REASON: Final[str] = (
    "the git listing this run is given may be empty, and an empty one leaves a bare run, "
    "which is the whole suite. Use `xargs -r`, or name a test path beside the listing."
)
_STDIN_WORDS_REASON: Final[str] = (
    "xargs reads this run's arguments from stdin, which cannot be seen, and with none it "
    "runs the bare command, which is the whole suite. Name the test paths on the command line."
)
_FIND_SELECTED_FILES_REASON: Final[str] = (
    "find's `-exec ... {} ...` names the files find selects, narrowed by a `-name`/`-path` "
    "test this handler does not read, so it may name the whole suite. Name the test paths "
    "directly instead of narrowing find."
)
_AT_FILE_REASON: Final[str] = (
    "pytest reads more arguments from the `@file` named here, which is not read, so they may "
    "name the whole suite. Name the test paths on the command line."
)
_PYARGS_REASON: Final[str] = (
    "under `--pyargs` an operand is a package, found wherever Python's path finds it, which "
    "is not looked up here, so it may hold the whole suite. Name the test paths instead."
)
_BRACE_REASON: Final[str] = (
    "a brace expansion here makes more words than are followed, and an alternative holds a "
    "`/`, so it may reach the whole suite. Name fewer paths, or give them one directory."
)
_UNREAD_CODE_REASON: Final[str] = (
    "a shell or Python here reads code that cannot be seen: from a producer that is not "
    "understood (only `echo`, `printf` and `cat FILE` are), from a file this command also "
    "writes, from a FIFO or a device, or from a file too large to read. Put the command in "
    "the Bash call itself."
)
_SCANNED_FILE_REASON: Final[str] = (
    "a file of code here is larger than is parsed, and it names a full-suite program, so it "
    "is judged as the full run it may be. Run the targeted command directly."
)
_OVER_BUDGET_REASON: Final[str] = (
    "this command, with the code it runs, is more than one judgement parses, and code that "
    "is not judged may run the whole suite, so it is judged as one. Run each script in its "
    "own Bash call, or run the targeted command directly."
)
#: The pattern id a deny for unreadable code names: it matched no declaration.
_UNREAD_CODE_ID: Final[str] = "code-that-cannot-be-read"
#: The pattern id a deny past the parse budget names: nothing matched.
_OVER_BUDGET_ID: Final[str] = "too-much-code-to-judge"

#: Past this many characters a command is not parsed (review 5 n5): shlex
#: builds each token a character at a time, and a 1 MB word took 36 s. The
#: cap is on the raw text, because blanking a heredoc body is itself
#: quadratic in the number of unclosed openers. File content is capped alike.
_MAX_COMMAND_LENGTH: Final[int] = 32 * 1024
#: One judgement hands the parsers at most this many bytes in all (review 8
#: B1): the command's own, each nested ``bash -c``, each file's and each
#: Python literal's, re-parses included. Past it the command is DENIED.
_MAX_PARSED_BYTES: Final[int] = 96 * 1024
#: One event scans at most this much file content in all; a file past it is
#: unseen.
_MAX_SCANNED_FILE_BYTES: Final[int] = 16 * 1024 * 1024
#: A file with a NUL byte this early is a binary, judged by its name alone.
_BINARY_PROBE_BYTES: Final[int] = 1024
_NUL: Final[str] = "\x00"
#: Paths that are stdin, or read nothing.
_STDIN_DEVICE: Final[str] = "/dev/stdin"
_STDIN_PATHS: Final[frozenset[str]] = frozenset({_STDIN_DEVICE, "/dev/fd/0", LONE_DASH})
_DESCRIPTOR_PREFIX: Final[str] = "/dev/fd/"
_EMPTY_DEVICE: Final[str] = "/dev/null"
_SHEBANG: Final[str] = "#!"
#: How many launchers, runners and ``python -m`` hops are followed in one
#: command (review 5 n6). Past it the command is judged as unparsed.
_MAX_HOPS: Final[int] = 32
#: How much of an unparsed long command the deny quotes.
_QUOTED_SEGMENT_LENGTH: Final[int] = 200
_ELLIPSIS: Final[str] = "..."

#: A ``#`` at the start of a word begins a comment: after a blank or one of these.
_COMMENT: Final[str] = "#"
_COMMENT_AFTER: Final[str] = ";&|()"

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
_PYTHON_MODULE_FLAG: Final[str] = "-m"
#: Python's short options that take a value, in a cluster (``-Ic code``,
#: ``-Bm pytest``, ``-Wignore``): the rest of the word, or the next word.
_PYTHON_MODULE_LETTER: Final[str] = "m"
_PYTHON_CODE_LETTER: Final[str] = "c"
_PYTHON_VALUE_LETTERS: Final[frozenset[str]] = frozenset("cmWX")
_PYTEST: Final[str] = "pytest"
#: What Python code that calls pytest is yielded as: pytest, with every
#: string in the code as an operand, of which only a path-shaped one targets.
_PYTEST_IN_CODE: Final[str] = "<pytest called by Python code>"
#: ``pytest --pyargs pkg.mod`` names a package, which is the path ``pkg/mod``.
_PYARGS: Final[str] = "--pyargs"
_MODULE_SEPARATOR: Final[str] = "."
_DOTTED_NAME: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
#: ``pytest @args.txt`` reads more arguments from the file.
_AT_FILE_PREFIX: Final[str] = "@"
#: ``PYTEST_ADDOPTS=value``: pytest reads the value's words as its own.
_PYTEST_ADDOPTS: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w$])PYTEST_ADDOPTS=(?P<value>\"[^\"]*\"|'[^']*'|[^\s;&|()]*)"
)
#: The word a ``PYTEST_ADDOPTS`` value built at run time stands as: unseen.
_ADDOPTS_UNSEEN: Final[str] = "$PYTEST_ADDOPTS"
#: A module holding pytest's entry points: ``pytest`` or ``_pytest.*``.
_PYTEST_MODULE: Final[re.Pattern[str]] = re.compile(r"_?pytest(?:\.\w+)*")
_PYTEST_ENTRY_POINTS: Final[frozenset[str]] = frozenset({"main", "console_main"})
#: ``import a, b as c`` and ``from m import x as y, z``: the names each binds.
_IMPORT: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w.])(?:from\s+(?P<module>[\w.]+)\s+)?import\s+\(?(?P<names>[\w.]+(?:\s+as\s+\w+)?"
    r"(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*)"
)
_IMPORT_ALIAS: Final[str] = " as "
_IMPORT_SEPARATOR: Final[str] = ","
#: Python code CALLS pytest (review 5 m1): importing it, or reading its
#: version, runs nothing. The dunder spelling of the import builtin is
#: written ``_{2}import_{2}`` so this module does not read as a use of it.
_PYTEST_IMPORT_CALL: Final[re.Pattern[str]] = re.compile(
    r"\b(?:_{2}import_{2}|import_module|run_module)\s*\(\s*(['\"])_?pytest(?:\.\w+)*\1"
)
#: Code that imports or runs a module named only at run time, or runs a
#: string: which program it starts cannot be read from the code.
_DYNAMIC_EXECUTION: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(?:_{2}import_{2}|import_module)\s*\((?!\s*(['\"])[\w.]+\1\s*[,)])[^)]*\)\s*\."),
    re.compile(r"\brun_module\s*\((?!\s*(['\"])[\w.]+\1\s*[,)])"),
    re.compile(r"(?<![\w.])(?:[e]xec|[e]val)\s*\((?!\s*(['\"])[^'\"]*\1\s*\))"),
)
#: The modules whose functions start a process, and ``os``'s such functions;
#: every ``subprocess`` function does.
_OS_MODULE: Final[re.Pattern[str]] = re.compile("os")
_SUBPROCESS_MODULE: Final[re.Pattern[str]] = re.compile("subprocess")
_OS_PROCESS_FUNCTION: Final[re.Pattern[str]] = re.compile(r"(?:system|popen|exec\w*|spawn\w*)")
#: ``sys.argv`` in the code: the words after the code string reach it.
_SYS_ARGV: Final[re.Pattern[str]] = re.compile(r"\bsys\s*\.\s*argv\b")
#: A quoted string in Python code: its content is one word of the run.
_PYTHON_STRING_LITERAL: Final[re.Pattern[str]] = re.compile(r"'([^'\\]*)'|\"([^\"\\]*)\"")

_SHELL_INTERPRETERS: Final[frozenset[str]] = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
#: Cheap pre-check before looking for code fed to an interpreter on stdin.
_INTERPRETER_WORD: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w.-])(?:bash|sh|zsh|dash|ksh|python[\d.]*|source)(?![\w.-])|(?<![^\s;&|(])\.(?=\s)"
    r"|\$\{?\w+\}?[\"']?\s+-(?=\s)"
)  #: ``cat FILE | bash``: the producer that passes a file through unchanged.
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
#: Reads the script from stdin; every later word is positional (review 7 m1).
_SHELL_STDIN_LETTER: Final[str] = "s"


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


def _without_comments(text: str) -> str:
    """The text with each shell comment removed, up to its line's end.

    A ``#`` starts a comment at the start of a word, outside quotes. A script
    read as code is full of them, and an apostrophe in one (``# don't``) read
    as an opening quote swallowed the lines after it, which then failed to
    parse and were judged unseen.
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
        if char == _COMMENT and not in_single and not in_double:
            if index == 0 or text[index - 1].isspace() or text[index - 1] in _COMMENT_AFTER:
                end = text.find("\n", index)
                index = len(text) if end == -1 else end
                continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        out.append(char)
        index += 1
    return "".join(out)


#: PEP 701 (Python 3.12+) splits an f-string into STRING-like parts; older
#: Pythons (this project runs 3.11) tokenize a whole f-string as one STRING,
#: already covered below. ``getattr`` rather than a direct attribute access
#: (review 8 M4): pyright resolves ``tokenize`` against the project's own
#: 3.11 stub, where ``FSTRING_MIDDLE`` does not exist, so a static
#: ``tokenize.FSTRING_MIDDLE`` is a reported error however it is guarded at
#: runtime.
_FSTRING_MIDDLE: Final[int | None] = getattr(tokenize, "FSTRING_MIDDLE", None)
_FSTRING_MIDDLE_TYPE: Final[tuple[int, ...]] = (
    (_FSTRING_MIDDLE,) if _FSTRING_MIDDLE is not None else ()
)


def _without_python_prose(text: str) -> str:
    """Python code judged only for a declared program's name: comments and string content dropped.

    Python's own tokenizer finds every comment and string, so a triple-quoted
    docstring, an f-string and an escaped quote are all read the way Python
    reads them -- unlike a hand-rolled quote toggle, which a single stray
    quote character (inside a docstring, say) can desynchronise for the rest
    of the file. A program's name inside a string is data, not a line that
    runs it, and a scan too coarse to parse the file in full must not read
    it as one (review 7 M2). A file that fails to tokenize (a syntax error)
    is scanned unchanged: the same behaviour as before this fix.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return text
    line_starts = [0]
    for line in text.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))
    chars = list(text)
    blanked_types = {tokenize.STRING, tokenize.COMMENT, *_FSTRING_MIDDLE_TYPE}
    for token in tokens:
        if token.type not in blanked_types:
            continue
        start = line_starts[token.start[0] - 1] + token.start[1]
        end = line_starts[token.end[0] - 1] + token.end[1]
        # The string's own quotes stay, so later text is still read as code.
        edge = 1 if token.type == tokenize.STRING else 0
        for index in range(start + edge, end - edge):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


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


def _invocations(
    command: str, depth: int = 0, positional: Sequence[str] | None = None
) -> Iterator[tuple[str, list[str], str]]:
    """Every ``(program, arguments, segment)`` the command would run.

    Line continuations are joined here as well as at ``get_bash_command``:
    the code string inside ``bash -c '...'`` never passed through that
    boundary, and joining twice changes nothing. ``positional`` is the argv
    of the script this code is, which ``$@`` and ``$1`` expand to; outside a
    script they stay unseen. The paths the code writes come first, as
    ``_WRITES``, so code read from one of them is judged unseen. Code past
    the parse meter is ``_OVER_BUDGET`` and nothing else (review 8 B1).
    """
    if not _charge(command):
        yield _OVER_BUDGET, [], command[:_QUOTED_SEGMENT_LENGTH]
        return
    text = _without_comments(_ansi_c_to_single_quoted(normalise_line_continuations(command)))
    scan_target = strip_inert_spans(text)
    written = _written_paths(scan_target)
    if written:
        yield _WRITES, written, ""
    has_interpreter = _INTERPRETER_WORD.search(scan_target) is not None
    # A Python heredoc's body is code for `_code_on_stdin` to judge, not a
    # shell segment of its own, so it is blanked before the command is split
    # into segments below -- but `_code_on_stdin` itself needs the ORIGINAL
    # text to find the heredoc in the first place.
    parse_target = _without_python_heredocs(scan_target) if has_interpreter else scan_target
    protected, substitutions = _protect_substitutions(parse_target)
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
    word_lists = [split for _, split in parsed if split]
    variables = _variables(word_lists, positional)
    renames = _renamed_commands(word_lists, parse_target)
    if has_interpreter:
        # A producer word built from a variable the command sets is expanded
        # too, so `F=f; cat $F | bash` reads f, not an absent path
        # (review 7 m1).
        yield from _code_on_stdin(scan_target, depth, variables, positional)
    nested = _double_quoted_substitutions(parse_target) + [
        _substitution_code(original) for original in substitutions
    ]
    for code in nested:
        yield from _nested(code, code, depth)
    for segment, split in parsed:
        if split is None:
            yield _UNPARSED, [], segment
            continue
        expanded = _expand_variables(split, variables, positional)
        for background in _split_background(_renamed(expanded, renames)):
            yield from _resolve(background, segment, depth)


def _written_paths(text: str) -> list[str]:
    """Each path the code writes with ``>``, ``>>``, ``&>`` or ``tee``, normalised."""
    targets = [found.group("target") for found in _WRITE_REDIRECT.finditer(text)]
    for found in _TEE.finditer(text):
        targets.extend(word for word in found.group("operands").split() if not _is_flag(word))
    return [
        posixpath.normpath(target.strip(_QUOTES)) for target in targets if target.strip(_QUOTES)
    ]


def _renamed_commands(word_lists: Iterable[list[str]], text: str) -> dict[str, list[str]]:
    """The commands an alias or ``hash -p`` makes a name run (review 6 n5).

    An alias is expanded only under ``shopt -s expand_aliases``: a
    non-interactive shell expands none otherwise.
    """
    renames: dict[str, list[str]] = {}
    expands_aliases = _EXPAND_ALIASES.search(text) is not None
    for words in word_lists:
        if expands_aliases and words[0] == _ALIAS:
            for definition in words[1:]:
                name, separator, value = definition.partition(_VALUE_SEPARATOR)
                if separator and name:
                    renames[name] = value.split()
        elif len(words) >= _HASH_WORDS and words[0] == _HASH and words[1] == _HASH_PATH_FLAG:
            renames[words[3]] = [words[2]]
    return renames


def _renamed(words: list[str], renames: Mapping[str, list[str]]) -> list[str]:
    """The words with a renamed command word replaced by what it runs."""
    if not words or words[0] not in renames:
        return words
    return renames[words[0]] + words[1:]


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


def _variables(
    word_lists: Iterable[list[str]], positional: Sequence[str] | None = None
) -> dict[str, list[str]]:
    """The values each variable the command sets can take.

    ``P=pytest`` and ``export P=pytest`` give one value; ``for t in a b``
    gives each word in turn (review 5 n4). Only a command that consists of
    assignments sets a variable: ``FOO=1 pytest`` sets FOO for pytest alone.
    A loop over a listing of changed files gives each file, never none: an
    empty list runs the body no times (review 6 M2). In a script, ``$1`` to
    ``$9`` are its arguments, and empty past the last.
    """
    found: dict[str, list[str]] = {}
    if positional is not None:
        for number in range(1, _POSITIONAL_PARAMETERS + 1):
            found[str(number)] = [positional[number - 1] if number <= len(positional) else ""]
    for words in word_lists:
        if len(words) >= _FOR_HEADER_WORDS and words[0] == _FOR and words[2] == _FOR_IN:
            values = words[_FOR_HEADER_WORDS:]
            if len(values) == 1 and _lists_changed_files(values[0]):
                values = [_CHANGED_FILES]
            found[words[1]] = values
            continue
        body = [w for w in words[1:] if not _is_flag(w)] if words[0] in _DECLARATIONS else words
        if body and all(_ASSIGNMENT.match(word) for word in body):
            for word in body:
                name, _, value = word.partition(_VALUE_SEPARATOR)
                # `CMD="$CMD --flag"` builds on the value set before it.
                expanded = _VARIABLE.sub(
                    lambda match: _single_value(match, found), _with_defaults(value, found)
                )
                found[name] = [expanded]
    return found


def _with_defaults(word: str, variables: Mapping[str, list[str]]) -> str:
    """``${NAME:-word}`` and ``${NAME:=word}`` read as the value set, else as ``word``.

    With the colon, an empty value counts as unset, as it does in bash.
    """

    def _default(found: re.Match[str]) -> str:
        values = variables.get(found.group("name"))
        if values is None or len(values) != 1 or (found.group("colon") and not values[0]):
            return found.group("default")
        return values[0]

    return _DEFAULT_EXPANSION.sub(_default, word)


def _expand_variables(
    words: list[str],
    variables: Mapping[str, list[str]],
    positional: Sequence[str] | None = None,
) -> list[str]:
    """Each word with the variables the command sets expanded.

    A whole-word ``$P`` is split as bash splits an unquoted expansion; one
    with several values becomes a brace group, so each value is judged. A
    variable the command does not set is left as written. In a script,
    ``"$@"`` is each of its arguments.
    """
    expanded: list[str] = []
    for original in words:
        if positional is not None and original in _ALL_POSITIONAL:
            expanded.extend(positional)
            continue
        word = _with_defaults(original, variables)
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
    if command_word(argv[0]) == _PRINTF:
        return _printf_output(rest).replace(_ESCAPED_NEWLINE, "\n")
    while rest and rest[0] in _ECHO_OPTIONS:
        rest = rest[1:]
    return " ".join(rest).replace(_ESCAPED_NEWLINE, "\n")


def _printf_output(arguments: Sequence[str]) -> str:
    """What ``printf FORMAT ARGS`` prints: each conversion takes the next argument.

    The format is reused while arguments remain, as bash does (``printf
    'pytest %s\\n' tests`` prints ``pytest tests``, review 6). ``printf -v``
    assigns rather than prints.
    """
    if arguments and arguments[0] == END_OF_OPTIONS:
        arguments = arguments[1:]
    if not arguments or arguments[0] == _PRINTF_ASSIGN:
        return ""
    template, values = arguments[0], list(arguments[1:])
    printed: list[str] = []
    while True:
        used = last = 0
        for found in _PRINTF_CONVERSION.finditer(template):
            printed.append(template[last : found.start()])
            last = found.end()
            if found.group(0) == _PRINTF_PERCENT:
                printed.append(_PRINTF_PERCENT[0])
                continue
            printed.append(values[used] if used < len(values) else "")
            used += 1
        printed.append(template[last:])
        values = values[used:]
        if not values or used == 0:
            return "".join(printed)


def _reads_code_from_stdin(words: list[str]) -> bool:
    """Whether this runs shell code from stdin: no script, or a stdin script, and no ``-c``.

    ``bash``, ``bash -s``, ``bash /dev/stdin`` and ``source /dev/stdin`` all
    do (review 6 m2).
    """
    argv = _strip_prefixes(words)
    if not argv:
        return False
    name = command_word(argv[0])
    if name in _SOURCE_COMMANDS:
        operands = _without_redirects(argv[1:])
        return bool(operands) and operands[0] in _STDIN_PATHS
    if name not in _SHELL_INTERPRETERS:
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
            return argument in _STDIN_PATHS
        if not argument.startswith(_LONG_FLAG_PREFIX):
            if _SHELL_CODE_LETTER in argument[1:]:
                return False
            # `-s`: the script comes from stdin, so a later word is
            # positional, not a name to check (review 7 m1).
            if _SHELL_STDIN_LETTER in argument[1:]:
                return True
        index += 1
    return True


def _without_redirects(words: Sequence[str]) -> list[str]:
    """The words with each redirection, and a target in the next word, removed."""
    kept: list[str] = []
    index = 0
    while index < len(words):
        redirect = _REDIRECT.match(words[index])
        if redirect is not None:
            index += 1 if redirect.group("target") else 2
            continue
        kept.append(words[index])
        index += 1
    return kept


def _is_a_listing(stages: Sequence[str]) -> bool:
    """Whether a pipeline writes only the paths a change touches (review 5 n3, review 6 M2).

    ``git diff --name-only``, optionally filtered by ``grep``, ``sort`` or
    ``uniq``: its output is a set of changed files, which is the targeted run
    the guidance asks for. A listing steered to print other words is none: a
    format, a line prefix, an output file, the empty tree (every tracked
    file), a word built at run time, or ``grep --label``.
    """
    try:
        words = [shlex.split(stage) for stage in stages]
    except ValueError as error:
        logger.debug("Listing not recognised, unsplittable (%s)", error)
        return False
    if not words or not all(words):
        return False
    first = _strip_prefixes(words[0])
    if not first or command_word(first[0]) != _GIT:
        return False
    git_words = first[1:]
    subcommands = [word for word in git_words if not _is_flag(word)]
    return (
        bool(subcommands)
        and subcommands[0] == _GIT_LISTING_SUBCOMMAND
        and _GIT_NAME_ONLY in git_words
        and not any(_steers_a_listing(word) for word in git_words)
        and all(
            command_word(stage[0]) in _LIST_FILTERS
            and not any(word.startswith(_GREP_LABEL) for word in stage)
            for stage in words[1:]
        )
    )


def _steers_a_listing(word: str) -> bool:
    """A git word that makes a listing print more than the changed paths.

    A substitution whose code is exactly ``git merge-base <rev>...`` is an
    exception (review 7 m3): it always prints a commit, never the empty
    tree, so ``git diff --name-only "$(git merge-base main HEAD)" -- tests``
    means the same as ``git diff --name-only main...HEAD -- tests``.
    """
    if _is_merge_base_substitution(word):
        return False
    if word.startswith(_GIT_STEERING_OPTIONS) or any(char in word for char in _UNBUILT_CHARACTERS):
        return True
    if _PLACEHOLDER_OPEN in word:
        return True
    return any(
        len(run) >= _ABBREVIATED_OBJECT and _EMPTY_TREE.startswith(run.lower())
        for run in _HEX_RUN.findall(word)
    )


def _is_merge_base_substitution(word: str) -> bool:
    """Whether a word is a substitution whose code is EXACTLY ``git merge-base <rev>...``.

    Split on the same boundaries a command is split on first (review 8 minor
    m2): the code must be exactly ONE command, or ``git merge-base x HEAD ||
    echo <empty tree>`` -- accepted before because it merely STARTED with
    ``git merge-base`` -- resolves to the empty tree's listing whenever the
    revision does not exist, and a trailing ``| git mktree`` runs something
    else again. A flag is refused too: ``-a`` prints every merge base, not
    one, and ``--fork-point`` uses the reflog, so neither is "as safe as a
    literal SHA" the way a bare ``git merge-base <rev> <rev>`` is.
    """
    if not word.startswith((_SUBSTITUTION_OPENER, _BACKTICK)):
        return False
    code = _substitution_code(word)
    segments = split_unquoted(code, _COMMAND_BOUNDARIES)
    if len(segments) != 1:
        return False
    try:
        words = shlex.split(segments[0])
    except ValueError:
        return False
    if len(words) < 3 or command_word(words[0]) != _GIT or words[1] != _GIT_MERGE_BASE_SUBCOMMAND:
        return False
    return all(operand == END_OF_OPTIONS or not _is_flag(operand) for operand in words[2:])


def _lists_changed_files(word: str) -> bool:
    """Whether a substitution operand is a listing of changed files."""
    if not word.startswith((_SUBSTITUTION_OPENER, _BACKTICK)):
        return False
    return _is_a_listing(split_unquoted(_substitution_code(word), _PIPE))


def _xargs_skips_empty_input(words: Sequence[str]) -> bool:
    """Whether ``xargs`` has ``-r``/``--no-run-if-empty``: plain xargs runs once on no input."""
    index = 1
    while index < len(words):
        word = words[index]
        index += 1
        if word == END_OF_OPTIONS or not _is_flag(word):
            return False
        if word == _XARGS_NO_RUN_IF_EMPTY:
            return True
        if word.startswith(_LONG_FLAG_PREFIX):
            index += 1 if word in _XARGS_VALUE_FLAGS else 0
            continue
        for position, letter in enumerate(word[1:], start=1):
            if letter == _XARGS_NO_RUN_LETTER:
                return True
            if letter in _XARGS_VALUE_LETTERS:
                index += 1 if position == len(word) - 1 else 0
                break
    return False


def _consumers_of_a_listing(text: str) -> frozenset[str]:
    """Each ``xargs -r`` stage whose stdin is a listing of changed files, as written.

    Without ``-r`` an empty listing runs the command bare, so such a stage is
    not a targeted run (review 6 M2).
    """
    consumers: set[str] = set()
    for pipeline in split_unquoted(text, _PIPELINE_BOUNDARIES):
        stages = split_unquoted(pipeline, _PIPE)
        for position in range(1, len(stages)):
            try:
                consumer = _strip_prefixes(shlex.split(stages[position]))
            except ValueError as error:
                logger.debug("Consumer left to the unparsed check (%s)", error)
                continue
            if (
                consumer
                and consumer[0] == _XARGS
                and _xargs_skips_empty_input(consumer)
                and _is_a_listing(stages[:position])
            ):
                consumers.add(stages[position].strip())
    return frozenset(consumers)


def _python_stdin_argv(words: list[str]) -> list[str] | None:
    """The argv of Python code read from stdin (no script, ``-c`` or ``-m``), else None.

    ``python3 - a b`` reads code from stdin with ``sys.argv[1:]`` of
    ``['a', 'b']``; ``python3 script.py`` reads DATA from stdin.
    """
    argv = _strip_prefixes(words)
    if not argv:
        return None
    if _PYTHON_INTERPRETER.match(command_word(argv[0])) is None:
        # `"$PY" - <<'EOF'`: an interpreter named at run time, reading stdin.
        named_at_run_time = _is_built_at_run_time(argv[0].strip(_QUOTES))
        if not (named_at_run_time and len(argv) > 1 and argv[1] in _STDIN_PATHS):
            return None
    rest = argv[1:]
    index = 0
    while index < len(rest):
        argument = rest[index]
        redirect = _REDIRECT.match(argument)
        if redirect is not None:
            index += 1 if redirect.group("target") else 2
            continue
        if argument in _STDIN_PATHS:
            return _without_redirects(rest[index + 1 :])
        if not _is_flag(argument):
            return None
        option = _python_value_option(argument)
        if option is not None:
            letter, attached = option
            if letter in (_PYTHON_CODE_LETTER, _PYTHON_MODULE_LETTER):
                return None
            index += 1 if attached else 2
            continue
        index += 1
    return []


def _python_value_option(word: str) -> tuple[str, str] | None:
    """The first value-taking letter of a short Python option cluster, and its attached value.

    ``-Ic code`` is ``-I -c code``, ``-Bm pytest`` is ``-B -m pytest`` and
    ``-Wignore`` carries its value (review 6 m3). None for a long option or
    a cluster that takes no value.
    """
    if word.startswith(_LONG_FLAG_PREFIX) or not _is_flag(word):
        return None
    for position, letter in enumerate(word[1:], start=1):
        if letter in _PYTHON_VALUE_LETTERS:
            return letter, word[position + 1 :]
    return None


@dataclass(frozen=True, slots=True)
class _Output:
    """What a producer writes into a pipe: its literal text, one file, or neither.

    Neither means the producer is not understood, so the code it feeds
    cannot be seen.
    """

    text: str | None = None
    path: str | None = None


#: Programs whose output is shell STATE (exports, aliases, functions) to set
#: up an interpreter or a tool, never a QA command: none of them read a file
#: (review 7 m2). Matched on the exact SUBCOMMAND the reference documents,
#: never on the program's name alone (review 8 M3): trusting a producer
#: blindly is a decision about a specific program's own behaviour, not a
#: structural property the command line can prove, and a program's OTHER
#: subcommands (``pyenv exec``, ``direnv exec``, ``conda run``) run an
#: arbitrary command, not shell state.
_ENV_SETUP_SUBCOMMANDS: Final[Mapping[str, frozenset[str]]] = {
    "pyenv": frozenset({"init"}),
    "rbenv": frozenset({"init"}),
    "nodenv": frozenset({"init"}),
    "direnv": frozenset({"export"}),
    "brew": frozenset({"shellenv"}),
}
#: ``conda shell.bash hook``, ``conda shell.zsh hook``, ...: the shell name
#: varies, the ``shell.`` prefix and the trailing ``hook`` do not.
_CONDA: Final[str] = "conda"
_CONDA_SHELL_PREFIX: Final[str] = "shell."
_CONDA_HOOK_WORD: Final[str] = "hook"
#: ``ssh-agent`` with only its own flags (``-s``, ``-c``: which shell syntax
#: to print) and no command of its own -- ``ssh-agent <command>`` runs
#: ``<command>``, which is not shell setup.
_SSH_AGENT: Final[str] = "ssh-agent"
_SSH_AGENT_FLAGS: Final[frozenset[str]] = frozenset({"-s", "-c"})
#: A shell completion script is the one shape of this that IS structural,
#: whatever program prints it: `<anything> completion <shell>` is always
#: shell function definitions, under a convention many tools share -- but
#: only in exactly this position, with the shell name the only operand after
#: it (review 8 M3): `cat f completion` is not a completion producer just
#: because the word `completion` appears somewhere in its arguments.
_COMPLETION_WORD: Final[str] = "completion"
_COMPLETION_WORDS: Final[int] = 2


def _is_environment_setup_producer(words: Sequence[str]) -> bool:
    """Whether a producer only sets up shell state, never a QA command (review 7 m2, review 8 M3).

    ``eval "$(ssh-agent -s)"``, ``eval "$(pyenv init -)"`` and
    ``source <(kubectl completion bash)`` run no QA and cannot: none of
    these read a file, so a fail-closed deny meant for code that cannot be
    SEEN protects nothing here. Denying them anyway (the direction taken by
    review 6 M2 for an unknown producer) is sound for a project file, but
    has no escape for shell setup, since this handler holds no state
    between one Bash call and the next. A producer word that is a PATH
    (``./ssh-agent``, ``fx/ssh-agent``) is never trusted: ``command_word``
    strips the directory, so a same-named project file would otherwise pass
    as the real tool.
    """
    if not words:
        return False
    head = words[0]
    if _PATH_SEPARATOR in head:
        return False
    name = command_word(head)
    rest = words[1:]
    if name == _SSH_AGENT:
        return all(word in _SSH_AGENT_FLAGS for word in rest)
    if name == _CONDA:
        return (
            len(rest) == 2
            and rest[0].startswith(_CONDA_SHELL_PREFIX)
            and rest[1] == _CONDA_HOOK_WORD
        )
    subcommands = _ENV_SETUP_SUBCOMMANDS.get(name)
    if subcommands is not None:
        return bool(rest) and rest[0] in subcommands
    return len(rest) == _COMPLETION_WORDS and rest[0] == _COMPLETION_WORD


def _producer_output(words: list[str]) -> _Output:
    """What a pipe producer writes (review 6 m2).

    ``echo``/``printf`` write their arguments; ``cat FILE`` writes one file,
    and ``cat`` with a heredoc writes its body, whose lines are judged as
    commands already. Anything else (``cat f g``, ``cat < f``, ``tee``,
    ``awk``, ``grep``, a program) is not understood.
    """
    printed = _literal_output(words)
    if printed is not None:
        return _Output(text=printed)
    argv = _strip_prefixes(words)
    if not argv or command_word(argv[0]) != _CAT:
        return _Output()
    rest = argv[1:]
    if rest and all(_HEREDOC_OPENER.match(word) for word in rest):
        return _Output(text="")
    if len(rest) == 2 and rest[0] == _HERE_STRING:
        return _Output(text=rest[1])
    if len(rest) == 1 and not _is_flag(rest[0]) and _REDIRECT.match(rest[0]) is None:
        return _Output(path=rest[0])
    return _Output()


def _code_on_stdin(
    text: str,
    depth: int,
    variables: Mapping[str, list[str]] | None = None,
    positional: Sequence[str] | None = None,
) -> Iterator[tuple[str, list[str], str]]:
    """Code a shell or Python reads on stdin: piped, from ``<(...)``, or a Python heredoc.

    Literal code (from ``echo``/``printf``) is judged here; a file (``cat
    f | bash``) is yielded as ``_CODE_FILE`` for the caller, which knows the
    directory, to read; a producer that is not understood is yielded as
    ``_UNREAD_CODE``. A shell heredoc needs nothing here: its body is not
    blanked, so its lines are judged as commands already. Text that cannot
    be split into words is left to :func:`_invocations`, which judges the
    same segment as unparsed. A producer's own words are expanded against
    ``variables`` first, so ``F=f; cat $F | bash`` reads ``f`` rather than
    treating the path as absent (review 7 m1).
    """
    known = variables or {}
    for pipeline in split_unquoted(text, _PIPELINE_BOUNDARIES):
        try:
            stages = [shlex.split(stage) for stage in split_unquoted(pipeline, _PIPE)]
        except ValueError as error:
            logger.debug("Pipeline left to the unparsed check (%s): %r", error, pipeline)
            continue
        for producer, consumer in pairwise(stages):
            producer = _expand_variables(producer, known, positional)
            yield from _fed(_producer_output(producer), consumer, pipeline, depth, producer)
    for consumer, producer_code in _process_substitutions(text):
        try:
            producer = shlex.split(producer_code)
        except ValueError as error:
            logger.debug("Substitution left to the unparsed check (%s)", error)
            continue
        producer = _expand_variables(producer, known, positional)
        yield from _fed(_producer_output(producer), consumer, producer_code, depth, producer)
    for heredoc in _python_heredocs(text):
        yield from _python_code_runs(heredoc.body, heredoc.argv, heredoc.body, depth)


def _process_substitutions(text: str) -> Iterator[tuple[list[str], str]]:
    """Each ``<(producer)`` that feeds a command code, as ``(consumer words, producer code)``.

    ``bash < <(p)`` reads it on stdin and ``bash <(p)`` and ``. <(p)`` run it
    as the script (review 6 m2); either way the consumer is given as reading
    ``/dev/stdin``. One pass tracks where each command starts, and a
    substitution that feeds a command is stepped over whole, so the work is
    linear in the text.
    """
    command_start = 0
    index = 0
    while index < len(text):
        if text.startswith(_PROCESS_SUBSTITUTION_OPENER, index):
            consumer = _process_substitution_consumer(text[command_start:index])
            if consumer:
                code_start = index + len(_PROCESS_SUBSTITUTION_OPENER)
                end = _closing_paren(text, code_start)
                yield [*consumer, _STDIN_DEVICE], text[code_start:end]
                index = end + 1
                continue
        if text[index] in _COMMAND_START_CHARACTERS:
            command_start = index + 1
        index += 1


def _process_substitution_consumer(head: str) -> list[str]:
    """The words of the command a ``<(...)`` belongs to, when it may read code from it."""
    try:
        consumer = shlex.split(head)
    except ValueError as error:
        logger.debug("Consumer left to the unparsed check (%s)", error)
        return []
    if consumer and consumer[-1] == _STDIN_REDIRECT_WORD:
        consumer = consumer[:-1]
    fed = [*consumer, _STDIN_DEVICE]
    if _reads_code_from_stdin(fed) or _python_stdin_argv(fed) is not None:
        return consumer
    return []


def _fed(
    output: _Output,
    consumer: list[str],
    segment: str,
    depth: int,
    producer: Sequence[str] = (),
) -> Iterator[tuple[str, list[str], str]]:
    """What a consumer runs when a producer's output is its code.

    A producer this handler cannot read is unseen, UNLESS it only sets up
    shell state (review 7 m2): that runs no QA, and cannot.
    """
    python_argv = _python_stdin_argv(consumer)
    if python_argv is None and not _reads_code_from_stdin(consumer):
        return
    kind = _SHELL_CODE if python_argv is None else _PYTHON_CODE
    if output.text is not None:
        yield from _code_runs(kind, output.text, python_argv or [], segment, depth)
    elif output.path is not None:
        yield _CODE_FILE, [kind, output.path, *(python_argv or [])], segment
    elif not _is_environment_setup_producer(producer):
        yield _UNREAD_CODE, [], segment


def _code_runs(
    kind: str, code: str, argv: Sequence[str], segment: str, depth: int
) -> Iterator[tuple[str, list[str], str]]:
    """What code of one kind runs: shell code nested, Python code read for its runs."""
    if kind == _PYTHON_CODE:
        yield from _python_code_runs(code, argv, segment, depth)
    else:
        yield from _nested(code, segment, depth)


@dataclass(frozen=True, slots=True)
class _PythonHeredoc:
    """A heredoc Python reads as its code: its argv, its body, and where the body lies."""

    argv: list[str]
    body: str
    start: int
    end: int


def _python_heredocs(text: str) -> Iterator[_PythonHeredoc]:
    """Each heredoc whose receiver is Python reading its code from stdin.

    Quoted or not: whether the OUTER shell expands the body does not change
    what the receiver does with it. A receiver that cannot be split is
    skipped; its line is judged as unparsed by :func:`_invocations`. The
    receiver is judged before the body is sought, so openers that feed data
    cost nothing more.
    """
    for found in _HEREDOC_OPENER.finditer(text):
        line_start = text.rfind("\n", 0, found.start()) + 1
        body_start = text.find("\n", found.end())
        if body_start == -1:
            continue
        stages = split_unquoted(text[line_start : found.start()], (*_PIPELINE_BOUNDARIES, *_PIPE))
        try:
            receiver = shlex.split(stages[-1]) if stages else []
        except ValueError as error:
            logger.debug("Heredoc receiver left to the unparsed check (%s)", error)
            continue
        argv = _python_stdin_argv(receiver)
        if argv is None:
            continue
        delimiter = found.group("delim")
        body: list[str] = []
        end = body_start + 1
        for line in text[body_start + 1 :].split("\n"):
            candidate = line.lstrip(_TAB) if found.group("strip") else line
            if candidate == delimiter:
                break
            body.append(candidate)
            end += len(line) + 1
        yield _PythonHeredoc(argv, "\n".join(body), body_start + 1, end)


def _without_python_heredocs(text: str) -> str:
    """The text with each Python heredoc's body blanked (review 6).

    Its lines are Python, judged as Python by :func:`_code_on_stdin`; read as
    shell commands, ``print('pytest')`` was a bare pytest run.
    """
    if _HEREDOC_OPENER.search(text) is None:
        return text
    blanked = list(text)
    for heredoc in _python_heredocs(text):
        for index in range(heredoc.start, min(heredoc.end, len(text))):
            if blanked[index] != "\n":
                blanked[index] = " "
    return "".join(blanked)


def _strip_prefixes(argv: list[str]) -> list[str]:
    """Drop assignments, keywords and wrappers until the command word leads."""
    return _peel(argv)[0]


def _peel(argv: list[str]) -> tuple[list[str], list[str]]:
    """Drop assignments, keywords and wrappers; also return each ``env -C`` directory.

    ``env -C DIR cmd`` runs ``cmd`` in DIR (review 5 n3), so the directories
    are returned, in order, for the caller to apply to that command alone:
    each ``-C`` moves on from the one before (review 6 n5).
    """
    directories: list[str] = []
    while True:
        start = 0
        while start < len(argv):
            if _ASSIGNMENT.match(argv[start]) or argv[start] in _SHELL_KEYWORDS:
                start += 1
            elif argv[start] == _FUNCTION:
                # `function t { pytest; }`: the body is judged as `t() { ...; }` is.
                start += _FUNCTION_HEADER_WORDS
            elif argv[start] == _COPROC:
                # `coproc pytest` and `coproc NAME { pytest; }` run pytest.
                named = start + 2 < len(argv) and argv[start + 2] in _GROUP_OPENERS
                start += 2 if named else 1
            else:
                break
        if (
            start + 1 < len(argv)
            and argv[start] == _COMMAND
            and argv[start + 1] in _COMMAND_LOOKUP_FLAGS
        ):
            # `command -v pytest` prints where pytest is; it runs nothing.
            return argv[start:], directories
        _, peeled = peel_command_wrappers(argv[start:])
        if start == 0 and peeled == 0:
            return argv, directories
        directories.extend(_env_directories(argv[start : start + peeled]))
        argv = argv[start + peeled :]


def _env_directories(wrapper_words: Sequence[str]) -> list[str]:
    """Each directory an ``env -C DIR`` / ``--chdir=DIR`` among peeled words moves to.

    A short cluster is read letter by letter: in ``env -iC DIR`` the ``C``
    takes the next word, and in ``-iCDIR`` the rest of the word (review 6 m3).
    """
    directories: list[str] = []
    in_env = False
    index = 0
    while index < len(wrapper_words):
        word = wrapper_words[index]
        index += 1
        if word == LONE_DASH:
            continue
        if not _is_flag(word):
            in_env = command_word(word) == _ENV
            continue
        if not in_env or word == END_OF_OPTIONS:
            continue
        flag, separator, value = word.partition(_FLAG_VALUE_SEPARATOR)
        if flag in _ENV_CHDIR_FLAGS:
            if separator:
                directories.append(value)
            elif index < len(wrapper_words):
                directories.append(wrapper_words[index])
                index += 1
            continue
        if word.startswith(_LONG_FLAG_PREFIX):
            continue
        for position, letter in enumerate(word[1:], start=1):
            if letter not in (_ENV_CHDIR_LETTER, _ENV_UNSET_LETTER):
                continue
            attached = word[position + 1 :]
            if not attached and index < len(wrapper_words):
                attached = wrapper_words[index]
                index += 1
            if letter == _ENV_CHDIR_LETTER:
                directories.append(attached)
            break
    return directories


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
    argv, directories = _peel(words)
    if not directories:
        yield from _resolve_command(argv, segment, depth, hops)
        return
    yield _CD_PUSH, [directories[0]], segment
    for directory in directories[1:]:
        yield _CD, [directory], segment
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
        yield from _resolve_opaque(unquoted, rest, segment, depth, hops)
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
        yield from _code_of(_SHELL_CODE, " ".join(rest), [], segment, depth)
        return

    if name in _SOURCE_COMMANDS:
        if rest:
            yield from _resolve_script(_SHELL_CODE, rest, segment, depth)
        return

    if name == _XARGS:
        # The words xargs reads from stdin are unseen, and may be none.
        tail = [*rest, _STDIN_WORDS]
        yield from _resolve_run_tail(tail, 0, _XARGS_VALUE_FLAGS, segment, depth, hops)
        return

    launcher = _LAUNCHERS.get(name)
    if launcher is not None:
        yield from _resolve_launcher(launcher, rest, segment, depth, hops)
        return

    if name == _PARALLEL:
        yield from _resolve_parallel(rest, segment, depth, hops)
        return

    if name == _FIND:
        yield from _resolve_find(rest, segment, depth, hops)
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

    if _PATH_SEPARATOR in argv[0]:
        # A program run by its path may be a script: its code is read.
        yield _CODE_FILE, [_EXECUTABLE_CODE, argv[0], *rest], segment
        return
    yield _PROGRAM_ALIASES.get(name, name), rest, segment


def _resolve_opaque(
    word: str, rest: list[str], segment: str, depth: int, hops: int
) -> Iterator[tuple[str, list[str], str]]:
    """A command word built at run time: an interpreter when its flags say so, else opaque.

    ``"$PY" -c code`` and ``$SHELL -c code`` run code, judged as Python and
    as shell; ``"$PY" -m mod`` runs the module (review 6 m6). Otherwise the
    word is yielded as ``_OPAQUE``, to be judged as each program the command
    names, with ``rest`` as that program's arguments.
    """
    index = 0
    while index < len(rest) and _is_flag(rest[index]):
        option = _python_value_option(rest[index])
        if option is None:
            index += 1
            continue
        letter, attached = option
        value_at = index if attached else index + 1
        value = attached or (rest[value_at] if value_at < len(rest) else "")
        after = rest[value_at + 1 :]
        if letter == _PYTHON_CODE_LETTER:
            yield from _python_code_runs(value, after, segment, depth)
            yield from _code_of(_SHELL_CODE, value, [], segment, depth)
            return
        if letter == _PYTHON_MODULE_LETTER:
            if value:
                yield from _resolve([value, *after], segment, depth, hops + 1)
            return
        index = value_at + 1
    if index < len(rest) and rest[index] in _STDIN_PATHS:
        # `"$PY" - <<'EOF'` runs code from stdin, judged where it is fed.
        return
    yield _OPAQUE, [word, *rest], segment


def _whole_substitution(word: str) -> str | None:
    """The code of a word that is one whole ``$(...)`` or backtick substitution, else None."""
    if word.startswith(_SUBSTITUTION_OPENER) and not word.startswith(_ARITHMETIC_OPENER):
        end = _closing_paren(word, len(_SUBSTITUTION_OPENER))
        return word[len(_SUBSTITUTION_OPENER) : end] if end == len(word) - 1 else None
    if len(word) > 1 and word.startswith(_BACKTICK) and word.find(_BACKTICK, 1) == len(word) - 1:
        return word[1:-1]
    return None


def _code_of(
    kind: str, code: str, argv: Sequence[str], segment: str, depth: int
) -> Iterator[tuple[str, list[str], str]]:
    """What code handed to ``eval`` or ``-c`` runs.

    Code that is one whole substitution is the OUTPUT of its producer
    (``bash -c "$(cat f)"``, review 6 m2): judged as a pipe's producer is.
    A producer this handler cannot read is unseen, unless it only sets up
    shell state (``eval "$(ssh-agent -s)"``), which runs no QA (review 7 m2).
    """
    inner = _whole_substitution(code.strip())
    if inner is None:
        yield from _code_runs(kind, code, argv, segment, depth)
        return
    try:
        producer = shlex.split(inner)
    except ValueError as error:
        logger.debug("Code substitution judged unparsed (%s)", error)
        yield _UNPARSED, [], segment
        return
    output = _producer_output(producer)
    if output.text is not None:
        yield from _code_runs(kind, output.text, argv, segment, depth)
    elif output.path is not None:
        yield _CODE_FILE, [kind, output.path, *argv], segment
    elif not _is_environment_setup_producer(producer):
        yield _UNREAD_CODE, [], segment


def _resolve_script(
    kind: str, words: list[str], segment: str, depth: int
) -> Iterator[tuple[str, list[str], str]]:
    """``bash script args``, ``source script args`` or ``python3 script args``: the script runs.

    Its code is read by the caller, with ``args`` as its argv. A stdin
    script (``/dev/stdin``, ``/dev/fd/0``, ``-``) runs a here-string or the
    file stdin is redirected from; piped code is judged by
    :func:`_code_on_stdin`. Another descriptor cannot be seen.
    """
    script, arguments = words[0], _without_redirects(words[1:])
    if script in _STDIN_PATHS:
        for index, word in enumerate(words[1:], start=1):
            following = words[index + 1] if index + 1 < len(words) else ""
            if word.startswith(_HERE_STRING):
                code = word[len(_HERE_STRING) :] or following
                # A whole substitution is its producer's output (review 7 m1):
                # `bash /dev/stdin <<< "$(cat f)"` reads f.
                yield from _code_of(kind, code, arguments, segment, depth)
                return
            stdin = _STDIN_REDIRECT.match(word)
            if stdin is not None:
                path = stdin.group("target") or following
                yield _CODE_FILE, [kind, path, *arguments], segment
                return
        return
    if script.startswith(_DESCRIPTOR_PREFIX):
        yield _UNREAD_CODE, [], segment
        return
    yield _CODE_FILE, [kind, script, *arguments], segment


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


def _resolve_find(
    rest: list[str], segment: str, depth: int, hops: int
) -> Iterator[tuple[str, list[str], str]]:
    """``find [paths] [tests] -exec cmd {} ;`` (or ``+``) runs ``cmd`` on what find selects.

    ``{}`` is find's start paths, wherever it sits inside a word (GNU find
    replaces it in place: ``{}/``, ``./{}``, review 8 minor m3) -- and
    whatever test narrows them (a ``-name``/``-path`` test can only select a
    SUBSET of the start paths, so a targeted start path stays targeted under
    any narrowing, and this is left for the same downstream check that
    judges a bare ``pytest tests`` as full). A BARE find (no path operand,
    which searches ``.``) has no path text to read at all, so ``{}`` is a
    sentinel this handler cannot place, judged unseen instead.
    ``-execdir``/``-ok``/``-okdir`` are followed the same way as ``-exec``.
    """
    start_paths: list[str] = []
    index = 0
    while index < len(rest) and not _is_flag(rest[index]) and rest[index] not in _FIND_PATH_STOP:
        start_paths.append(rest[index])
        index += 1
    selected = start_paths if start_paths else [_FIND_SELECTED_FILES]
    while index < len(rest):
        word = rest[index]
        index += 1
        if word not in _FIND_EXEC_ACTIONS:
            continue
        action: list[str] = []
        while index < len(rest) and rest[index] not in _FIND_ACTION_TERMINATORS:
            action.append(rest[index])
            index += 1
        index += 1  # step past the `;` or `+` terminator, if one was found
        if not action:
            continue
        argv: list[str] = []
        for action_word in action:
            if _FIND_PLACEHOLDER in action_word:
                argv.extend(action_word.replace(_FIND_PLACEHOLDER, path) for path in selected)
            else:
                argv.append(action_word)
        yield from _resolve(argv, segment, depth, hops + 1)


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


def _imported_names(code: str, module: re.Pattern[str]) -> tuple[set[str], dict[str, str]]:
    """The names Python code binds to a module matching ``module``, and to its members.

    ``import pytest as p`` binds the module to ``p``; ``import _pytest.config``
    binds ``_pytest.config``; ``from pytest import main as m`` binds the
    member ``main`` to ``m`` (review 6 m3).

    Returns:
        The names that hold the module, and each name bound to a member,
        mapped to that member.
    """
    modules: set[str] = set()
    members: dict[str, str] = {}
    for found in _IMPORT.finditer(code):
        source = found.group("module")
        for item in found.group("names").split(_IMPORT_SEPARATOR):
            name, _, alias = (part.strip() for part in item.strip().partition(_IMPORT_ALIAS))
            if source is None and module.fullmatch(name):
                modules.add(alias or name)
            elif source is not None and module.fullmatch(source):
                members[alias or name] = name
    return modules, members


def _calls_a_name(code: str, names: Iterable[str], attribute: str = "") -> bool:
    """Whether code calls one of ``names``, or its ``attribute`` when that is a pattern."""
    spelled = "|".join(re.escape(name) for name in sorted(names))
    if not spelled:
        return False
    member = rf"\s*\.\s*(?:{attribute})" if attribute else ""
    return re.search(rf"(?<![\w.])(?:{spelled}){member}\s*\(", code) is not None


def _calls_pytest(code: str) -> bool:
    """Whether Python code CALLS a pytest entry point, under any name it imported it as."""
    if _PYTEST_IMPORT_CALL.search(code) is not None:
        return True
    modules, members = _imported_names(code, _PYTEST_MODULE)
    entry = "|".join(sorted(_PYTEST_ENTRY_POINTS))
    # `from _pytest import config` binds a module as a member: `config.main()`.
    holders = {_PYTEST, *modules, *members}
    functions = {bound for bound, member in members.items() if member in _PYTEST_ENTRY_POINTS}
    return _calls_a_name(code, holders, entry) or _calls_a_name(code, functions)


def _starts_a_process(code: str) -> bool:
    """Whether Python code calls ``os``/``subprocess`` to start a process, under any name."""
    os_modules, os_members = _imported_names(code, _OS_MODULE)
    process_modules, process_members = _imported_names(code, _SUBPROCESS_MODULE)
    os_functions = {
        bound for bound, member in os_members.items() if _OS_PROCESS_FUNCTION.fullmatch(member)
    }
    return (
        _calls_a_name(code, {_OS_MODULE.pattern, *os_modules}, _OS_PROCESS_FUNCTION.pattern)
        or _calls_a_name(code, {_SUBPROCESS_MODULE.pattern, *process_modules}, r"\w+")
        or _calls_a_name(code, os_functions | set(process_members))
    )


def _process_call_spans(code: str) -> list[str]:
    """The argument text of every call this code makes that starts a process.

    A string literal is only ever an ARGV the code runs when it sits between
    a process-starting call's parentheses (review 7 M2): a docstring or a
    log message elsewhere in the file is never inside one, so it is never a
    candidate, however many words or apostrophes it has. Depth is tracked
    per call with :func:`_closing_paren`, so a nested call's own parens do
    not end the outer one early.
    """
    os_modules, os_members = _imported_names(code, _OS_MODULE)
    process_modules, process_members = _imported_names(code, _SUBPROCESS_MODULE)
    os_functions = {
        bound for bound, member in os_members.items() if _OS_PROCESS_FUNCTION.fullmatch(member)
    }
    os_holders = sorted({_OS_MODULE.pattern, *os_modules})
    process_holders = sorted({_SUBPROCESS_MODULE.pattern, *process_modules})
    bare = sorted(os_functions | set(process_members))
    call_patterns = [
        rf"(?<![\w.])(?:{'|'.join(re.escape(name) for name in os_holders)})"
        rf"\s*\.\s*{_OS_PROCESS_FUNCTION.pattern}\s*\(",
        rf"(?<![\w.])(?:{'|'.join(re.escape(name) for name in process_holders)})"
        rf"\s*\.\s*\w+\s*\(",
    ]
    if bare:
        call_patterns.append(rf"(?<![\w.])(?:{'|'.join(re.escape(name) for name in bare)})\s*\(")
    spans = []
    for call_pattern in call_patterns:
        for match in re.finditer(call_pattern, code):
            start = match.end()
            spans.append(code[start : _closing_paren(code, start)])
    return spans


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
    calls = _calls_pytest(code)
    starts_pytest = _PYTEST in literals and _starts_a_process(code)
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

    A string literal is judged as shell code only when it sits inside a
    process-starting call's own argument list (:func:`_process_call_spans`):
    a docstring or a log message elsewhere in the file is never an argv, and
    parsing one as shell risks an apostrophe reading as an unbalanced quote
    and the prose then being scanned whole for a declared program's name
    (review 7 M2). Code that imports or runs a module named only at run time
    is yielded as ``_OPAQUE``, so the caller can fail closed. pytest is
    yielded as ``_PYTEST_IN_CODE``: its operands are every string in the
    code, so only a path-shaped one targets the run. Code past the parse
    meter is ``_OVER_BUDGET`` and nothing else (review 8 B1).
    """
    if not _charge(code):
        yield _OVER_BUDGET, [], segment
        return
    if _starts_a_process(code):
        for span in _process_call_spans(code):
            for literal in _string_literals(span):
                if not literal.split(maxsplit=1)[1:]:
                    continue
                try:
                    shlex.split(literal)
                except ValueError as error:
                    # Unparsable as shell: prose (an apostrophe, say), not a
                    # command whose absence should fail closed (review 7 M2).
                    logger.debug("Literal left unparsed, not shell (%s): %r", error, literal)
                    continue
                yield from _nested(literal, segment, depth)
    operands = _pytest_in_code(code, argv)
    if operands is not None:
        yield _PYTEST_IN_CODE, operands, segment
    elif any(pattern.search(code) for pattern in _DYNAMIC_EXECUTION):
        yield _OPAQUE, [_PYTEST_IN_CODE, *_string_literals(code), *argv], segment


def _resolve_python(
    rest: list[str], segment: str, depth: int, hops: int
) -> Iterator[tuple[str, list[str], str]]:
    """``python [flags] script args``, ``-m module args``, ``-c code`` or code on stdin.

    A module is resolved like a command, so ``python -m coverage run -m
    pytest`` reaches pytest and ``python -m py.test`` is pytest. Code is
    judged by :func:`_python_code_runs`, whether it comes from ``-c``, a
    here-string, or a file (``python3 < f.py`` and ``python3 f.py``, which
    the caller reads). Short options are read letter by letter, so ``-Ic``
    and ``-Bm`` take their value (review 6 m3).
    """
    index = 0
    stdin_file: str | None = None
    while index < len(rest):
        argument = rest[index]
        following = rest[index + 1] if index + 1 < len(rest) else ""
        if argument.startswith(_HERE_STRING):
            code = argument[len(_HERE_STRING) :] or following
            # A whole substitution is its producer's output (review 7 m1):
            # `python3 <<< "$(cat f)"` reads f.
            yield from _code_of(_PYTHON_CODE, code, [], segment, depth)
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
        if not _is_flag(argument):
            yield from _resolve_script(_PYTHON_CODE, rest[index:], segment, depth)
            return
        option = _python_value_option(argument)
        if option is None:
            index += 1
            continue
        letter, attached = option
        value_at = index if attached else index + 1
        value = attached or following
        after = rest[value_at + 1 :]
        if letter == _PYTHON_MODULE_LETTER:
            if value:
                yield from _resolve([value, *after], segment, depth, hops + 1)
            return
        if letter == _PYTHON_CODE_LETTER:
            # A whole substitution is its producer's output, as for `bash -c`
            # (review 7 m1): `python3 -c "$(cat f)"` reads f.
            yield from _code_of(_PYTHON_CODE, value, after, segment, depth)
            return
        index = value_at + 1
    if stdin_file:
        yield _CODE_FILE, [_PYTHON_CODE, stdin_file], segment


def _resolve_shell(
    rest: list[str], segment: str, depth: int
) -> Iterator[tuple[str, list[str], str]]:
    """``bash script args`` runs the script; ``-c 'code'``, ``<<< 'code'`` and ``< file`` run code.

    ``-s`` reads the script from stdin and takes no script operand: every
    word after it is a positional argument, not a name (review 7 m1), so
    ``bash -s -- tests < f`` reads ``f``, not a directory named ``tests``.
    """
    index = 0
    runs_code = False
    reads_stdin_script = False
    stdin_file = ""
    positional: list[str] = []
    while index < len(rest):
        argument = rest[index]
        following = rest[index + 1] if index + 1 < len(rest) else ""
        if argument.startswith(_HERE_STRING):
            code = argument[len(_HERE_STRING) :] or following
            # A whole substitution is its producer's output (review 7 m1):
            # `bash <<< "$(cat f)"` reads f.
            yield from _code_of(_SHELL_CODE, code, [], segment, depth)
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
            reads_stdin_script = reads_stdin_script or _SHELL_STDIN_LETTER in argument[1:]
            index += 1
            continue
        if argument.startswith(_LONG_FLAG_PREFIX):
            index += 1
            continue
        if reads_stdin_script:
            positional.append(argument)
            index += 1
            continue
        if runs_code:
            yield from _code_of(_SHELL_CODE, argument, [], segment, depth)
            return
        yield from _resolve_script(_SHELL_CODE, rest[index:], segment, depth)
        return
    if stdin_file and not runs_code:
        yield _CODE_FILE, [_SHELL_CODE, stdin_file, *positional], segment


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
    if start is None:
        return None
    resolved = _resolved(operand, here)
    if resolved is None:
        return None
    origin = posixpath.normpath(start)
    if _within(origin, resolved) is not None and resolved != origin:
        return _ABOVE_START
    return _within(resolved, origin)


def _within(path: str, directory: str) -> str | None:
    """``path`` relative to ``directory`` (``.`` for itself), or None when it lies outside."""
    if path == directory:
        return _CURRENT_DIR
    prefix = directory.rstrip(_PATH_SEPARATOR) + _PATH_SEPARATOR
    return path[len(prefix) :] if path.startswith(prefix) else None


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
        return _exists(cwd / operand)
    except ValueError as error:
        # Unrepresentable as a path (an embedded NUL): it names nothing on
        # disk, so it cannot be what the run targets.
        logger.debug("%r is no path, so it targets nothing (%s)", operand, error)
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


def _repository_root(path: str, marked: dict[str, bool]) -> str | None:
    """The nearest directory at or above ``path`` holding a repository marker.

    ``marked`` remembers each directory already looked at, so the operands of
    one event share their lookups. A path the filesystem refuses (a
    component past its name limit, review 6 n1) holds no marker.
    """
    candidate = path
    while True:
        if candidate not in marked:
            marked[candidate] = any(
                _exists(Path(candidate) / marker) for marker in _REPOSITORY_MARKERS
            )
        if marked[candidate]:
            return candidate
        parent = posixpath.dirname(candidate)
        if parent == candidate:
            return None
        candidate = parent


def _exists(path: Path) -> bool:
    """Whether a path exists. One the filesystem refuses to look up does not.

    Absent is the answer that fails closed at every caller: no repository
    marker, no path-like target, and a ``--pyargs`` module left unseen.
    """
    return path_exists(path, unreadable_means=False)


def _names_the_suite(relative: str, full_args: frozenset[str]) -> bool:
    """A path relative to its root that is the root, a ``full_args`` entry or an ancestor of one."""
    return (
        relative == _CURRENT_DIR
        or relative in full_args
        or any(entry.startswith(relative + _PATH_SEPARATOR) for entry in full_args)
    )


def _operand_is_full(
    operand: str,
    full_args: frozenset[str],
    here: Path | None,
    start: Path | None,
    marked: dict[str, bool],
) -> bool:
    """Whether an operand names the whole suite.

    The operand is resolved from the directory the command runs in and judged
    against the repository CONTAINING it (review 4 N6): at its root, at a
    ``full_args`` entry, or at an ancestor of one. Where no repository marker
    is found, the starting directory stands in for the root. At or above the
    starting directory is always full. An operand that cannot be placed at
    all is compared literally, or by its tail when absolute. A word that is
    full wherever it stands is a ``full_words`` entry, never a path.
    """
    placed = _relative_to_start(operand, here, start)
    if placed == _ABOVE_START:
        return True
    resolved = _resolved(operand, here)
    root = _repository_root(resolved, marked) if resolved is not None else None
    relative = _within(resolved, root) if resolved is not None and root is not None else None
    if relative is not None:
        return _names_the_suite(relative, full_args)
    if placed is not None:
        return _names_the_suite(placed, full_args)
    if operand in full_args:
        return True
    return _is_absolute(operand) and any(
        operand.endswith(_PATH_SEPARATOR + entry) for entry in full_args if entry != _CURRENT_DIR
    )


def _resolved(operand: str, here: Path | None) -> str | None:
    """The absolute path an operand names, normalised, or None when that cannot be known."""
    if operand.startswith(_UNSEEN_CD_PREFIXES):
        return None
    if operand.startswith(_PATH_SEPARATOR):
        return posixpath.normpath(operand)
    if here is None:
        return None
    return posixpath.normpath(posixpath.join(here, operand))


def _expand_braces(word: str) -> list[str] | None:
    """Every word bash's brace expansion makes of ``word`` (``a/{b,c}`` is ``a/b a/c``).

    Sequences expand too (``{t..t}ests`` is ``tests``, review 6 m7). None
    when there are more than the cap, or more groups than can be walked: the
    caller then reads the word through :func:`_brace_reach`. The work is
    bounded by the cap, never by the full expansion (review 5 M2).
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
        if index < len(word):
            head, tail = word[:open_at], word[index + 1 :]
            if commas:
                bounds = [open_at, *commas, index]
                for left, right in pairwise(bounds):
                    yield from _brace_alternatives(head + word[left + 1 : right] + tail)
                return
            sequence = _SEQUENCE.fullmatch(word, open_at + 1, index)
            if sequence is not None:
                for value in _sequence_values(sequence):
                    yield from _brace_alternatives(head + value + tail)
                return
        open_at = word.find(_BRACE_OPEN, open_at + 1)
    yield word


def _sequence_values(sequence: re.Match[str]) -> Iterator[str]:
    """Lazily, each value of a ``{first..last[..step]}`` sequence expression."""
    step = abs(int(sequence.group("step") or 1)) or 1
    numeric = sequence.group("first_number") is not None
    if numeric:
        low, high = int(sequence.group("first_number")), int(sequence.group("last_number"))
    else:
        low, high = ord(sequence.group("first_letter")), ord(sequence.group("last_letter"))
    direction = 1 if high >= low else -1
    for value in range(low, high + direction, step * direction):
        yield str(value) if numeric else chr(value)


def _brace_reach(word: str) -> str | None:
    """A word past the brace cap, each group read as ``*``: a glob of the same reach.

    None when an alternative holds a ``/``, which could reach anywhere: that
    word is judged unseen. One pass pairs the braces, so the work is linear.
    """
    groups: list[tuple[int, int]] = []
    open_braces: list[int] = []
    has_comma: set[int] = set()
    for index, char in enumerate(word):
        if char == _BRACE_OPEN:
            open_braces.append(index)
        elif char == _BRACE_SEPARATOR and open_braces:
            has_comma.add(open_braces[-1])
        elif char == _BRACE_CLOSE and open_braces:
            open_at = open_braces.pop()
            if open_at in has_comma or _SEQUENCE.fullmatch(word, open_at + 1, index):
                groups.append((open_at, index))
    reach: list[str] = []
    last = 0
    for open_at, close_at in sorted(groups):
        if open_at < last:
            continue
        if _PATH_SEPARATOR in word[open_at:close_at]:
            return None
        reach.extend((word[last:open_at], _GLOB_ANY))
        last = close_at + 1
    reach.append(word[last:])
    return "".join(reach)


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


@dataclass(frozen=True, slots=True)
class _Verdict:
    """Whether a run is full, and, when that rests on what could not be seen, why."""

    full: bool
    unseen: str = ""


_NOT_FULL: Final[_Verdict] = _Verdict(full=False)
_SEEN_FULL: Final[_Verdict] = _Verdict(full=True)


@dataclass
class _Operands:
    """What a run's operands add up to, gathered one word at a time.

    ``every_word_targets`` holds under a grammar, which knows every flag:
    a word no flag claims is an operand. ``module_names`` holds under
    ``--pyargs``, where an operand is a dotted package name.
    """

    every_word_targets: bool
    module_names: bool
    marked: dict[str, bool]
    seen_full: bool = False
    targets: int = 0
    unseen_full: str = ""
    maybe_bare: str = ""


def _run_verdict(
    pattern: FullQaPattern,
    arguments: Sequence[str],
    cwd: Path | None,
    start: Path | None = None,
    *,
    shape_only: bool = False,
    marked: dict[str, bool] | None = None,
) -> _Verdict:
    """Whether these arguments make ``pattern.command`` run the whole suite.

    A word naming the whole suite (``full_words``, or a ``full_args`` path)
    makes the run full wherever it sits. Under a grammar every operand is a
    target (pytest stops on a path it cannot find); without one, or for
    ``shape_only`` words taken from code, only a PATH-LIKE operand is, and
    any other word is ignored (see :func:`_is_path_like`). ``cwd`` is where
    the command runs (moved by any ``cd``), ``start`` where the event began,
    which ``full_args`` are relative to. A verdict that rests on an operand
    that cannot be seen says so (review 6 n2). ``marked`` caches repository
    marker lookups across one event.
    """
    operands = _Operands(
        every_word_targets=pattern.flag_options is not None and not shape_only,
        module_names=pattern.flag_options is not None and _PYARGS in arguments,
        marked={} if marked is None else marked,
    )
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
                return _NOT_FULL
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
        _add_operand(operands, word, pattern, cwd, start)

    if pattern.full_args is None or operands.seen_full:
        return _SEEN_FULL
    if operands.unseen_full:
        return _Verdict(full=True, unseen=operands.unseen_full)
    if operands.targets or not pattern.bare_is_full:
        return _NOT_FULL
    # A bare run collects the directory it runs in, so below the repository
    # root it is as narrow as that directory.
    if cwd is not None and not _operand_is_full(
        _CURRENT_DIR, pattern.full_args, cwd, start, operands.marked
    ):
        return _NOT_FULL
    return _Verdict(full=True, unseen=operands.maybe_bare)


def _add_operand(
    operands: _Operands, word: str, pattern: FullQaPattern, cwd: Path | None, start: Path | None
) -> None:
    """Judge one operand word into ``operands``."""
    under_grammar = pattern.flag_options is not None
    if word == _CHANGED_FILES:
        operands.targets += 1
    elif word == _STDIN_WORDS:
        operands.maybe_bare = operands.maybe_bare or _STDIN_WORDS_REASON
    elif word == _FIND_SELECTED_FILES:
        operands.unseen_full = operands.unseen_full or _FIND_SELECTED_FILES_REASON
    elif _lists_changed_files(word):
        # Empty, it leaves the run bare: targeted only beside another target.
        operands.maybe_bare = operands.maybe_bare or _EMPTY_LISTING_REASON
    elif under_grammar and word.startswith(_AT_FILE_PREFIX):
        operands.unseen_full = operands.unseen_full or _AT_FILE_REASON
    elif _is_run_time_operand(word):
        operands.unseen_full = operands.unseen_full or _RUN_TIME_OPERAND_REASON
    else:
        alternatives = _expand_braces(word)
        if alternatives is None:
            reach = _brace_reach(word)
            if reach is None:
                operands.unseen_full = operands.unseen_full or _BRACE_REASON
                return
            alternatives = [reach]
        for expanded in alternatives:
            if expanded:
                _add_path_operand(operands, expanded, pattern, cwd, start)


def _add_path_operand(
    operands: _Operands, word: str, pattern: FullQaPattern, cwd: Path | None, start: Path | None
) -> None:
    """Judge one expanded operand: a full word, a full path, or a target."""
    if word in pattern.full_words:
        operands.seen_full = True
        return
    if operands.module_names and _DOTTED_NAME.fullmatch(word):
        word = word.replace(_MODULE_SEPARATOR, _PATH_SEPARATOR)
        if cwd is None or not (_exists(cwd / word) or _exists(cwd / f"{word}{_PYTHON_SUFFIX}")):
            # Imported from wherever the path finds it: that cannot be seen.
            operands.unseen_full = operands.unseen_full or _PYARGS_REASON
            return
    # Brackets after `::` select a parametrised test; they are no glob.
    reach = _glob_reach(word.split(_NODE_ID_SEPARATOR, 1)[0])
    operand = _normalise_operand(word if reach is None else reach)
    if pattern.full_args is not None and _operand_is_full(
        operand, pattern.full_args, cwd, start, operands.marked
    ):
        operands.seen_full = True
    elif operands.every_word_targets or reach is not None or _is_path_like(operand, cwd):
        operands.targets += 1


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
        named = _named_pattern(command, patterns)
        if named is None:
            return None
        quoted = command[:_QUOTED_SEGMENT_LENGTH] + _ELLIPSIS
        return FullQaMatch(named.pattern_id, quoted, fail_closed=_OVERSIZED_REASON)
    event = _Event(patterns=patterns, start=cwd, addopts=_addopts(command))
    token = _PARSE_METER.set(_ParseMeter(remaining=_MAX_PARSED_BYTES))
    try:
        return _first_full_run(_invocations(command), command, event, cwd, 0)
    finally:
        _PARSE_METER.reset(token)


class _Readable(Enum):
    """What reading a file of code found."""

    #: Parsed in full.
    TEXT = "text"
    #: Too large to parse: only scanned for a program's name.
    SCANNED = "scanned"
    #: Cannot be seen at all: a FIFO, a device, or too large to scan.
    UNSEEN = "unseen"
    #: Nothing to run: missing, a directory, or nowhere this can place.
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class _CodeContent:
    """A file of code as read: how far it could be read, and its text."""

    readable: _Readable
    text: str = ""
    path: str = ""


_ABSENT_CODE: Final[_CodeContent] = _CodeContent(_Readable.ABSENT)
_UNSEEN_CODE: Final[_CodeContent] = _CodeContent(_Readable.UNSEEN)


@dataclass
class _ParseMeter:
    """What is left of one judgement's parse budget, in bytes (review 8 B1)."""

    remaining: int


#: The meter of the judgement in progress, set per call by
#: :func:`find_full_qa_invocation`. A ContextVar, never handler state: the
#: daemon may judge events concurrently on the one handler instance.
_PARSE_METER: Final[ContextVar[_ParseMeter]] = ContextVar("subagent_full_qa_parse_meter")


def _charge(code: str) -> bool:
    """Charge ``code`` to this judgement's meter: False when it would pass the budget.

    Once refused, every later charge is refused too, so a judgement never
    parses past the first thing it could not afford. With no meter set,
    nothing was budgeted, and the charge is refused (fail closed).
    """
    meter = _PARSE_METER.get(None)
    if meter is None:
        return False
    size = len(code.encode("utf-8"))
    if size > meter.remaining:
        meter.remaining = 0
        return False
    meter.remaining -= size
    return True


#: A parsed file's verdict, memoised by the resolved path, the kind it was
#: read as, its argv, and the directory it ran from (review 7 M1): a file
#: referenced many times, or one that feeds itself, is parsed once.
_VerdictKey = tuple[str, str, tuple[str, ...], str]


@dataclass
class _Event:
    """What one event's judgement shares: the declaration, and the bounded file reads.

    Every file read in the event draws on one scan budget, and each path is
    read at most once (review 6 M1). Parsing draws on the per-call
    :class:`_ParseMeter`. Each distinct (path, kind, argv, directory) is
    PARSED at most once: repeat references reuse the memoised verdict
    instead of re-parsing (review 7 M1).
    """

    patterns: Sequence[FullQaPattern]
    start: Path | None
    addopts: list[str]
    written: set[str] = field(default_factory=set)
    files: dict[str, _CodeContent] = field(default_factory=dict)
    named: dict[str, FullQaPattern | None] = field(default_factory=dict)
    marked: dict[str, bool] = field(default_factory=dict)
    scan_budget: int = _MAX_SCANNED_FILE_BYTES
    verdicts: dict[_VerdictKey, FullQaMatch | None] = field(default_factory=dict)
    verdicts_pending: set[_VerdictKey] = field(default_factory=set)


def _addopts(text: str) -> list[str]:
    """The words each ``PYTEST_ADDOPTS=value`` in the text gives every pytest run (review 6 m4).

    A value built at run time is one run-time word, which is unseen.
    """
    words: list[str] = []
    for found in _PYTEST_ADDOPTS.finditer(text):
        value = found.group("value").strip(_QUOTES)
        if any(char in value for char in _UNBUILT_CHARACTERS):
            words.append(_ADDOPTS_UNSEEN)
            continue
        try:
            words.extend(shlex.split(value))
        except ValueError:
            words.append(_ADDOPTS_UNSEEN)
    return words


def _named_pattern(text: str, patterns: Sequence[FullQaPattern]) -> FullQaPattern | None:
    """The first pattern whose program the text names."""
    return next((p for p in patterns if _names_program(text, p.command)), None)


def _first_full_run(
    invocations: Iterable[tuple[str, list[str], str]],
    source: str,
    event: _Event,
    here: Path | None,
    files_deep: int,
) -> FullQaMatch | None:
    """The first full run among ``invocations``, following each ``cd`` in order.

    ``source`` is the code they come from, searched for a program when a
    command word is a variable that code does not set. ``env -C``, ``pushd``
    and ``popd`` move the directory as one stack. ``files_deep`` counts code
    files already read on the way here, so a file that feeds itself to a
    shell is not read for ever.
    """
    directories: list[Path | None] = []
    for program, arguments, segment in invocations:
        found: FullQaMatch | None = None
        if program == _WRITES:
            event.written.update(arguments)
        elif program == _CD:
            here = _changed_directory(here, arguments)
        elif program in (_CD_PUSH, _PUSHD):
            directories.append(here)
            here = _changed_directory(here, arguments)
        elif program in (_CD_POP, _POPD):
            here = directories.pop() if directories else here
        elif program == _CODE_FILE:
            found = _full_run_in_code_file(arguments, segment, event, here, files_deep)
        elif program == _UNREAD_CODE:
            found = FullQaMatch(_UNREAD_CODE_ID, segment.strip(), _UNREAD_CODE_REASON)
        elif program == _OVER_BUDGET:
            quoted = segment.strip()[:_QUOTED_SEGMENT_LENGTH]
            found = FullQaMatch(_OVER_BUDGET_ID, quoted, _OVER_BUDGET_REASON)
        else:
            found = _full_run_of(program, arguments, segment, event, here, source)
        if found is not None:
            return found
    return None


def _full_run_of(
    program: str,
    arguments: list[str],
    segment: str,
    event: _Event,
    here: Path | None,
    source: str = "",
) -> FullQaMatch | None:
    """Whether one invocation is a declared full run, read or judged unseen."""
    if program == _UNPARSED:
        named = _named_pattern(segment, event.patterns)
        if named is None:
            return None
        return FullQaMatch(named.pattern_id, segment.strip(), fail_closed=_UNPARSED_REASON)
    if program == _OPAQUE:
        word, rest = arguments[0], arguments[1:]
        # A variable the code does not set may hold any program the code
        # names; a substitution names its program in its own text.
        haystack = source if _VARIABLE.fullmatch(word) else word
        shape_only = word == _PYTEST_IN_CODE
        for pattern in event.patterns:
            if not _names_program(haystack, pattern.command):
                continue
            opaque_arguments = _with_addopts(pattern, rest, event)
            if _run_verdict(
                pattern,
                opaque_arguments,
                here,
                event.start,
                shape_only=shape_only,
                marked=event.marked,
            ).full:
                return FullQaMatch(pattern.pattern_id, segment.strip(), fail_closed=_OPAQUE_REASON)
        return None
    shape_only = program == _PYTEST_IN_CODE
    if shape_only:
        program = _PYTEST
    for pattern in event.patterns:
        if pattern.command != program:
            continue
        verdict = _run_verdict(
            pattern,
            _with_addopts(pattern, arguments, event),
            here,
            event.start,
            shape_only=shape_only,
            marked=event.marked,
        )
        if verdict.full:
            return FullQaMatch(pattern.pattern_id, segment.strip(), fail_closed=verdict.unseen)
    return None


def _with_addopts(pattern: FullQaPattern, arguments: list[str], event: _Event) -> list[str]:
    """pytest's arguments with ``PYTEST_ADDOPTS`` in front, as pytest reads them."""
    return event.addopts + arguments if pattern.command == _PYTEST else arguments


def _full_run_in_code_file(
    arguments: list[str],
    segment: str,
    event: _Event,
    here: Path | None,
    files_deep: int,
) -> FullQaMatch | None:
    """A full run in code read from a file: fed on stdin, or run as a script.

    A program the project declares is judged by its pattern, whatever its
    code holds (``llm_qa.py`` calls pytest itself). Otherwise the code is
    read and judged with its own argv; a cd inside it stays inside it. Code
    that cannot be seen fails closed: an unreadable file is denied, and one
    too large to parse, or past the nesting followed, is denied when it names
    a declared program (review 6 M1, m2). A file's BYTES are read at most
    once per event, and each (path, kind, argv, directory) is parsed at most
    once; every parse is charged to the call's one parse meter, and a parse
    it cannot afford denies the command (review 8 B1). So a file referenced
    with a different argv or directory each time (``bash f.sh a0``, ``a1``,
    ...) is parsed only while the meter lasts.
    """
    kind, path, argv = arguments[0], arguments[1], arguments[2:]
    name = _PROGRAM_ALIASES.get(command_word(path), command_word(path))
    if any(pattern.command == name for pattern in event.patterns):
        return _full_run_of(name, argv, segment, event, here)
    content = _read_code(path, here, event)
    if content.readable is _Readable.ABSENT:
        return None
    if content.readable is _Readable.UNSEEN:
        return FullQaMatch(_UNREAD_CODE_ID, segment.strip(), _UNREAD_CODE_REASON)
    code_kind = _code_kind(content.text) if kind == _EXECUTABLE_CODE else kind
    if code_kind is None:
        return None
    if content.readable is _Readable.SCANNED or files_deep >= _MAX_NESTING:
        return _scanned_verdict(content, code_kind, event, segment)
    key: _VerdictKey = (
        content.path,
        code_kind,
        tuple(argv),
        str(here) if here is not None else "",
    )
    if key in event.verdicts_pending:
        # A file feeding itself back in: already being explored higher in
        # this same chain, so this reference adds nothing new to find.
        return None
    if key in event.verdicts:
        found = event.verdicts[key]
        return (
            None
            if found is None
            else FullQaMatch(found.pattern_id, segment.strip(), found.fail_closed)
        )
    event.verdicts_pending.add(key)
    try:
        event.addopts.extend(_addopts(content.text))
        invocations = (
            _invocations(content.text, 0, argv)
            if code_kind == _SHELL_CODE
            else _python_code_runs(content.text, argv, segment, 0)
        )
        found = _first_full_run(
            invocations, _without_comments(content.text), event, here, files_deep + 1
        )
    finally:
        event.verdicts_pending.discard(key)
    event.verdicts[key] = found
    # The deny quotes the command that ran the file, never the file's own text.
    return (
        None if found is None else FullQaMatch(found.pattern_id, segment.strip(), found.fail_closed)
    )


def _scanned_verdict(
    content: _CodeContent, code_kind: str, event: _Event, segment: str
) -> FullQaMatch | None:
    """The verdict for a file too large to parse: a scan for a declared program's name.

    Comments are dropped first (review 7 M2): a large script's only mention
    of a declared program can be a comment saying it is run elsewhere, not a
    line that runs it. A Python file also has every string's content blanked,
    so a docstring or a message quoting a program's name is not read as one.
    """
    if content.path not in event.named:
        scanned = (
            _without_python_prose(content.text)
            if code_kind == _PYTHON_CODE
            else _without_comments(content.text)
        )
        event.named[content.path] = _named_pattern(scanned, event.patterns)
    named = event.named[content.path]
    if named is None:
        return None
    return FullQaMatch(named.pattern_id, segment.strip(), _SCANNED_FILE_REASON)


def _code_kind(text: str) -> str | None:
    """The kind of code a file run by its path holds, from its first line.

    A ``#!`` line naming a shell or Python says which; one naming another
    interpreter is not judged (None), and neither is a binary. A text file
    with no ``#!`` line is run by the shell.
    """
    if _NUL in text[:_BINARY_PROBE_BYTES]:
        return None
    if not text.startswith(_SHEBANG):
        return _SHELL_CODE
    words = text[len(_SHEBANG) :].split("\n", 1)[0].split()
    if words and command_word(words[0]) == _ENV:
        words = [word for word in words[1:] if not _is_flag(word)]
    interpreter = command_word(words[0]) if words else ""
    if _PYTHON_INTERPRETER.match(interpreter):
        return _PYTHON_CODE
    if interpreter in _SHELL_INTERPRETERS:
        return _SHELL_CODE
    return None


def _read_code(path: str, here: Path | None, event: _Event) -> _CodeContent:
    """A file of code, read at most once per event and within the event's budgets.

    ``/dev/null`` is empty. A path this command writes is unseen: what runs
    is not what is on disk now. A path that cannot be placed (relative, with
    no known directory, or built at run time) is absent.
    """
    if path == _EMPTY_DEVICE:
        return _CodeContent(_Readable.TEXT)
    if posixpath.normpath(path) in event.written:
        return _UNSEEN_CODE
    if path.startswith(_PATH_SEPARATOR):
        target = posixpath.normpath(path)
    elif here is not None and not path.startswith(_UNSEEN_CD_PREFIXES):
        target = posixpath.normpath(posixpath.join(here, path))
    else:
        return _ABSENT_CODE
    cached = event.files.get(target)
    if cached is None:
        cached = _read_new(target, event)
        event.files[target] = cached
    return cached


def _read_new(target: str, event: _Event) -> _CodeContent:
    """Read a file not yet read in this event.

    Missing, a directory, or a name the filesystem refuses: nothing runs. A
    FIFO or a device: unseen, and never opened, since a FIFO blocks. Within
    the parse cap: readable in full, TEXT -- whether it is actually PARSED
    or only scanned is decided per verdict key, against the parse budget
    (review 8 B1), not here at read time: the bytes are read once regardless.
    Past the parse cap: scanned while the scan budget lasts, and unseen after
    it. Any other ``OSError`` propagates, which the daemon turns into a deny:
    the code may be a run, and it could not be seen.
    """
    try:
        status = Path(target).stat()
    except (FileNotFoundError, NotADirectoryError):
        return _ABSENT_CODE
    except OSError as error:
        if error.errno != errno.ENAMETOOLONG:
            raise
        return _ABSENT_CODE
    if stat.S_ISDIR(status.st_mode):
        return _ABSENT_CODE
    if not stat.S_ISREG(status.st_mode):
        return _UNSEEN_CODE
    size = status.st_size
    if size <= _MAX_COMMAND_LENGTH:
        return _CodeContent(_Readable.TEXT, _decoded(target), target)
    if size > event.scan_budget:
        return _UNSEEN_CODE
    event.scan_budget -= size
    return _CodeContent(_Readable.SCANNED, _decoded(target), target)


def _decoded(target: str) -> str:
    """A file's bytes as text; undecodable bytes are replaced, never an error."""
    return Path(target).read_bytes().decode("utf-8", errors="replace")


def _names_program(text: str, program: str) -> bool:
    """Whether ``program`` appears in ``text`` as a word or a path's last part.

    The substring test first: it is linear and fast, where the lookbehind
    makes the regex slow over a large text that does not hold the name.
    """
    if program not in text:
        return False
    return re.search(rf"(?<![\w.-]){re.escape(program)}(?![\w.-])", text) is not None


def _changed_directory(current: Path | None, arguments: Sequence[str]) -> Path | None:
    """Where ``cd <arguments>`` leaves the command, or None when it cannot be known.

    An argument the shell would expand (``$X``, ``~``), ``cd -`` and a bare
    ``cd`` all lead somewhere this cannot see, so the path shape decides
    from there on. Commands are followed in order, which treats a ``cd``
    inside a subshell as though it persisted: a bounded approximation.
    Redirections (``pushd d >/dev/null``) are not operands.
    """
    operands = [word for word in _without_redirects(arguments) if not _is_flag(word)]
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
        full_qa_patterns: list of ``{id, command, full_args?, full_words?,
            bare_is_full?, read_only_flags?, value_flags?, option_grammar?}``.
            Default empty, which is inert.
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
            "`full_qa_patterns` entries are `{id, command, full_args?, full_words?, "
            "bare_is_full?, read_only_flags?, value_flags?, option_grammar?}`, where "
            "`command` is the program's basename, `full_args` are the PATHS that make it "
            "run the whole suite and `full_words` the WORDS that do from anywhere (omit "
            "both and every run is full). Any other operand narrows the run only if it "
            "is path-like, looked up in the directory the command `cd`s to. "
            "`option_grammar: pytest` supplies pytest's complete option set, so a "
            "flag's value is never read as a path and every other word is a target, "
            "and a plugin flag it does not know is read as taking a value: name test "
            "paths BEFORE such a flag, or write `--flag=value`. A changed-files listing "
            "is targeted only through `xargs -r` or beside a named path: an empty one "
            "runs the bare suite. Ships off with no patterns; enabled with none, "
            "`hooks-daemon check` reports it as unable to fire. Keep `scope` at SUB: "
            "any other scope denies the coordinator's own run."
        )
