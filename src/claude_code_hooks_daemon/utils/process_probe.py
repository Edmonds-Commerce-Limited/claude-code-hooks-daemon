"""Classify the process probes in a Bash command, and whether they match themselves.

The Bash tool runs every command through ``bash -c "<command>"``, so the
pattern a command searches for is ALWAYS present in the searching shell's own
argv. A field report recorded the consequence::

    until ! pgrep -f "run_02" >/dev/null; do sleep 30; done

The job had finished hours earlier. ``pgrep -f`` matches against the full
command line of every process, and one of those processes is the very shell
running the loop — whose command line contains ``run_02``. The probe could
never return empty, so the wait could never end.

Three shapes share the defect:

* ``pgrep -f <literal>`` / ``pkill -f <literal>`` — the pattern is in the
  waiting shell's argv.
* ``ps … | grep <literal>`` — the ``grep`` process's own line appears in the
  ``ps`` output it is filtering.
* ``pgrep -f <literal> | xargs kill`` — the ``pkill`` outcome by another route.

**The test applied here is the tool's own semantics, not a pattern list.**
``pgrep -f`` matches an extended regular expression against a command line, so
this module asks exactly that question: does the pattern, read as a regex,
match the text of the probe's own command line? That single test explains every
documented remedy without enumerating them — ``[r]un_02`` no longer matches its
own spelling, ``run_0[3-9]`` never did, and ``pgrep -x`` compares the whole
line rather than searching within it.

The same report records a second, compounding shape: the loop itself. A
``while``/``until`` whose condition is a process probe and whose body is only
``sleep`` has nothing that can stop it but the probe changing its answer, and
the Bash tool caps only FOREGROUND calls. :func:`classify_liveness_loops`
describes those separately, because a loop waiting on an ARTEFACT
(``until grep -q "PLAY RECAP" run.log``) is the recommended remedy and must
never be confused with the defect.

Deliberately a classifier, not a shell parser. It reports; the handler decides.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from claude_code_hooks_daemon.utils.command_evasion import normalise_line_continuations
from claude_code_hooks_daemon.utils.shell_segmentation import strip_quoted_heredoc_bodies


class ProbeKind(StrEnum):
    """Which flavour of process probe a command span carries."""

    PGREP = "pgrep"
    PKILL = "pkill"
    PS_GREP = "ps-grep"
    PS_PID = "ps-pid"
    KILL_PID = "kill-pid"


class ProbeVerdict(StrEnum):
    """Whether a probe can see the shell that is running it.

    ``UNRESOLVED`` is not a hedge between the other two: it means the pattern
    is built by expansion, so no static reading of the command can say what is
    searched for. A caller must never DENY on it.
    """

    SELF_MATCHING = "self-matching"
    UNRESOLVED = "unresolved"
    SAFE = "safe"


class WaitConstruct(StrEnum):
    """The construct a probe sits inside, when that construct waits on it.

    The distinction a caller cares about: a self-matching probe run ONCE gives
    a wrong answer, while the same probe inside one of these never terminates.
    """

    LOOP = "loop"
    WATCH = "watch"
    TIMEOUT = "timeout"


#: Highest-precedence construct first. A loop inside a ``timeout`` is reported
#: as a loop: the inner construct is the more specific truth about the probe.
_CONSTRUCT_PRECEDENCE: Final[tuple[WaitConstruct, ...]] = (
    WaitConstruct.LOOP,
    WaitConstruct.WATCH,
    WaitConstruct.TIMEOUT,
)

#: How each self-matching kind is spelt once rewritten with the bracket trick.
#: A mapping rather than a branch, so a new kind adds a row and nothing else.
_REWRITE_TEMPLATES: Final[dict[ProbeKind, str]] = {
    ProbeKind.PGREP: 'pgrep -f "{pattern}"',
    ProbeKind.PKILL: 'pkill -f "{pattern}"',
    ProbeKind.PS_GREP: 'ps aux | grep "{pattern}"',
}


@dataclass(frozen=True, slots=True)
class ProcessProbe:
    """One classified process probe found in a Bash command.

    Attributes:
        kind: Which probe shape this is.
        text: The probe's own command text, as written.
        pattern: The pattern operand as bash would pass it (quotes removed),
            or None when the probe names a PID or carries no pattern.
        verdict: Whether the pattern can match the probing shell.
        signals: Whether a match is SIGNALLED rather than reported —
            ``pkill`` always, and ``pgrep … | xargs kill`` by another route.
            Recorded independently of the verdict so a caller can warn about
            an unresolvable pattern that would kill whatever it does match.
        wait_construct: The waiting construct the probe sits inside, if any.
    """

    kind: ProbeKind
    text: str
    pattern: str | None
    verdict: ProbeVerdict
    signals: bool
    wait_construct: WaitConstruct | None

    @property
    def is_self_matching(self) -> bool:
        """Whether this probe's pattern matches its own command line."""
        return self.verdict is ProbeVerdict.SELF_MATCHING

    @property
    def lethal(self) -> bool:
        """Whether acting on this probe's match would signal the caller itself."""
        return self.signals and self.is_self_matching

    @property
    def safe_rewrite(self) -> str | None:
        """The bracket-trick spelling of this probe, when one can be offered."""
        if not self.is_self_matching or self.pattern is None:
            return None
        template = _REWRITE_TEMPLATES.get(self.kind)
        tricked = bracket_trick(self.pattern)
        if template is None or tricked is None:
            return None
        return template.format(pattern=tricked)


