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
_REDIRECT_CHARS: Final = "<>"

#: Placeholder the command-position view puts where a heredoc body was.
_HEREDOC_BODY_WORD: Final = "HEREDOC_BODY"
_UNRESOLVED_WORD: Final = "\x00"

_DURATION: Final[re.Pattern[str]] = re.compile(r"^(\d+(?:\.\d*)?|\.\d+)([smhd]?)$")
_UNIT_SECONDS: Final[dict[str, float]] = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}

_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
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
_TIMEOUT_VALUE_OPTIONS: Final[frozenset[str]] = frozenset({"-k", "-s", "--kill-after", "--signal"})

#: Wrappers that start their operand as the real command, with how many leading
#: option words (all valueless) they may carry.
_SIMPLE_WRAPPERS: Final[frozenset[str]] = frozenset(
    {"nohup", "nice", "command", "exec", "stdbuf", "sudo", "ionice", "setsid", "time"}
)

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
#: wrapper (``timeout``, ``uv run``, ``python -m``, ...) already peeled.
DEFAULT_SLOW_PATTERNS: Final[tuple[str, ...]] = (
    r"^(?:pytest|py\.test|tox|nox)\b",
    r"^(?:llm_qa\.py|run_all\.sh)\b",
    r"^(?:jest|vitest|playwright|mocha|tsc|webpack|gradle|gradlew|mvn|ant|make|cmake|ninja|bazel)\b",
    r"^(?:npm|yarn|pnpm|bun)\s+(?:ci|install|i|add|test|build|run\s+(?:build|test)\S*)\b",
    r"^(?:pip|pip3)\s+install\b",
    r"^uv\s+(?:sync|build|pip\s+install)\b",
    r"^cargo\s+(?:build|test|install|check|clippy|bench)\b",
    r"^go\s+(?:build|test|install|vet)\b",
    r"^docker\s+(?:build|buildx|compose\s+(?:up|build))\b",
    r"^(?:apt|apt-get|dnf|yum|brew)\s+install\b",
    r"^gh\s+run\s+watch\b",
    r"^gh\s+pr\s+checks\b.*--watch\b",
    r"^watch\b",
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
    return [_UNRESOLVED_WORD if word is None else word for word in iter_shell_words(segment)]


def _skip_prefix(words: list[str]) -> tuple[list[str], bool]:
    """Drop leading assignments and shell syntax; say whether a loop keyword was dropped."""
    index = 0
    loop_head = False
    while index < len(words):
        word = words[index]
        if word in _STRUCTURE_WORDS or word.startswith(tuple(_REDIRECT_CHARS)):
            return [], loop_head
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
    if head in _SIMPLE_WRAPPERS:
        index = 0
        while index < len(rest) and rest[index].startswith("-"):
            index += 1
        return rest[index:]
    if head in _RUN_LAUNCHERS and rest[:1] == ["run"]:
        index = 1
        while index < len(rest) and rest[index].startswith("-"):
            index += 1
        return rest[index:]
    if _PYTHON.match(head) and rest[:1] == ["-m"] and len(rest) > 1:
        return rest[1:]
    if (_PYTHON.match(head) or head in _SHELLS) and rest and not rest[0].startswith("-"):
        return rest
    return None


def _peel(segment: str) -> _Peeled:
    words, loop_head = _skip_prefix(_segment_words(segment))
    peeled = _Peeled(words=words, loop_head=loop_head)
    while peeled.words and peeled.words[0] != _UNRESOLVED_WORD:
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


def _shell_body_is_loop(peeled: _Peeled) -> bool:
    """Whether the segment is ``bash -c`` whose body opens with ``until``/``while``."""
    if peeled.program not in _SHELLS:
        return False
    arguments = peeled.arguments
    for index, word in enumerate(arguments[:-1]):
        if word.startswith("-") and not word.startswith("--") and "c" in word:
            return arguments[index + 1] in _LOOP_WORDS
    return False


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
        seconds = parse_duration_seconds(word)
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
        if not _shell_body_is_loop(peeled) and program not in _SHELLS:
            findings.append(Finding(FindingKind.UNBOUNDED, program))
    return findings


def classify(command: str, policy: LongRunningPolicy | None = None) -> tuple[Finding, ...]:
    """The reasons ``command`` looks long or unbounded; empty when it looks short.

    Judged on the command-position view, so text bash hands over as data is
    never read as a command. A command ending in a lone ``&`` is background
    work and draws nothing; so does a statement followed by one.
    """
    policy = policy or LongRunningPolicy()
    if not command.strip() or any(pattern.search(command) for pattern in policy.exempt_patterns):
        return ()
    if _is_background(command_position_view(command)):
        return ()
    segments = command_position_code_segments_with_separators(command)
    findings: list[Finding] = []
    loop_seen = False
    sleep_seen = False
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
        if following == _BACKGROUND_OPERATOR or is_delimiter:
            continue
        peeled = _peel(segment)
        loop_seen = loop_seen or peeled.loop_head or _shell_body_is_loop(peeled)
        sleep_seen = sleep_seen or peeled.program == _SLEEP
        findings.extend(_segment_findings(peeled, policy))
    if loop_seen and sleep_seen:
        findings.insert(0, Finding(FindingKind.WAIT_LOOP, "a loop that sleeps"))
    return tuple(dict.fromkeys(findings))
