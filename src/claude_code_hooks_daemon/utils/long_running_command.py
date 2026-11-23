"""Judge a foreground Bash command by SHAPE for how long it may run (Plan 00602).

A command run in the foreground of the main thread blocks the session: the
owner's messages and other agents' messages wait until it ends. There is no
measurement here (v1): the verdict is a function of the command text only.

Four signs that a command is long, each a finding that the handler denies:

* ``WAIT_LOOP`` -- an ``until``/``while`` loop that sleeps. A loop that
  sleeps is waiting for something outside the command, so it ends when that
  thing happens, not when the command is done.
* ``LONG_TIMEOUT`` -- a ``timeout N`` wrapper with ``N`` above the threshold.
  Nobody bounds a command at ten minutes unless they expect it to run for
  minutes: the timeout is the tell.
* ``LONG_SLEEP`` -- ``sleep N`` with ``N`` above the threshold.
* ``SLOW_COMMAND`` -- a program on the known-slow list (test suites, QA runs,
  builds, installs, ``gh run watch``).

One sign is advisory only: ``UNBOUNDED`` -- a program on neither list, run
with no timeout, so nothing says it will end.

What is never a finding: a command (or one statement of it) put in the
background with a trailing ``&``, a ``timeout`` at or below the threshold
(an explicit short bound is what the advisory asks for), and anything the
shared command-position view blanks as data (a commit message, a heredoc body,
an ``echo`` argument).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from claude_code_hooks_daemon.utils.command_position import (
    command_position_code_segments_with_separators,
    command_position_view,
)
from claude_code_hooks_daemon.utils.shell_segmentation import iter_shell_words

#: The length, in seconds, at which a command counts as long ("about 30 seconds").
DEFAULT_THRESHOLD_SECONDS: Final[float] = 30.0

_BACKGROUND_OPERATOR: Final = "&"
_AND_OPERATOR: Final = "&&"
#: Separators that join one statement to the next into a single backgroundable unit.
_LIST_JOINERS: Final[frozenset[str]] = frozenset({"&&", "||", "|", "|&"})
_REDIRECT_CHARS: Final = "<>"

#: Placeholder the command-position view puts where a heredoc body was.
_HEREDOC_BODY_WORD: Final = "HEREDOC_BODY"
_UNRESOLVED_WORD: Final = "\x00"

_DURATION: Final[re.Pattern[str]] = re.compile(r"^(\d+(?:\.\d*)?|\.\d+)([smhd]?)$")
_UNIT_SECONDS: Final[dict[str, float]] = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}

_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
#: A redirect before the command (``>out.txt cmd``, ``2>err cmd``, ``> out cmd``);
#: group 1 is the target when it is attached, empty when it is the next word.
_LEADING_REDIRECT: Final[re.Pattern[str]] = re.compile(r"^\d*(?:<<<|<<-?|<>|>>|>\||>&|<&|>|<)(.*)$")
_PYTHON: Final[re.Pattern[str]] = re.compile(r"^python[\d.]*$")
_HEREDOC_DELIMITER: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

_LOOP_WORDS: Final[frozenset[str]] = frozenset({"until", "while"})
_SHELLS: Final[frozenset[str]] = frozenset({"bash", "sh", "zsh", "dash", "ksh"})

#: Shell syntax that prefixes or closes a command and is not the command.
_SYNTAX_WORDS: Final[frozenset[str]] = frozenset(
    {
        "do",
        "done",
        "then",
        "else",
        "elif",
        "fi",
        "if",
        "while",
        "until",
        "for",
        "case",
        "esac",
        "select",
        "!",
        "{",
        "}",
        "(",
        ")",
        "time",
        "function",
    }
)

#: Words that open or close a compound command and carry no command of their
#: own: `for f in a b`, `case x in`, `done < file`.
_STRUCTURE_WORDS: Final[frozenset[str]] = frozenset(
    {"for", "select", "case", "esac", "done", "fi", "function", "}", ")"}
)

_TIMEOUT: Final = "timeout"
_SLEEP: Final = "sleep"
_WAIT: Final = "wait"
#: GNU ``sleep`` operands that never end.
_ENDLESS_SLEEP: Final[frozenset[str]] = frozenset({"inf", "infinity"})
_TIMEOUT_VALUE_OPTIONS: Final[frozenset[str]] = frozenset({"-k", "-s", "--kill-after", "--signal"})

#: Wrappers that start their operand as the real command, with how many leading
#: option words (all valueless) they may carry.
_SIMPLE_WRAPPERS: Final[frozenset[str]] = frozenset(
    {"nohup", "nice", "command", "exec", "stdbuf", "sudo", "ionice", "setsid", "time"}
)

#: Wrapper options that take the NEXT word as their value (``nice -n 19 cmd``).
_WRAPPER_VALUE_OPTIONS: Final[dict[str, frozenset[str]]] = {
    "nice": frozenset({"-n", "--adjustment"}),
    "ionice": frozenset({"-c", "-n", "-p", "-P", "-u", "--class", "--classdata"}),
    "sudo": frozenset({"-u", "-g", "-U", "-C", "-p", "-D", "--user", "--group"}),
}

#: ``<runner> run <command>`` launchers.
_RUN_LAUNCHERS: Final[frozenset[str]] = frozenset({"uv", "poetry", "pipenv"})

#: Programs that answer at once and never draw the no-timeout advisory. Matched
#: by program basename; a project adds its own through ``extra_fast_programs``.
#: ``git`` is fast except for the verbs in ``_GIT_SLOW_SUBCOMMANDS`` (network
#: and object-store work), which still advise even when ``git`` is listed.
DEFAULT_FAST_PROGRAMS: Final[frozenset[str]] = frozenset(
    {
        "ls", "cat", "grep", "egrep", "fgrep", "rg", "head", "tail", "wc", "echo", "printf",
        "cd", "pwd", "test", "[", "[[", "true", "false", "read", "exit", "return", "unset",
        "export", "set", "shift", "pushd", "popd", "type", "which", "stat", "date", "env",
        "mkdir", "rmdir", "rm", "cp", "mv", "touch", "ln", "chmod", "diff", "cmp", "sort",
        "uniq", "cut", "tr", "tee", "jq", "yq", "awk", "sed", "basename", "dirname",
        "realpath", "readlink", "file", "ps", "pgrep", "kill", "id", "whoami", "hostname",
        "uname", "seq", "expr", "source", ".", ":", "find", "git", "gh", "hooks-daemon",
        "column", "xxd", "od", "du", "df", "tree", "less", "more", "bash", "sh",
        "mkplan.bash", "pingbus",
    }
)  # fmt: skip

#: ``git`` subcommands that talk to a remote or rewrite the object store.
_GIT_SLOW_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {"fetch", "pull", "push", "clone", "gc", "fsck", "submodule", "lfs", "repack", "prune"}
)
_GIT_VALUE_OPTIONS: Final[frozenset[str]] = frozenset({"-C", "-c", "--git-dir", "--work-tree"})

#: Known-slow programs, matched against ``<program> <arguments>`` with every
#: wrapper (``timeout``, ``uv run``, ``python -m``, ...) already peeled. Kept
#: as named groups so a guard can take a subset (host_seat_lane_guard takes
#: test, build and QA but not installs, containers or watches).
TEST_PATTERNS: Final[tuple[str, ...]] = (
    r"^(?:pytest|py\.test|tox|nox)\b",
    r"^(?:jest|vitest|playwright|mocha)\b",
    r"^(?:npm|yarn|pnpm|bun)\s+(?:test|run\s+test\S*)\b",
    r"^cargo\s+(?:test|bench)\b",
    r"^go\s+test\b",
)
BUILD_PATTERNS: Final[tuple[str, ...]] = (
    r"^(?:tsc|webpack|gradle|gradlew|mvn|ant|cmake|ninja|bazel)\b",
    r"^(?:npm|yarn|pnpm|bun)\s+(?:build|run\s+build\S*)\b",
    r"^uv\s+build\b",
    r"^cargo\s+(?:build|check|clippy)\b",
    r"^go\s+(?:build|vet)\b",
)
#: Every ``make``: a target may build, test or deploy, so it is its own group.
MAKE_PATTERNS: Final[tuple[str, ...]] = (r"^make\b",)
QA_PATTERNS: Final[tuple[str, ...]] = (r"^(?:llm_qa\.py|run_all\.sh)\b",)
INSTALL_PATTERNS: Final[tuple[str, ...]] = (
    r"^(?:npm|yarn|pnpm|bun)\s+(?:ci|install|i|add)\b",
    r"^(?:pip|pip3)\s+install\b",
    r"^uv\s+(?:sync|pip\s+install)\b",
    r"^cargo\s+install\b",
    r"^go\s+install\b",
    r"^(?:apt|apt-get|dnf|yum|brew)\s+install\b",
)
CONTAINER_PATTERNS: Final[tuple[str, ...]] = (
    r"^docker\s+(?:build|buildx|compose\s+(?:up|build))\b",
)
WATCH_PATTERNS: Final[tuple[str, ...]] = (
    r"^gh\s+run\s+watch\b",
    r"^gh\s+pr\s+checks\b.*--watch\b",
    r"^watch\b",
    # `tail -f` / `-F` / `--follow` never ends on its own.
    r"^tail\b.*?\s(?:-[A-Za-z0-9]*[fF][A-Za-z0-9]*|--follow)(?=[=\s]|$)",
)
DEFAULT_SLOW_PATTERNS: Final[tuple[str, ...]] = (
    *TEST_PATTERNS,
    *BUILD_PATTERNS,
    *MAKE_PATTERNS,
    *QA_PATTERNS,
    *INSTALL_PATTERNS,
    *CONTAINER_PATTERNS,
    *WATCH_PATTERNS,
)


class FindingKind(StrEnum):
    """What made a command look long (or unbounded)."""

    WAIT_LOOP = "wait-loop"
    LONG_TIMEOUT = "long-timeout"
    LONG_SLEEP = "long-sleep"
    SLOW_COMMAND = "slow-command"
    UNBOUNDED = "unbounded"


@dataclass(frozen=True)
class Finding:
    """One reason a command looks long, with the text that showed it."""

    kind: FindingKind
    subject: str


def _compile(patterns: Iterable[str], option: str) -> tuple[re.Pattern[str], ...]:
    """Compile ``patterns``, naming ``option`` when one is not a valid regex."""
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise ValueError(f"{option} entry {pattern!r} is not a valid regex: {exc}") from exc
    return tuple(compiled)


@dataclass(frozen=True)
class LongRunningPolicy:
    """The knobs of the judgement. The defaults are the shipped behaviour."""

    threshold_seconds: float = DEFAULT_THRESHOLD_SECONDS
    slow_patterns: tuple[re.Pattern[str], ...] = field(
        default_factory=lambda: _compile(DEFAULT_SLOW_PATTERNS, "slow_patterns")
    )
    fast_programs: frozenset[str] = DEFAULT_FAST_PROGRAMS
    exempt_patterns: tuple[re.Pattern[str], ...] = ()

    @classmethod
    def build(
        cls,
        *,
        threshold_seconds: float = DEFAULT_THRESHOLD_SECONDS,
        extra_slow_patterns: Sequence[str] = (),
        extra_fast_programs: Sequence[str] = (),
        exempt_patterns: Sequence[str] = (),
    ) -> LongRunningPolicy:
        """The default policy plus a project's additions.

        Raises:
            ValueError: A pattern is not a valid regex.
        """
        return cls(
            threshold_seconds=threshold_seconds,
            slow_patterns=_compile(
                (*DEFAULT_SLOW_PATTERNS, *extra_slow_patterns), "extra_slow_patterns"
            ),
            fast_programs=DEFAULT_FAST_PROGRAMS | frozenset(extra_fast_programs),
            exempt_patterns=_compile(exempt_patterns, "exempt_patterns"),
        )


def parse_duration_seconds(word: str) -> float | None:
    """Seconds named by a ``sleep``/``timeout`` duration word, or None if it is not one."""
    match = _DURATION.match(word)
    if match is None:
        return None
    return float(match.group(1)) * _UNIT_SECONDS[match.group(2)]


@dataclass
class _Peeled:
    """A segment with its wrappers removed."""

    words: list[str]
    timeouts: list[float | None] = field(default_factory=list)
    loop_head: bool = False

    @property
    def program(self) -> str | None:
        """Basename of the program the segment finally runs, or None if unknown."""
        if not self.words or self.words[0] == _UNRESOLVED_WORD:
            return None
        return self.words[0].rsplit("/", 1)[-1]

    @property
    def arguments(self) -> list[str]:
        """The words after the program."""
        return self.words[1:]


def _segment_words(segment: str) -> list[str]:
    """The words of ``segment``, with subshell parentheses split off the command.

    ``(sleep 100)`` is the command ``sleep 100`` in a subshell, not a program
    named ``(sleep``: a leading ``(`` becomes a word of its own (syntax, dropped
    with the other prefix words) and the matching ``)`` is cut from the last word.
    """
    words: list[str] = []
    opened = 0
    for raw in iter_shell_words(segment):
        word = _UNRESOLVED_WORD if raw is None else raw
        while word.startswith("(") and len(word) > 1 and all(w == "(" for w in words):
            words.append("(")
            opened += 1
            word = word[1:]
        if word:
            words.append(word)
    while opened and words and words[-1].endswith(")") and len(words) > opened:
        if words[-1] == ")":
            words.pop()
        else:
            words[-1] = words[-1][:-1]
        opened -= 1
    return words


def _skip_prefix(words: list[str]) -> tuple[list[str], bool]:
    """Drop leading assignments, redirects and shell syntax.

    Says whether a loop keyword was dropped.
    """
    index = 0
    loop_head = False
    while index < len(words):
        word = words[index]
        if word in _STRUCTURE_WORDS:
            return [], loop_head
        redirect = _LEADING_REDIRECT.match(word)
        if redirect is not None:
            index += 1 if redirect.group(1) else 2
            continue
        if word in _LOOP_WORDS:
            loop_head = True
        elif not (_ASSIGNMENT.match(word) or word in _SYNTAX_WORDS):
            break
        index += 1
    return words[index:], loop_head


def _peel_timeout(words: list[str]) -> tuple[float | None, list[str]]:
    """The seconds a leading ``timeout`` allows (inf for 0) and the words after it."""
    index = 1
    while index < len(words) and words[index].startswith("-"):
        index += 2 if words[index] in _TIMEOUT_VALUE_OPTIONS else 1
    if index >= len(words):
        return None, []
    seconds = parse_duration_seconds(words[index])
    if seconds == 0.0:
        seconds = float("inf")
    return seconds, words[index + 1 :]


def _peel_wrapper(words: list[str]) -> list[str] | None:
    """The words after one non-timeout wrapper, or None when ``words`` has none."""
    head = words[0].rsplit("/", 1)[-1]
    rest = words[1:]
    if head == "env":
        index = 0
        while index < len(rest) and (rest[index].startswith("-") or _ASSIGNMENT.match(rest[index])):
            index += 2 if rest[index] == "-u" else 1
        return rest[index:]
    if head == "command" and any(
        re.fullmatch(r"-[pP]*[vV][pP]*", option) for option in rest[:2] if option.startswith("-")
    ):
        # `command -v pytest` only looks the name up: it is `type pytest`, not a run.
        return ["type", *rest]
    if head in _SIMPLE_WRAPPERS:
        valued = _WRAPPER_VALUE_OPTIONS.get(head, frozenset())
        index = 0
        while index < len(rest) and rest[index].startswith("-"):
            index += 2 if rest[index] in valued else 1
        return rest[index:]
    if head in _RUN_LAUNCHERS and rest[:1] == ["run"]:
        index = 1
        while index < len(rest) and rest[index].startswith("-"):
            index += 1
        return rest[index:]
    if _PYTHON.match(head) and rest[:1] == ["-m"] and len(rest) > 1:
        return rest[1:]
    if head in _SHELLS:
        body = _shell_command_string(rest)
        if body is not None:
            return body
    if (_PYTHON.match(head) or head in _SHELLS) and rest and not rest[0].startswith("-"):
        return rest
    return None


def _shell_command_string(arguments: list[str]) -> list[str] | None:
    """The words of a ``bash -c`` body, or None when the shell is not given one."""
    index = 0
    while index < len(arguments) and arguments[index].startswith(("-", "+")):
        word = arguments[index]
        if word.startswith("-") and not word.startswith("--") and "c" in word:
            return arguments[index + 1 :]
        index += 2 if word in ("-o", "+o") else 1
    return None


def _dequote_program(word: str) -> str:
    """``word`` as bash resolves a program name: quotes and backslashes removed.

    ``"pytest"``, ``'pytest'`` and ``p\\ytest`` all run ``pytest``. Only the
    program word is touched; a ``$``-expansion stays unresolved text.
    """
    if word == _UNRESOLVED_WORD or not any(char in word for char in "'\"\\"):
        return word
    return word.replace("'", "").replace('"', "").replace("\\", "")


def _peel(segment: str) -> _Peeled:
    words, loop_head = _skip_prefix(_segment_words(segment))
    peeled = _Peeled(words=words, loop_head=loop_head)
    while peeled.words and peeled.words[0] != _UNRESOLVED_WORD:
        peeled.words[0] = _dequote_program(peeled.words[0])
        if peeled.words[0].rsplit("/", 1)[-1] == _TIMEOUT:
            seconds, remainder = _peel_timeout(peeled.words)
            peeled.timeouts.append(seconds)
            peeled.words, dropped_loop = _skip_prefix(remainder)
            peeled.loop_head = peeled.loop_head or dropped_loop
            continue
        remainder_or_none = _peel_wrapper(peeled.words)
        if remainder_or_none is None:
            break
        peeled.words, dropped_loop = _skip_prefix(remainder_or_none)
        peeled.loop_head = peeled.loop_head or dropped_loop
    return peeled


def _git_is_slow(arguments: list[str]) -> bool:
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if not word.startswith("-"):
            return word in _GIT_SLOW_SUBCOMMANDS
        index += 2 if word in _GIT_VALUE_OPTIONS else 1
    return False


def _sleep_seconds(arguments: list[str]) -> float | None:
    """Total seconds ``sleep`` is given, or None when an operand is not a duration."""
    total = 0.0
    seen = False
    for word in arguments:
        seconds = float("inf") if word.lower() in _ENDLESS_SLEEP else parse_duration_seconds(word)
        if seconds is None:
            return None
        total += seconds
        seen = True
    return total if seen else None


def _is_background(view: str) -> bool:
    """Whether the whole command ends with a lone ``&`` (it runs in the background)."""
    tail = view.rstrip()
    if not tail.endswith(_BACKGROUND_OPERATOR) or tail.endswith(_AND_OPERATOR):
        return False
    before = tail[:-1].rstrip()
    return not (before and before[-1] in _REDIRECT_CHARS)


def _background_unit_start(view: str, segments: list[tuple[str, str]]) -> int:
    """Index of the first segment a trailing ``&`` puts in the background.

    A trailing ``&`` backgrounds the last pipeline or ``&&``/``||`` list, not the
    statements before a ``;``, ``&`` or newline. ``len(segments)`` when nothing is
    backgrounded. A compound command (``... done &``, ``( ... ) &``) is
    backgrounded whole, so it starts at 0.
    """
    if not segments or not _is_background(view):
        return len(segments)
    last = segments[-1][1].strip()
    first_word = last.split(maxsplit=1)[0] if last else ""
    if last.endswith((")", "}")) or first_word in _STRUCTURE_WORDS:
        return 0
    start = len(segments) - 1
    while start > 0 and segments[start][0].strip() in _LIST_JOINERS:
        start -= 1
    return start


def _bounded(timeouts: list[float | None], threshold: float) -> bool:
    """Whether some enclosing ``timeout`` ends the segment within the threshold."""
    return any(seconds is not None and seconds <= threshold for seconds in timeouts)


def _segment_findings(peeled: _Peeled, policy: LongRunningPolicy) -> list[Finding]:
    findings: list[Finding] = []
    for seconds in peeled.timeouts:
        if seconds is not None and seconds > policy.threshold_seconds:
            label = "no limit" if seconds == float("inf") else f"{seconds:g}s"
            findings.append(Finding(FindingKind.LONG_TIMEOUT, f"timeout {label}"))
    program = peeled.program
    if program is None or program in _SYNTAX_WORDS or program == _HEREDOC_BODY_WORD:
        return findings
    if program == _SLEEP:
        seconds = _sleep_seconds(peeled.arguments)
        if seconds is not None and seconds > policy.threshold_seconds:
            findings.append(Finding(FindingKind.LONG_SLEEP, f"sleep {' '.join(peeled.arguments)}"))
        return findings
    if _bounded(peeled.timeouts, policy.threshold_seconds):
        return findings
    canonical = " ".join([program, *peeled.arguments])
    if any(pattern.search(canonical) for pattern in policy.slow_patterns):
        findings.append(Finding(FindingKind.SLOW_COMMAND, program))
    elif program not in policy.fast_programs or (
        program == "git" and _git_is_slow(peeled.arguments)
    ):
        if program not in _SHELLS:
            findings.append(Finding(FindingKind.UNBOUNDED, program))
    return findings


def classify(
    command: str, policy: LongRunningPolicy | None = None, *, include_background: bool = False
) -> tuple[Finding, ...]:
    """The reasons ``command`` looks long or unbounded; empty when it looks short.

    Judged on the command-position view, so text bash hands over as data is
    never read as a command. A statement followed by a lone ``&`` is background
    work and draws nothing; a trailing ``&`` backgrounds only the last statement
    (the ``&&``/``||``/``|`` list it ends), so ``sleep 300; echo x &`` still
    blocks on the sleep. ``include_background`` judges backgrounded statements
    like any other, for a guard that cares WHAT runs rather than how long.
    """
    policy = policy or LongRunningPolicy()
    if not command.strip() or any(pattern.search(command) for pattern in policy.exempt_patterns):
        return ()
    segments = command_position_code_segments_with_separators(command)
    background_from = (
        len(segments)
        if include_background
        else _background_unit_start(command_position_view(command), segments)
    )
    findings: list[Finding] = []
    loop_seen = False
    sleep_seen = False
    background_seen = False
    previous_words: list[str] = []
    for index, (_separator, segment) in enumerate(segments):
        following = segments[index + 1][0].strip() if index + 1 < len(segments) else ""
        words = _segment_words(segment)
        is_delimiter = (
            previous_words == [_HEREDOC_BODY_WORD]
            and len(words) == 1
            and _HEREDOC_DELIMITER.match(words[0]) is not None
        )
        previous_words = words
        backgrounded = following == _BACKGROUND_OPERATOR and not include_background
        if backgrounded or index >= background_from or is_delimiter:
            background_seen = background_seen or not is_delimiter
            continue
        peeled = _peel(segment)
        loop_seen = loop_seen or peeled.loop_head
        sleep_seen = sleep_seen or peeled.program == _SLEEP
        if peeled.program == _WAIT and background_seen:
            findings.append(Finding(FindingKind.SLOW_COMMAND, "wait for a background job"))
            continue
        findings.extend(_segment_findings(peeled, policy))
    if loop_seen and sleep_seen:
        findings.insert(0, Finding(FindingKind.WAIT_LOOP, "a loop that sleeps"))
    return tuple(dict.fromkeys(findings))