def bracket_trick(pattern: str) -> str | None:
    """Rewrite ``pattern`` so it can no longer match its own spelling.

    ``run_02`` becomes ``[r]un_02``: as a regex it still matches ``run_02`` in
    any OTHER process's command line, but the probing shell's argv now contains
    ``[r]un_02``, which the regex does not match.

    Returns None when the rewrite is not safely mechanical — an empty pattern,
    one that already contains a bracket expression, or one whose first
    character is a regex metacharacter rather than a literal to hide.
    """
    if not pattern or "[" in pattern:
        return None
    first = pattern[0]
    if not (first.isalnum() or first == "_"):
        return None
    return f"[{first}]{pattern[1:]}"


@dataclass(frozen=True, slots=True)
class LivenessLoop:
    """One ``while``/``until`` loop, and whether it can ever stop.

    The incident's second failure mode. A loop whose CONDITION is a process
    probe and whose BODY is nothing but ``sleep`` has no way to stop except by
    the probe changing its answer — so when the probe is wrong, the loop is a
    silent, unbounded wait. The Bash tool caps a FOREGROUND call at ten
    minutes; a ``run_in_background`` call has no cap, which is where the
    reported night went.

    Attributes:
        keyword: ``while`` or ``until``.
        text: The loop as written, opener to ``done``.
        condition: The text between the keyword and ``do``.
        body: The text between ``do`` and ``done``.
        probes: The process probes in the CONDITION. Empty when the loop waits
            on something else — an artefact (``until grep -q MARKER log``),
            which is the remedy and must never be flagged.
        body_only_sleeps: Whether the body does nothing but idle.
        bounded: Whether something caps the iterations.
    """

    keyword: str
    text: str
    condition: str
    body: str
    probes: tuple[ProcessProbe, ...]
    body_only_sleeps: bool
    bounded: bool

    @property
    def is_unbounded_liveness_wait(self) -> bool:
        """Whether this loop waits on a process, idly, with nothing to stop it."""
        return bool(self.probes) and self.body_only_sleeps and not self.bounded


def classify_process_probes(command: str) -> tuple[ProcessProbe, ...]:
    """Classify every process probe in ``command``, in the order they appear.

    Args:
        command: The raw Bash command string, exactly as the tool received it.

    Returns:
        One :class:`ProcessProbe` per recognised probe. Empty when the command
        contains none — which includes prose that merely names one, since a
        quoted argument and a quoted-delimiter heredoc body are both data.
    """
    if not command.strip():
        return ()
    normalised = _normalise(command)
    return tuple(_analyse(normalised, subject=normalised, inherited=None))


def classify_liveness_loops(command: str) -> tuple[LivenessLoop, ...]:
    """Describe every ``while``/``until`` loop in ``command``.

    A loop written inside a quoted ``bash -c`` script is deliberately NOT
    reported. That is not a gap being tolerated, it is the answer: the shapes
    that hide a loop in a quoted argument are the ones that BOUND it
    (``timeout 3600 bash -c '…'``), so reporting them would advise against the
    fix. Probes inside such a script are still classified — see
    :func:`classify_process_probes`, which does recurse.

    Args:
        command: The raw Bash command string.

    Returns:
        One :class:`LivenessLoop` per loop, in the order they appear.
    """
    if not command.strip():
        return ()
    normalised = _normalise(command)
    words = _scan_words(normalised)
    return tuple(_describe_loop(structure, normalised) for structure in _loop_structures(words))


def _normalise(command: str) -> str:
    """Join line continuations and blank literal heredoc bodies, once."""
    return strip_quoted_heredoc_bodies(normalise_line_continuations(command))


# --------------------------------------------------------------------------
# Lexing
# --------------------------------------------------------------------------

_SINGLE_QUOTE: Final = "'"
_DOUBLE_QUOTE: Final = '"'
_ESCAPE: Final = "\\"

#: Operators that end a word wherever they appear, longest first so ``&&`` is
#: never read as two ``&``. ``{`` and ``}`` are absent deliberately: bash treats
#: them as reserved words only when they stand alone, and splitting them inline
#: would cut ``xargs -I{}`` in half.
_OPERATORS: Final[tuple[str, ...]] = ("&&", "||", ";;", ";", "|", "&", "\n", "(", ")")

#: A redirection, matched BEFORE the operator table so ``2>&1`` stays one word
#: instead of being split on its ``&``.
_REDIRECT: Final[re.Pattern[str]] = re.compile(r"\d*(?:&>>|&>|>>|>&|<&|>\||>|<)")

#: A leading ``VAR=value`` assignment, which prefixes a command without being it.
_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"^\w+=")

#: Words after which the NEXT word names a command. The loop keywords are here
#: too, which is what makes ``until ! pgrep …`` resolve to ``pgrep``.
_COMMAND_POSITION_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "&&",
        "||",
        ";",
        ";;",
        "|",
        "&",
        "\n",
        "(",
        ")",
        "{",
        "}",
        "!",
        "if",
        "then",
        "elif",
        "else",
        "fi",
        "while",
        "until",
        "for",
        "in",
        "do",
        "done",
        "case",
        "esac",
        "time",
    }
)

#: Separators that end a statement, used to bound a ``watch``/``timeout`` region.
_STATEMENT_SEPARATORS: Final[frozenset[str]] = frozenset({"&&", "||", ";", ";;", "&", "\n"})

_PIPE: Final = "|"
_LOOP_OPENERS: Final[frozenset[str]] = frozenset({"while", "until", "for"})

#: The loops whose iteration count is decided by a CONDITION rather than by a
#: fixed list, so they are the ones that can spin for ever.
_CONDITIONAL_LOOP_OPENERS: Final[frozenset[str]] = frozenset({"while", "until"})
_LOOP_CLOSER: Final = "done"


@dataclass(frozen=True, slots=True)
class _Word:
    """One lexed word, with the offsets that place it inside a wait region."""

    start: int
    end: int
    text: str


def _scan_words(text: str) -> list[_Word]:
    """Split ``text`` into quote-aware words, operators kept as words of their own."""
    words: list[_Word] = []
    buffer: list[str] = []
    start = 0
    in_single = False
    in_double = False
    index = 0

    def flush(end: int) -> None:
        if buffer:
            words.append(_Word(start, end, "".join(buffer)))
            buffer.clear()

    while index < len(text):
        char = text[index]
        if char == _ESCAPE and not in_single:
            if not buffer:
                start = index
            buffer.append(char)
            index += 1
            if index < len(text):
                buffer.append(text[index])
                index += 1
            continue
        if char == _SINGLE_QUOTE and not in_double:
            in_single = not in_single
        elif char == _DOUBLE_QUOTE and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if char.isspace() and char != "\n":
                flush(index)
                index += 1
                continue
            redirect = _REDIRECT.match(text, index)
            if redirect is not None:
                if not buffer:
                    start = index
                buffer.append(redirect.group(0))
                index = redirect.end()
                continue
            operator = next((op for op in _OPERATORS if text.startswith(op, index)), None)
            if operator is not None:
                flush(index)
                words.append(_Word(index, index + len(operator), operator))
                index += len(operator)
                continue
        if not buffer:
            start = index
        buffer.append(char)
        index += 1

    flush(len(text))
    return words


# --------------------------------------------------------------------------
# Wait regions
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Region:
    """A span of the command inside which a probe is being waited on."""

    start: int
    end: int
    construct: WaitConstruct


@dataclass(frozen=True, slots=True)
class _Wrapper:
    """A command that RUNS another command, and what to skip to reach it.

    Attributes:
        value_flags: Flags whose following token is a value, not the command.
        positional_operands: Positional tokens consumed before the wrapped
            command starts — ``timeout``'s DURATION is the only one shipped.
        construct: The wait construct this wrapper establishes, if any.
    """

    value_flags: frozenset[str]
    positional_operands: int = 0
    construct: WaitConstruct | None = None


_WRAPPERS: Final[dict[str, _Wrapper]] = {
    "watch": _Wrapper(
        value_flags=frozenset({"-n", "--interval"}),
        construct=WaitConstruct.WATCH,
    ),
    "timeout": _Wrapper(
        value_flags=frozenset({"-s", "--signal", "-k", "--kill-after"}),
        positional_operands=1,
        construct=WaitConstruct.TIMEOUT,
    ),
    "nohup": _Wrapper(value_flags=frozenset()),
    "sudo": _Wrapper(value_flags=frozenset({"-u", "-g", "-p"})),
    "env": _Wrapper(value_flags=frozenset({"-u", "--unset"})),
    "nice": _Wrapper(value_flags=frozenset({"-n", "--adjustment"})),
    "stdbuf": _Wrapper(value_flags=frozenset({"-i", "-o", "-e"})),
    "command": _Wrapper(value_flags=frozenset()),
}

#: Wrappers that make the command they run a WAIT rather than a one-shot.
_WAIT_WRAPPERS: Final[dict[str, WaitConstruct]] = {
    name: wrapper.construct for name, wrapper in _WRAPPERS.items() if wrapper.construct is not None
}


def _wait_regions(words: list[_Word], end: int) -> list[_Region]:
    """Locate every region of the command that waits on what it contains."""
    regions: list[_Region] = []
    open_loops: list[int] = []
    at_command_position = True

    for position, word in enumerate(words):
        # `done` closes a loop only in COMMAND position. As an ARGUMENT it is
        # an ordinary word, and `grep -q done run.log` inside a wait loop is
        # exactly the artefact-polling shape the report recommends — closing
        # the loop there would lose the loop that is actually open.
        if at_command_position and word.text == _LOOP_CLOSER and open_loops:
            regions.append(_Region(open_loops.pop(), word.end, WaitConstruct.LOOP))
        elif at_command_position and word.text in _LOOP_OPENERS:
            open_loops.append(word.start)
        elif at_command_position and word.text in _WAIT_WRAPPERS:
            regions.append(
                _Region(word.start, _statement_end(words, position, end), _WAIT_WRAPPERS[word.text])
            )
        at_command_position = word.text in _COMMAND_POSITION_MARKERS

    # An opener with no `done` is a syntax error, so the command cannot run as
    # written. Reporting the loop anyway is the reading that survives the
    # author fixing their typo.
    regions.extend(_Region(start, end, WaitConstruct.LOOP) for start in open_loops)
    return regions


def _statement_end(words: list[_Word], position: int, end: int) -> int:
    """Offset at which the statement starting at ``position`` ends."""
    for word in words[position + 1 :]:
        if word.text in _STATEMENT_SEPARATORS:
            return word.start
    return end


_LOOP_BODY_OPENER: Final = "do"

#: Commands a loop body may run while still counting as "doing nothing but
#: waiting". A body that acts on anything is not an idle spin, however long it
#: sleeps, so it is out of scope for the unbounded-wait advisory.
_IDLE_BODY_COMMANDS: Final[frozenset[str]] = frozenset(
    {"sleep", "echo", "printf", "date", "true", ":"}
)
_SLEEP: Final = "sleep"

#: Text that proves the author already bounded the loop themselves. An
#: arithmetic expansion is the counter idiom (``i=$((i+1))``) and a numeric
#: test is the cap that reads it, so either one stands the advisory down.
_COUNTER_MARKERS: Final[tuple[str, ...]] = ("((", "-lt", "-le", "-gt", "-ge")


@dataclass(frozen=True, slots=True)
class _LoopStructure:
    """The three word ranges a shell loop is made of."""

    keyword: _Word
    condition: list[_Word]
    body: list[_Word]
    end: int


def _loop_structures(words: list[_Word]) -> list[_LoopStructure]:
    """Locate each ``while``/``until`` loop's condition and body word ranges.

    ``for`` is deliberately excluded: its "condition" is a fixed list, so it
    iterates a known number of times and cannot be an unbounded wait.
    """
    structures: list[_LoopStructure] = []
    stack: list[list[int]] = []
    at_command_position = True

    for position, word in enumerate(words):
        if at_command_position and word.text == _LOOP_CLOSER and stack:
            opener, body_start = stack.pop()
            if body_start >= 0:
                structures.append(
                    _LoopStructure(
                        keyword=words[opener],
                        condition=words[opener + 1 : body_start],
                        body=words[body_start + 1 : position],
                        end=word.end,
                    )
                )
        elif at_command_position and word.text in _CONDITIONAL_LOOP_OPENERS:
            stack.append([position, -1])
        elif word.text == _LOOP_BODY_OPENER and stack and stack[-1][1] < 0:
            stack[-1][1] = position
        at_command_position = word.text in _COMMAND_POSITION_MARKERS

    return structures


def _describe_loop(structure: _LoopStructure, text: str) -> LivenessLoop:
    """Classify one loop: what it waits on, and whether anything caps it."""
    condition = _slice(text, _trim_separators(structure.condition))
    body = _slice(text, _trim_separators(structure.body))
    return LivenessLoop(
        keyword=structure.keyword.text,
        text=text[structure.keyword.start : structure.end],
        condition=condition,
        body=body,
        probes=tuple(_analyse(condition, subject=text, inherited=None)),
        body_only_sleeps=_body_only_sleeps(body),
        bounded=any(marker in condition or marker in body for marker in _COUNTER_MARKERS),
    )


def _slice(text: str, words: list[_Word]) -> str:
    """The source text spanned by ``words``."""
    return text[words[0].start : words[-1].end] if words else ""


def _trim_separators(words: list[_Word]) -> list[_Word]:
    """Drop the statement separators bracketing a condition or body.

    The ``;`` before ``done`` belongs to the loop's syntax, not to its body,
    and leaving it in makes the reported text read as an unfinished command.
    """
    start = 0
    end = len(words)
    while start < end and words[start].text in _STATEMENT_SEPARATORS:
        start += 1
    while end > start and words[end - 1].text in _STATEMENT_SEPARATORS:
        end -= 1
    return words[start:end]


def _body_only_sleeps(body: str) -> bool:
    """Whether every command in ``body`` idles, and at least one sleeps."""
    names = [_basename(span.words[0].text) for span in _spans(_scan_words(body)) if span.words]
    return bool(names) and _SLEEP in names and all(name in _IDLE_BODY_COMMANDS for name in names)


def _construct_at(regions: list[_Region], offset: int) -> WaitConstruct | None:
    """The highest-precedence wait construct enclosing ``offset``."""
    enclosing = {region.construct for region in regions if region.start <= offset < region.end}
    return next(
        (construct for construct in _CONSTRUCT_PRECEDENCE if construct in enclosing),
        None,
    )


# --------------------------------------------------------------------------
# Spans
# --------------------------------------------------------------------------


@dataclass(slots=True)
class _Span:
    """One simple command: its words, and which pipeline it belongs to."""

    words: list[_Word] = field(default_factory=list)
    pipeline: int = 0
    start: int = 0


def _spans(words: list[_Word]) -> list[_Span]:
    """Group ``words`` into simple commands, tracking pipeline membership."""
    spans: list[_Span] = []
    current: _Span | None = None
    pipeline = 0

    for word in words:
        if word.text == _PIPE:
            current = None
            continue
        if word.text in _COMMAND_POSITION_MARKERS:
            current = None
            pipeline += 1
            continue
        if current is None:
            current = _Span(words=[word], pipeline=pipeline, start=word.start)
            spans.append(current)
        else:
            current.words.append(word)

    return spans


# --------------------------------------------------------------------------
# Command resolution
# --------------------------------------------------------------------------

_INTERPRETERS: Final[frozenset[str]] = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_INTERPRETER_SCRIPT_FLAG: Final = "-c"

_GREP_FAMILY: Final[frozenset[str]] = frozenset({"grep", "egrep", "fgrep", "ugrep"})
_KILLERS: Final[frozenset[str]] = frozenset({"kill", "pkill", "killall"})
_XARGS: Final = "xargs"

_PS: Final = "ps"
_KILL: Final = "kill"
_PGREP: Final = "pgrep"
_PKILL: Final = "pkill"

#: `pgrep`/`pkill` options whose FOLLOWING token is a value rather than the
#: pattern. Missing one would read a uid or a terminal name as the pattern.
_SELECTOR_VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "-d",
        "--delimiter",
        "-g",
        "--pgroup",
        "-G",
        "--group",
        "-P",
        "--parent",
        "-s",
        "--session",
        "-t",
        "--terminal",
        "-u",
        "--euid",
        "-U",
        "--uid",
        "-F",
        "--pidfile",
        "--signal",
        "--ns",
        "--nslist",
    }
)

#: The single-letter spellings of the above, for a clustered ``-fu root``.
_SELECTOR_VALUE_LETTERS: Final[frozenset[str]] = frozenset("dgGPstuUF")

_FULL_MATCH_FLAGS: Final[frozenset[str]] = frozenset({"-f", "--full"})
_FULL_MATCH_LETTER: Final = "f"
_EXACT_FLAGS: Final[frozenset[str]] = frozenset({"-x", "--exact"})
_EXACT_LETTER: Final = "x"

_INVERT_FLAGS: Final[frozenset[str]] = frozenset({"-v", "--invert-match"})
_PID_SELECTORS: Final[frozenset[str]] = frozenset({"-p", "--pid", "-q", "--quick-pid"})
_SIGNAL_ZERO: Final = "-0"

#: The shell variable that holds the current shell's own PID, so excluding it
#: is a self-exclusion however it is quoted.
_OWN_PID: Final = "$$"

_SHORT_CLUSTER: Final[re.Pattern[str]] = re.compile(r"^-[A-Za-z0-9]+$")
_END_OF_OPTIONS: Final = "--"


def _basename(text: str) -> str:
    """The command name bash resolves ``text`` to, quoting and path removed."""
    return text.replace(_DOUBLE_QUOTE, "").replace(_SINGLE_QUOTE, "").rsplit("/", 1)[-1]


def _is_quoted_script(text: str) -> bool:
    """Whether ``text`` is a quoted string holding a command rather than a word."""
    if len(text) < 3 or text[0] not in (_SINGLE_QUOTE, _DOUBLE_QUOTE):
        return False
    return text[-1] == text[0] and any(char.isspace() for char in text[1:-1])


def _unquote(text: str) -> str:
    """The value bash would pass, with quoting removed."""
    try:
        parsed = shlex.split(text)
    except ValueError:
        return text.replace(_DOUBLE_QUOTE, "").replace(_SINGLE_QUOTE, "")
    return parsed[0] if parsed else ""


def _is_expanded(raw: str) -> bool:
    """Whether bash would build this word by expansion rather than pass it as-is."""
    if len(raw) >= 2 and raw.startswith(_SINGLE_QUOTE) and raw.endswith(_SINGLE_QUOTE):
        return False
    return "$" in raw or "`" in raw


def _is_redirect(text: str) -> bool:
    return _REDIRECT.match(text) is not None


def _is_bare_redirect(text: str) -> bool:
    """A redirect operator with no target attached, so the target is the next word."""
    match = _REDIRECT.match(text)
    return match is not None and match.end() == len(text)


@dataclass(frozen=True, slots=True)
class _Invocation:
    """A resolved command: its name, its flags and its positional operands."""

    name: str
    flags: tuple[str, ...]
    operands: tuple[str, ...]
    raw_operands: tuple[str, ...]
    construct: WaitConstruct | None


def _strip_wrappers(words: list[_Word]) -> tuple[list[_Word], WaitConstruct | None]:
    """Peel ``watch``/``timeout``/``sudo``/... off the front of a span.

    Returns the remaining words and the wait construct the peeled wrappers
    establish, so ``watch -n 5 pgrep -f x`` resolves to ``pgrep`` while still
    reporting that it is being watched.
    """
    remaining = list(words)
    construct: WaitConstruct | None = None

    while remaining:
        wrapper = _WRAPPERS.get(_basename(remaining[0].text))
        if wrapper is None:
            break
        construct = wrapper.construct or construct
        remaining.pop(0)
        positionals = wrapper.positional_operands
        while remaining:
            token = remaining[0].text
            if token.startswith("-") and token not in ("-", _END_OF_OPTIONS):
                remaining.pop(0)
                if token in wrapper.value_flags and remaining:
                    remaining.pop(0)
                continue
            if positionals > 0:
                remaining.pop(0)
                positionals -= 1
                continue
            break

    return remaining, construct


def _resolve(span: _Span) -> tuple[list[_Word], _Invocation] | None:
    """Resolve a span to the command it actually runs, or None if it runs none."""
    words = [word for word in span.words if not _ASSIGNMENT.match(word.text)]
    words, construct = _strip_wrappers(words)
    if not words:
        return None

    flags: list[str] = []
    operands: list[str] = []
    raw_operands: list[str] = []
    index = 1
    tokens = [word.text for word in words]
    while index < len(tokens):
        token = tokens[index]
        if _is_redirect(token):
            index += 2 if _is_bare_redirect(token) else 1
            continue
        if token == _END_OF_OPTIONS:
            index += 1
            continue
        if token.startswith("-") and token != "-":
            flags.append(token)
            if _takes_a_value(token):
                index += 2
                continue
            index += 1
            continue
        raw_operands.append(token)
        operands.append(_unquote(token))
        index += 1

    return words, _Invocation(
        name=_basename(tokens[0]),
        flags=tuple(flags),
        operands=tuple(operands),
        raw_operands=tuple(raw_operands),
        construct=construct,
    )


def _takes_a_value(token: str) -> bool:
    """Whether ``token``'s following word is this flag's value."""
    if token in _SELECTOR_VALUE_FLAGS:
        return True
    if _SHORT_CLUSTER.match(token) is None:
        return False
    return token[-1] in _SELECTOR_VALUE_LETTERS


def _has_flag(invocation: _Invocation, names: frozenset[str], letter: str | None = None) -> bool:
    """Whether a flag is present, as a lone option or inside a short cluster."""
    if any(flag in names for flag in invocation.flags):
        return True
    if letter is None:
        return False
    return any(
        _SHORT_CLUSTER.match(flag) is not None and letter in flag[1:] for flag in invocation.flags
    )


# --------------------------------------------------------------------------
# Self-match test
# --------------------------------------------------------------------------

_REGEX_METACHARACTERS: Final[frozenset[str]] = frozenset("[](){}.*+?|^$\\")


def _as_python_regex(pattern: str) -> str:
    """Re-spell a POSIX ERE so Python's engine reads it the same way.

    Only the anchors differ in a way that matters here: ERE treats ``^`` as an
    anchor at the start and ``$`` at the end, and both as ORDINARY characters
    anywhere else. Python anchors them wherever they appear, which would read
    the literal pattern ``$PATTERN`` as "end of string, then PATTERN" and find
    no match where the real tool finds one.
    """
    result: list[str] = []
    in_bracket = False
    index = 0
    last = len(pattern) - 1
    while index < len(pattern):
        char = pattern[index]
        if char == _ESCAPE and index < last:
            result.append(pattern[index : index + 2])
            index += 2
            continue
        if in_bracket:
            in_bracket = char != "]"
            result.append(char)
        elif char == "[":
            in_bracket = True
            result.append(char)
        elif char == "^" and index != 0:
            result.append(r"\^")
        elif char == "$" and index != last:
            result.append(r"\$")
        else:
            result.append(char)
        index += 1
    return "".join(result)


def _matches_own_command_line(pattern: str, subject: str) -> bool:
    """Whether ``pattern`` would match the text of the command that runs it.

    A pattern with no metacharacters is answered by containment, which is both
    faster and exact. Anything else is compiled — and an uncompilable pattern
    falls back to containment rather than being waved through, because the tool
    would still have matched the literal text sitting right there.
    """
    if not pattern:
        return False
    if not _REGEX_METACHARACTERS.intersection(pattern):
        return pattern in subject
    try:
        return re.search(_as_python_regex(pattern), subject) is not None
    except re.error:
        return pattern in subject


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


def _analyse(text: str, *, subject: str, inherited: WaitConstruct | None) -> Iterator[ProcessProbe]:
    """Yield every probe in ``text``, in order of appearance.

    Args:
        text: The command text being analysed — the whole command, or the
            script argument of a nested ``bash -c``.
        subject: The command line a probe's pattern is tested against. Always
            the OUTERMOST command, because that is what sits in the shell's
            argv whatever depth the probe was written at.
        inherited: The wait construct enclosing ``text``, when it is nested.
    """
    words = _scan_words(text)
    regions = _wait_regions(words, len(text))
    spans = _spans(words)
    resolved = [(span, _resolve(span)) for span in spans]
    pipelines = _pipeline_index(resolved)

    for span, resolution in resolved:
        if resolution is None:
            continue
        remaining, invocation = resolution
        construct = invocation.construct or _construct_at(regions, span.start) or inherited
        nested = _nested_script(remaining, invocation)
        if nested is not None:
            yield from _analyse(nested, subject=subject, inherited=construct)
            continue
        yield from _probes_for(
            _ProbeContext(
                invocation=invocation,
                span_text=text[span.start : _span_end(span)],
                subject=subject,
                construct=construct,
                downstream=pipelines.get(span.pipeline, ()),
            )
        )


def _span_end(span: _Span) -> int:
    return span.words[-1].end if span.words else span.start


def _pipeline_index(
    resolved: list[tuple[_Span, tuple[list[_Word], _Invocation] | None]],
) -> dict[int, tuple[_Invocation, ...]]:
    """Every resolved invocation, grouped by the pipeline it belongs to."""
    grouped: dict[int, list[_Invocation]] = {}
    for span, resolution in resolved:
        if resolution is not None:
            grouped.setdefault(span.pipeline, []).append(resolution[1])
    return {pipeline: tuple(items) for pipeline, items in grouped.items()}


def _nested_script(words: list[_Word], invocation: _Invocation) -> str | None:
    """The script text an interpreter span runs, or None if it runs no script.

    Two shapes reach here: ``bash -c '<script>'`` and a wrapper handed a quoted
    command (``watch 'pgrep -f x'``), whose first remaining word IS the script.
    """
    if invocation.name in _INTERPRETERS and _INTERPRETER_SCRIPT_FLAG in invocation.flags:
        return invocation.operands[0] if invocation.operands else None
    if invocation.construct is not None and words and _is_quoted_script(words[0].text):
        return _unquote(words[0].text)
    return None


@dataclass(frozen=True, slots=True)
class _ProbeContext:
    """Everything a builder needs to classify one resolved invocation.

    One object rather than five parameters because the builders share a
    signature by contract (they are dispatch-table values), and each uses a
    different subset of it.

    Attributes:
        invocation: The resolved command, flags and operands.
        span_text: The probe's own text, quoted back to the caller.
        subject: The command line a pattern is tested against.
        construct: The wait construct enclosing the probe, if any.
        downstream: The other invocations in the same pipeline.
    """

    invocation: _Invocation
    span_text: str
    subject: str
    construct: WaitConstruct | None
    downstream: tuple[_Invocation, ...]


_ProbeBuilder = Callable[[_ProbeContext], "ProcessProbe | None"]


def _probes_for(context: _ProbeContext) -> Iterator[ProcessProbe]:
    """Yield the probes a single resolved invocation carries."""
    builder = _PROBE_BUILDERS.get(context.invocation.name)
    if builder is None:
        return
    probe = builder(context)
    if probe is not None:
        yield probe


def _pattern_verdict(invocation: _Invocation, subject: str) -> tuple[str | None, ProbeVerdict]:
    """The pattern a ``pgrep``/``pkill`` searches for, and what it can see.

    Name mode and ``-x`` are SAFE by construction, so neither needs the regex
    test: name mode compares against ``comm`` (``bash`` for the waiting shell,
    never the pattern), and ``-x`` demands the WHOLE command line equal the
    pattern rather than contain it.
    """
    if not _has_flag(invocation, _FULL_MATCH_FLAGS, _FULL_MATCH_LETTER):
        return None, ProbeVerdict.SAFE
    if _has_flag(invocation, _EXACT_FLAGS, _EXACT_LETTER):
        return None, ProbeVerdict.SAFE
    if not invocation.operands:
        return None, ProbeVerdict.SAFE
    pattern = invocation.operands[0]
    if _is_expanded(invocation.raw_operands[0]):
        return pattern, ProbeVerdict.UNRESOLVED
    if _matches_own_command_line(pattern, subject):
        return pattern, ProbeVerdict.SELF_MATCHING
    return pattern, ProbeVerdict.SAFE


def _build_pgrep(context: _ProbeContext) -> ProcessProbe | None:
    """``pgrep`` reports matches; a pipeline stage may then act on them."""
    pattern, verdict = _pattern_verdict(context.invocation, context.subject)
    return ProcessProbe(
        kind=ProbeKind.PGREP,
        text=context.span_text,
        pattern=pattern,
        verdict=verdict,
        signals=_pipeline_kills(context.downstream),
        wait_construct=context.construct,
    )


def _build_pkill(context: _ProbeContext) -> ProcessProbe | None:
    """``pkill -f`` signals every match, so a self-match kills the caller."""
    pattern, verdict = _pattern_verdict(context.invocation, context.subject)
    return ProcessProbe(
        kind=ProbeKind.PKILL,
        text=context.span_text,
        pattern=pattern,
        verdict=verdict,
        signals=True,
        wait_construct=context.construct,
    )


def _build_ps(context: _ProbeContext) -> ProcessProbe | None:
    """``ps`` is a probe only once something filters it, or it names a PID."""
    filters = tuple(item for item in context.downstream if item.name in _GREP_FAMILY)
    if not filters:
        if not _has_flag(context.invocation, _PID_SELECTORS):
            return None
        return ProcessProbe(
            kind=ProbeKind.PS_PID,
            text=context.span_text,
            pattern=None,
            verdict=ProbeVerdict.SAFE,
            signals=False,
            wait_construct=context.construct,
        )
    pattern, verdict = _grep_verdict(filters)
    return ProcessProbe(
        kind=ProbeKind.PS_GREP,
        text=context.span_text,
        pattern=pattern,
        verdict=verdict,
        signals=False,
        wait_construct=context.construct,
    )


def _grep_verdict(filters: tuple[_Invocation, ...]) -> tuple[str | None, ProbeVerdict]:
    """Classify a ``ps`` pipeline's grep stages.

    The self-match here is the grep process's OWN line in the ps output, so the
    subject is the grep invocation rather than the whole command. Any stage
    that inverts on ``grep`` or on ``$$`` removes that line, which is the
    documented remedy and stands the whole pipeline down.
    """
    if any(_excludes_itself(item) for item in filters):
        return None, ProbeVerdict.SAFE
    for item in filters:
        if not item.operands:
            continue
        pattern = item.operands[0]
        if _is_expanded(item.raw_operands[0]):
            return pattern, ProbeVerdict.UNRESOLVED
        rendered = f"{item.name} {' '.join(item.raw_operands)}"
        if _matches_own_command_line(pattern, rendered):
            return pattern, ProbeVerdict.SELF_MATCHING
        return pattern, ProbeVerdict.SAFE
    return None, ProbeVerdict.SAFE


def _excludes_itself(invocation: _Invocation) -> bool:
    """Whether this grep stage removes its own line from the ps output."""
    if not _has_flag(invocation, _INVERT_FLAGS):
        return False
    return any(operand in _GREP_FAMILY or _OWN_PID in operand for operand in invocation.operands)


def _build_kill(context: _ProbeContext) -> ProcessProbe | None:
    """Only ``kill -0`` probes. Any other signal ACTS, and is not this module's."""
    if _SIGNAL_ZERO not in context.invocation.flags:
        return None
    return ProcessProbe(
        kind=ProbeKind.KILL_PID,
        text=context.span_text,
        pattern=None,
        verdict=ProbeVerdict.SAFE,
        signals=False,
        wait_construct=context.construct,
    )


def _pipeline_kills(downstream: tuple[_Invocation, ...]) -> bool:
    """Whether a later pipeline stage turns matched PIDs into signals."""
    return any(
        item.name in _KILLERS
        or (
            item.name == _XARGS and any(_basename(operand) in _KILLERS for operand in item.operands)
        )
        for item in downstream
    )


#: Dispatch by command name. A new probe shape adds a builder and a row here;
#: nothing branches on the name anywhere else in the module.
_PROBE_BUILDERS: Final[dict[str, _ProbeBuilder]] = {
    _PGREP: _build_pgrep,
    _PKILL: _build_pkill,
    _PS: _build_ps,
    _KILL: _build_kill,
}
