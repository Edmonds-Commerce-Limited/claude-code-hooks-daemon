"""Shared bounded shell-expansion primitives (Plan 00466 guard-defects review 3).

Every guard that must reason about what a shell WORD could expand to (brace
alternation, a recursive `**` glob) previously built its own bounded
expander. Review 3 found that pattern reintroduces B1's own defect class
every time: review 2's B1 fix, and both of its own new M2 sub-fixes, each
independently made a SAFETY-guard scan slow enough to blow the client's 30s
PreToolUse budget -- and a socket timeout on that budget is an ALLOW for the
whole chain, so a slow scan is a bypass, not a nuisance. Three per-shape caps
(a bounded regex here, a DP cell cap there, a results-count cap somewhere
else) each missed some OTHER unbounded path the same general shape could
still take.

This module is the ONE place expansion is bounded, so there is only one
thing to audit, and every caller inherits the same failure mode: past the
cap, :func:`expand_braces` / :func:`bounded_recursive_glob` raise
``TooManyToEnumerateError`` rather than silently degrading to a
smaller-but-still-eager computation. Callers MUST treat that as fail CLOSED
("cannot rule out a protected path") -- never as "no match" -- exactly the
way ``iter_protected_mentions`` already treats its own ``TimeoutError``.
"""

from __future__ import annotations

import errno
import fnmatch
import itertools
import logging
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)


class TooManyToEnumerateError(Exception):
    """Raised when a bounded expansion primitive gives up rather than
    enumerate past its cap.

    Callers MUST treat this as fail CLOSED -- "cannot rule out a protected
    path" -- never as "no matches". Review 3's cross-cutting finding: each
    of review 2's per-shape fixes independently reintroduced B1's own
    defect (a slow SAFETY-guard scan is a fail-open) precisely because each
    one, past its own cap, fell back to SOME smaller but still-eager
    computation instead of giving up outright. One shared failure mode,
    raised from one shared place, is the structural fix.
    """


# ── Brace expansion ──────────────────────────────────────────────────────

#: One-level ``{a,b,c}`` group. Non-greedy body (`[^{}]*`) so this never
#: backtracks ambiguously -- the cost driver review 3 found was never THIS
#: regex, it was the recursive expansion consuming what it locates.
_BRACE_GROUP_RE: Final[re.Pattern[str]] = re.compile(r"\{([^{}]*)\}")

#: Total concrete spellings one word's brace expansion may produce before
#: :func:`expand_braces` gives up. "A few hundred" per the review's own fix
#: direction -- no legitimate path glob needs anywhere near this many.
DEFAULT_MAX_BRACE_SPELLINGS: Final[int] = 256

#: Recursion depth cap, independent of the spelling cap above -- a WIDE
#: group blows the spelling cap quickly, but a DEEP one (`{a,{a,{a,...}}}`)
#: costs one recursive frame per nesting level regardless of how few
#: alternatives are at each level, and a spelling cap alone never catches a
#: single-alternative-per-level chain (own live finding, own RED test).
DEFAULT_MAX_BRACE_DEPTH: Final[int] = 64

#: Brace GROUPS examined per call to :func:`iter_brace_words` -- bounds the
#: volume cost of many groups butted together across a whole command, not
#: any one group's own expansion (that is `DEFAULT_MAX_BRACE_SPELLINGS`'s
#: job).
DEFAULT_MAX_BRACE_WORDS: Final[int] = 500

#: A brace SEQUENCE body (`{start..end[..step]}`, n466-n24 review 4 M-1): a
#: degenerate single-letter sequence with start == end names a real
#: protected filename this way (a real review-4 finding, not a synthetic
#: example), and was reaching NOTHING before this -- the pre-existing
#: comma-split treated the whole body as one literal alternative, so
#: `{a..a}` spelled the literal text `a..a`, not the single letter `a`.
#: Both endpoints must be the SAME kind (both digits, or both a single
#: letter) -- bash does not mix them, and neither does this.
_SEQUENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<start>-?\d+|[A-Za-z])\.\.(?P<end>-?\d+|[A-Za-z])(?:\.\.(?P<step>-?\d+))?$"
)


def _sequence_alternatives(body: str) -> Iterator[str] | None:
    """Lazy alternatives for a brace SEQUENCE body, or ``None`` when ``body``
    is not sequence-shaped -- the caller falls back to a comma split.

    Lazy (a generator, not a materialised list) is the point: a huge span
    (``{1..100000}``) must fail closed via the SAME ``max_spellings`` cap
    :func:`expand_braces` already enforces on its ``islice``, not by
    building the full list first. A ``range``-driven generator costs O(1)
    to construct regardless of how wide the sequence is, so the cap is
    cheap even for a huge span.
    """
    match = _SEQUENCE_RE.match(body)
    if match is None:
        return None
    start_s, end_s, step_s = match.group("start"), match.group("end"), match.group("step")
    if start_s.lstrip("-").isdigit() and end_s.lstrip("-").isdigit():
        return _numeric_sequence(start_s, end_s, step_s)
    if len(start_s) == 1 and len(end_s) == 1 and start_s.isalpha() and end_s.isalpha():
        return _alpha_sequence(start_s, end_s, step_s)
    return None


def _numeric_sequence(start_s: str, end_s: str, step_s: str | None) -> Iterator[str] | None:
    start, end = int(start_s), int(end_s)
    if step_s is not None:
        if not re.fullmatch(r"-?\d+", step_s) or int(step_s) == 0:
            return None
        magnitude = abs(int(step_s))
    else:
        magnitude = 1
    step = magnitude if end >= start else -magnitude
    # bash zero-pads every element to the widest endpoint WHEN either
    # endpoint literally carries a leading zero (`{01..10}` -> 01..10;
    # `{1..10}` does not pad).
    width = 0
    for literal in (start_s, end_s):
        digits = literal[1:] if literal.startswith("-") else literal
        if len(digits) > 1 and digits.startswith("0"):
            width = max(width, len(digits))

    def _gen() -> Iterator[str]:
        n = start
        while (n <= end) if step > 0 else (n >= end):
            digits = str(abs(n)).rjust(width, "0")
            yield f"-{digits}" if n < 0 else digits
            n += step

    return _gen()


def _alpha_sequence(start_s: str, end_s: str, step_s: str | None) -> Iterator[str] | None:
    if step_s is not None:
        if not re.fullmatch(r"-?\d+", step_s) or int(step_s) == 0:
            return None
        magnitude = abs(int(step_s))
    else:
        magnitude = 1
    start_ord, end_ord = ord(start_s), ord(end_s)
    step = magnitude if end_ord >= start_ord else -magnitude

    def _gen() -> Iterator[str]:
        n = start_ord
        while (n <= end_ord) if step > 0 else (n >= end_ord):
            yield chr(n)
            n += step

    return _gen()


def _raw_brace_expansions(word: str, *, depth: int, max_depth: int) -> Iterator[str]:
    """Lazy, unbounded-in-principle brace expansion of ``word``'s OWN groups.

    A true generator (`yield from` all the way down): pulling only the
    first N items from this via `itertools.islice` touches only the work
    needed to produce those N leaves in traversal order, never the full
    combinatorial tree -- this laziness IS the fix, not a post-hoc
    truncation of an already-built list.
    """
    if depth > max_depth:
        raise TooManyToEnumerateError(
            f"brace nesting exceeds the depth cap ({max_depth}) in {word[:80]!r}"
        )
    match = _BRACE_GROUP_RE.search(word)
    if match is None:
        yield word
        return
    prefix, suffix = word[: match.start()], word[match.end() :]
    body = match.group(1)
    alternatives = _sequence_alternatives(body)
    if alternatives is None:
        alternatives = iter(body.split(","))
    for alternative in alternatives:
        yield from _raw_brace_expansions(
            prefix + alternative + suffix, depth=depth + 1, max_depth=max_depth
        )


def expand_braces(
    word: str,
    *,
    max_spellings: int = DEFAULT_MAX_BRACE_SPELLINGS,
    max_depth: int = DEFAULT_MAX_BRACE_DEPTH,
) -> list[str]:
    """Every concrete spelling of ``word``'s brace groups.

    Raises :class:`TooManyToEnumerateError` when there are more than
    ``max_spellings`` of them, or the nesting is deeper than ``max_depth`` --
    in EITHER case without ever materialising anywhere near the full
    exponential expansion: consumption is capped with
    ``itertools.islice(..., max_spellings + 1)``, so at most
    ``max_spellings + 1`` leaves of the expansion tree are ever visited,
    however many the word's full expansion would actually produce (B1-R3,
    Plan 00466 review 3 -- the prior eager recursive expander took >45s on
    `{a,b}` x 22; this gives up in well under a second on the SAME input).
    """
    spellings = list(
        itertools.islice(
            _raw_brace_expansions(word, depth=0, max_depth=max_depth), max_spellings + 1
        )
    )
    if len(spellings) > max_spellings:
        raise TooManyToEnumerateError(
            f"brace expansion of {word[:80]!r} exceeds {max_spellings} spellings"
        )
    return spellings


def iter_brace_words(text: str, *, max_words: int = DEFAULT_MAX_BRACE_WORDS) -> Iterator[str]:
    """Every raw ``{...}``-carrying, whitespace-delimited WORD in ``text``.

    Anchored on :data:`_BRACE_GROUP_RE`'s own bounded, non-backtracking
    matches, then each match's surrounding non-whitespace run is found with
    a plain linear boundary scan -- deliberately NOT a
    ``\\S*\\{[^{}]*\\}\\S*`` regex. That shape was tried first (twice,
    independently, in two different modules) and measured
    CATASTROPHICALLY slow on adversarial input carrying no ``{``/``}`` at
    all: the engine backtracks over every possible split point of the
    greedy ``\\S*`` before concluding there is no brace group to anchor on
    (15s at 94 KB, >45s at 200 KB -- M-3, Plan 00466 review 3). This is now
    the ONE place that logic lives, replacing both modules' own copies.

    Bounded to the first ``max_words`` DISTINCT words: many brace groups
    butted together with no separating whitespace (so each one's own
    boundary scan re-walks a growing shared span) is a volume cost the same
    way a huge run of ordinary tokens is -- no single group is pathological,
    the risk is many of them. A word carrying SEVERAL groups (``x{a,b}{c,d}
    {e,f}y``) is matched once per group by ``_BRACE_GROUP_RE``, but its
    boundary scan always resolves to the SAME enclosing span -- re-yielding
    it once per internal group would re-run its (already-capped, but not
    free) brace expansion redundantly, so a match already covered by the
    PREVIOUS yielded span is skipped without counting against the cap or
    doing a second boundary scan.

    Past ``max_words`` this RAISES :class:`TooManyToEnumerateError` (review
    7 MAJOR-1) rather than silently stopping: a caller consuming this
    generator up to the cap and then treating exhaustion as "no more brace
    words" would allow a mention placed only in the (undiscovered) words
    past the cap -- the same fail-open B1-R3's own eager-expansion fix was
    written to close, reintroduced at the ENUMERATION boundary instead of
    the expansion one. Every existing caller already treats
    ``TooManyToEnumerateError`` from :func:`expand_braces` as fail-closed,
    so this raises the identical exception rather than inventing a second
    "give up" signal.
    """
    count = 0
    last_end = 0
    for match in _BRACE_GROUP_RE.finditer(text):
        if match.start() < last_end:
            continue  # already inside the span just yielded
        if count >= max_words:
            raise TooManyToEnumerateError(
                f"more than {max_words} brace-carrying words in a single command"
            )
        count += 1
        start = match.start()
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        end = match.end()
        while end < len(text) and not text[end].isspace():
            end += 1
        last_end = end
        yield text[start:end]


# ── Word normalisation (quotes, escapes, unresolved substitutions) ──────────
#
# n466-n24 review 4, M-1: brace expansion alone is not the whole "what could
# this WORD really spell" class. A shell strips quotes and backslash escapes
# and concatenates the pieces into ONE word before anything else sees it, so
# a mention scan that keys on the RAW text (quote characters as plain token
# delimiters, as `secret_file_matching._tokenise` does) tears a legitimately
# assembled word apart before any spelling can be recognised -- the same
# defect class `TestBraceExpansionBeforeTokenising` fixed for `,`. And a part
# of a word this cannot resolve without actually RUNNING a shell (`$VAR`,
# `${...}`, `$(...)`, a backtick, `$((...))`) must not be silently dropped
# either: turning it into a single `*` makes the WHOLE word a glob, so the
# caller's existing glob-intersection machinery (`_globs_can_intersect`) can
# still judge whether it could reach a protected path -- denying only when a
# match is genuinely POSSIBLE, so an ordinary `$VAR`-rooted path stays
# allowed.

#: Words yielded per call to :func:`iter_normalised_shell_words` -- bounds
#: the volume cost of a command built from many separate words, the same
#: direction :data:`DEFAULT_MAX_BRACE_WORDS` bounds for brace groups.
DEFAULT_MAX_NORMALISED_WORDS: Final[int] = 2000

#: Characters that end a shell WORD when found UNQUOTED. Mirrors
#: ``secret_file_matching._TOKEN_DELIMITERS``'s operator set, minus the
#: quote/``$``/backtick characters this module decodes instead of discarding.
_WORD_SEPARATOR_CHARS: Final[str] = " \t\n;|&<>()"

# n466-n24 review 5 minor-1: a `bash -c '...'`/`sh -c '...'`/`eval '...'`
# ARGUMENT is itself a nested shell command -- its own quotes only resolve
# once the outer word decode has already spliced them together (a filename
# split across an escaped mid-word quote decodes on the outer pass to a word
# that STILL carries a literal quote character -- only a SECOND decode pass,
# run on that word as its own command, reveals the real one-word filename).
# Names the recognised interpreter basenames (a leading path like
# `/bin/bash` is stripped before comparing) and the recursion's two
# independent bounds.
_SHELL_INTERPRETER_BASENAMES: Final[frozenset[str]] = frozenset(
    {
        "sh",
        "bash",
        "zsh",
        "dash",
        "ksh",
        "ash",
        "mksh",
        "csh",
        "tcsh",
        "fish",
        # Review 7 MAJOR-3: restricted/alternative shells missing before.
        "rbash",
        "yash",
        "posh",
        "pdksh",
    }
)

#: A version-suffixed shell binary name (`bash5`, `bash5.1`) -- review 6
#: minor-1. Only a bare trailing digit run (optionally dotted) counts;
#: `bash-static`/`zshrc` are ordinary non-matches, not shells with a weird
#: suffix.
_VERSIONED_SHELL_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:sh|bash|zsh|dash|ksh|ash|mksh|csh|tcsh)\d[\d.]*$"
)


def _is_shell_interpreter(basename: str) -> bool:
    """Is ``basename`` (already stripped of any leading path) a recognised
    shell -- a literal name, or a version-suffixed one (`bash5`)?"""
    return basename in _SHELL_INTERPRETER_BASENAMES or bool(
        _VERSIONED_SHELL_NAME_RE.match(basename)
    )


_EVAL_COMMAND_NAME: Final[str] = "eval"

# review 6 minor-1: three wrapper SHAPES whose own `-c`-style (or implicit)
# code argument is not preceded by a recognised SHELL name at all, so the
# per-word "any shell name anywhere" trigger never fires for them on its
# own.
#
#: `flock <file> -c CMD` / `su [-] USER -c CMD` / `script FILE -c CMD`
#: (review 7 MAJOR-3: `su`/`script` moved here from the strict set above)
#: -- the code flag can follow one or more POSITIONAL words first, so the
#: option walk must not stop at the first non-option word the way a real
#: interpreter's does.
_TOLERANT_DASH_C_WRAPPER_BASENAMES: Final[frozenset[str]] = frozenset({"flock", "su", "script"})

#: `watch [options] COMMAND` runs `COMMAND` via a shell internally with NO
#: introducing flag at all -- the first non-option word (after skipping the
#: wrapper's own flags, including `-n`/`--interval`'s separate value) IS
#: the code.
_IMPLICIT_CODE_WRAPPER_BASENAMES: Final[frozenset[str]] = frozenset({"watch"})
_IMPLICIT_CODE_VALUE_FLAGS: Final[frozenset[str]] = frozenset({"-n", "--interval"})

#: Wrappers that pass an EXISTING pipeline's stdin straight through to
#: whatever comes next -- `echo … | sudo bash`, `… | env bash` still feed
#: the echoed text to `bash`. Consulted only while resolving a pending
#: echo/printf-to-shell pipe; elsewhere these names carry no special
#: meaning (each is ALSO an ordinary word, still yielded).
_PIPE_WRAPPER_BASENAMES: Final[frozenset[str]] = frozenset(
    {"sudo", "env", "nice", "timeout", "nohup", "exec", "command", "doas", "stdbuf", "ionice"}
)

#: `echo … | tee /dev/null | bash` -- `tee` forwards the SAME bytes on to
#: its own stdout (as well as to a file), so pending pipe content must
#: survive a `tee` stage rather than being dropped there.
#: `cat` (review 7 MAJOR-3, in addition to `tee`) also forwards its stdin
#: on unmodified when given no filename operands to read instead
#: (`echo … | cat | bash`) -- the common form; `cat somefile | bash` would
#: forward `somefile`'s content instead, a residual this conservative
#: passthrough treatment does not distinguish (fails toward recursing into
#: MORE text, never less).
_PIPE_PASSTHROUGH_BASENAMES: Final[frozenset[str]] = frozenset({"tee", "cat"})

# Review 7 MAJOR-3: a pipe-wrapper's OWN option words were previously
# invisible -- `echo … | sudo -u root bash` treated `-u` as neither a
# wrapper, a shell, nor `tee`, so the pending pipe content was silently
# dropped (fail-open) rather than the walk continuing past `-u root` to
# find `bash`. Each wrapper below now has its OWN table of value-taking
# short/long options, walked exactly like `_classify_interpreter_option_
# word` walks an interpreter's -- but this is a SEPARATE table because a
# wrapper's flags (`-u USER`, `-n ADJUSTMENT`) have nothing to do with an
# interpreter's (`-c CODE`).
#: Short flags that take their value as the NEXT word.
_WRAPPER_SHORT_VALUE_FLAGS: Final[dict[str, frozenset[str]]] = {
    "sudo": frozenset({"-u", "-g", "-p", "-h", "-C", "-r", "-t"}),
    "doas": frozenset({"-u"}),
    "env": frozenset({"-u", "-C", "-S"}),
    "nice": frozenset({"-n"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "ionice": frozenset({"-c", "-n", "-p", "-t"}),
}
#: Long flags (bare, no `=`) that take their value as the NEXT word.
_WRAPPER_LONG_VALUE_FLAGS: Final[dict[str, frozenset[str]]] = {
    "sudo": frozenset({"--user", "--group", "--prompt", "--chdir", "--host", "--close-from"}),
    "doas": frozenset({"--user"}),
    "env": frozenset({"--unset", "--chdir", "--split-string"}),
    "nice": frozenset({"--adjustment"}),
}
#: Mandatory POSITIONAL arguments (not introduced by any flag) a wrapper
#: consumes before its command word -- only `timeout DURATION COMMAND`
#: needs this among the wrappers here.
_WRAPPER_POSITIONAL_COUNT: Final[dict[str, int]] = {"timeout": 1}

#: `env`'s `VAR=value` assignments, positional and flag-free, ahead of the
#: command it runs (`env FOO=bar bash`).
_ENV_ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _classify_wrapper_option_word(wrapper: str, word: str) -> str:
    """Classify one word while walking ``wrapper``'s OWN options/positionals
    (a pipe-to-shell wrapper such as `sudo`/`env`/`timeout`, never an
    interpreter's `-c` flags -- see :func:`_classify_interpreter_option_word`
    for that).

    Returns ``"value"`` (the NEXT word is this flag's value -- skip it and
    keep walking), ``"skip"`` (a plain flag, a glued value, or an `env
    VAR=value` assignment -- nothing more to consume), or ``"command"``
    (not a flag/assignment/expected positional -- this word IS the
    wrapper's command, or the head of a further wrapper).
    """
    if wrapper == "env" and _ENV_ASSIGNMENT_RE.match(word):
        return "skip"
    if word.startswith("--"):
        if "=" in word:
            return "skip"
        return "value" if word in _WRAPPER_LONG_VALUE_FLAGS.get(wrapper, frozenset()) else "skip"
    if len(word) > 1 and word[0] == "-":
        if word in _WRAPPER_SHORT_VALUE_FLAGS.get(wrapper, frozenset()):
            return "value"
        if word[:2] in _WRAPPER_SHORT_VALUE_FLAGS.get(wrapper, frozenset()):
            return "skip"  # glued value, e.g. `-uroot`/`-n5`
        return "skip"  # an unrecognised flag -- best-effort: assume no value
    return "command"

#: Nesting levels of `-c`/`eval` re-parsing followed (`bash -c 'bash -c
#: "..."'` could recurse arbitrarily) -- independent of the per-level
#: word-count bound above, which does not limit how deep the nesting goes.
_MAX_NESTED_SHELL_DEPTH: Final[int] = 4

#: Total bytes of nested `-c`/`eval` ARGUMENT text re-parsed across the
#: WHOLE call (shared across every level, not reset per level) -- bounds the
#: aggregate re-parsing cost regardless of how the nesting is shaped, the
#: same direction the other bounds in this module cap their own cost.
_MAX_NESTED_SHELL_BYTES: Final[int] = 32768


def _interpreter_basename(word: str) -> str:
    """``word`` with any leading path stripped (e.g. `/bin/bash` -> `bash`)."""
    return word.rsplit("/", 1)[-1]


# n466-n24 review 6: three more nested-command shapes, closed rather than
# left as documented residuals, per team-lead's "no known defects" bar.
#
# (1) A FLAG between the interpreter and `-c` (`bash -x -c '…'`,
#     `bash --norc -c`, `bash -lc` with `-c` clustered, `bash -O extglob -c`)
#     was not recognised -- only bare adjacency was. `_classify_interpreter_
#     option_word` below walks long options, short-flag clusters (`-c`
#     recognised ANYWHERE in a cluster) and known arg-taking options
#     (`-o`/`-O`, `--rcfile`/`--init-file`, glued or as a separate word).
#
# (2) `eval` joins ALL its own argument words with a single space each and
#     RE-PARSES the joined result -- only the single word immediately after
#     `eval` was recursed into before. Collection runs until a genuine shell
#     command terminator (`;|&<>()`), mirrored by `source`/`.` piping a
#     literal `echo`/`printf` producer's output through the same join
#     (`source <(echo '…')`), and by a literal `echo '…' | bash` feeding a
#     shell's stdin the same way.
#
# (3) `source <(…)` / `. <(…)` whose substituted command is NOT a literal
#     `echo`/`printf` is judged by its OWN command text instead (since
#     1aa15f32, review 6 MAJOR-2) -- a non-literal producer with no
#     mention of its own (`kubectl completion bash`) is no longer failed
#     closed just for being unrecognised.
_COMMAND_TERMINATOR_CHARS: Final[str] = ";|&<>()"
_HERE_STRING_OPERATOR: Final[str] = "<<<"
_PROCESS_SUBSTITUTION_OPERATOR: Final[str] = "<("
#: `> >(...)` -- an OUTPUT process substitution: whatever is redirected
#: INTO it becomes that command's stdin (review 7 MAJOR-3).
_OUTPUT_PROCESS_SUBSTITUTION_OPERATOR: Final[str] = ">("
#: Operator characters that genuinely END a bare interpreter's chance of a
#: trailing here-string (review 7 MAJOR-3) -- deliberately NOT the full
#: `_COMMAND_TERMINATOR_CHARS` set: `<`/`>` are ordinary REDIRECTS that can
#: legitimately sit between the interpreter and its here-string
#: (`bash 2>/dev/null <<<'...'`), not a command boundary.
_BARE_HERESTRING_STOP_CHARS: Final[str] = ";|&()"
_PIPE_OPERATOR: Final[str] = "|"
_LITERAL_PRODUCER_COMMANDS: Final[frozenset[str]] = frozenset({"echo", "printf"})
_SOURCE_COMMAND_NAMES: Final[frozenset[str]] = frozenset({"source", "."})

#: Long options that take their value as the NEXT word (`--rcfile FILE`).
#: Everything else starting with `--` is assumed to take no argument.
_LONG_OPTIONS_WITH_ARG: Final[frozenset[str]] = frozenset({"--rcfile", "--init-file"})

#: Short-option characters that take a value, either glued into the same
#: token (`-opipefail`) or as the next word (`-o pipefail`) -- `-o
#: option-name` and `-O shopt-name`.
_SHORT_OPTIONS_WITH_ARG: Final[str] = "oO"


def _classify_interpreter_option_word(word: str) -> str:
    """Classify one word while walking `<interpreter> [options...]`.

    Returns one of:

    - ``"dash_c"`` -- a `c` appears anywhere in this word's short-option
      cluster (or the word IS `-c`). The CODE argument is the NEXT word,
      wherever `c` sat in the cluster -- once bash sees `-c` it takes the
      following ARGV word wholesale as the command string, so anything
      past `c` in the SAME token is not meaningfully distinguishable here.
    - ``"value_glued"`` -- an arg-taking short option (`-o`/`-O`) whose
      value is glued into this SAME token (`-opipefail`) -- nothing more
      to consume.
    - ``"value_separate"`` -- an arg-taking option (`-o`, `-O`, or a known
      long option) whose value is the NEXT word.
    - ``"plain"`` -- an ordinary flag with no argument (`-x`, `--norc`,
      `-lc` is handled by "dash_c" above since it contains `c`).
    - ``"non_option"`` -- not an option word -- this is a `<interpreter>`
      invocation with no `-c` found; option-walking stops here.

    Two operand spellings of "read the script from stdin" (`bash -`, `bash
    /dev/stdin`) are recognised as ``"plain"`` (review 6 MAJOR-1) -- the
    same direction `-s` already was -- so a following here-string is still
    found rather than the walk stopping here as an ordinary non-option word.
    ``/dev/fd/0``/``/proc/self/fd/0`` (review 7 MAJOR-3) are the same
    stdin-alias family.

    Two more return values, both review 7 MAJOR-3 (`su`/`script`'s long
    `--command` form, walked through this SAME classifier since both are
    entered via ``scanning_interpreter_options``):

    - ``"dash_c"`` also covers a bare ``--command`` word (the NEXT word is
      the code, exactly like a real interpreter's `-c`).
    - ``"dash_c_glued_command"`` -- ``--command=CODE``, the code glued into
      THIS token with no further word to wait for.
    """
    if word in ("-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"):
        return "plain"
    if word == "--command":
        return "dash_c"
    if word.startswith("--command="):
        return "dash_c_glued_command"
    if word.startswith("--"):
        return "value_separate" if word in _LONG_OPTIONS_WITH_ARG else "plain"
    # bash's `+`-form options (`+x`, `+O value`) are the mirror image of
    # `-x`/`-O value` and walked identically (review 6 MAJOR-1) -- the sign
    # character only changes the FLAG's runtime effect, never how many
    # words it occupies.
    if len(word) > 1 and word[0] in "-+":
        for position in range(1, len(word)):
            char = word[position]
            if char == "c":
                return "dash_c"
            if char in _SHORT_OPTIONS_WITH_ARG:
                return "value_glued" if position + 1 < len(word) else "value_separate"
        return "plain"
    return "non_option"

#: ANSI-C (`$'...'`) single-character escapes with no numeric argument.
_ANSI_C_SIMPLE_ESCAPES: Final[dict[str, str]] = {
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "?": "?",
}


def _decode_ansi_c_body(body: str) -> str:
    """Decode a ``$'...'`` ANSI-C-quoted body's backslash escapes: the
    simple single-character forms above, ``\\xHH`` (1-2 hex digits),
    ``\\NNN`` (1-3 octal digits), ``\\uHHHH`` and ``\\UHHHHHHHH`` (1-4/1-8
    hex digits). An escape this does not recognise keeps both the
    backslash and the following character, bash's own behaviour for one it
    does not know either.
    """
    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt in _ANSI_C_SIMPLE_ESCAPES:
            out.append(_ANSI_C_SIMPLE_ESCAPES[nxt])
            i += 2
        elif nxt == "x":
            match = re.match(r"[0-9A-Fa-f]{1,2}", body[i + 2 : i + 4])
            if match:
                out.append(chr(int(match.group(0), 16)))
                i += 2 + len(match.group(0))
            else:
                out.append(ch)
                i += 1
        elif nxt in "01234567":
            match = re.match(r"[0-7]{1,3}", body[i + 1 : i + 4])
            assert match is not None  # nxt itself is already an octal digit
            out.append(chr(int(match.group(0), 8) & 0xFF))
            i += 1 + len(match.group(0))
        elif nxt in "uU":
            width = 4 if nxt == "u" else 8
            match = re.match(rf"[0-9A-Fa-f]{{1,{width}}}", body[i + 2 : i + 2 + width])
            if match:
                out.append(chr(int(match.group(0), 16)))
                i += 2 + len(match.group(0))
            else:
                out.append(ch)
                i += 1
        else:
            out.append(ch)
            out.append(nxt)
            i += 2
    return "".join(out)


#: A `$name` bareword: an identifier, or one of the single-character
#: special parameters (`$1`, `$@`, `$?`, `$$`, `$!`, `$#`, `$-`, `$*`, `$0`).
_DOLLAR_VAR_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9@*?$!#-]")


def _consume_balanced(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """``text[start] == open_ch``: the index just past the MATCHING
    ``close_ch``, tracking nesting depth (handles `$((...))` as two nested
    `(`/`)` pairs for free). Unterminated input returns ``len(text)`` --
    consuming to the end rather than looping, so a malformed substitution
    can never cause a caller to revisit already-scanned bytes.
    """
    depth = 0
    i = start
    n = len(text)
    while i < n:
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _consume_dollar(
    text: str, start: int, *, substitutions: list[str] | None = None
) -> tuple[str, int]:
    """At ``text[start] == '$'``: ``(piece, end)``.

    ``piece`` is statically-decoded text for the one form this CAN resolve
    without running a shell (``$'...'`` ANSI-C quoting), or the single
    character ``'*'`` for every form it cannot (``$VAR``, ``${...}``,
    ``$(...)``, ``$((...))``) -- turning the word carrying it into a GLOB
    rather than silently dropping the substitution's contribution. ``end``
    is always ``> start``, so a caller advancing by it can never loop even
    on a malformed/unterminated form.

    Review 7 MAJOR-2: when ``substitutions`` is given, ``$(...)``'s RAW
    body text (between the parens, before any decoding) is appended to it
    -- this is a genuine nested COMMAND, unlike ``$VAR``/``${...}``, and the
    caller (:func:`_iter_normalised_shell_words`) re-parses each captured
    body as its own command, the same way a process substitution's body
    already is. ``$((...))`` (arithmetic) is captured too, since balanced-
    paren matching cannot distinguish it from `$(...)` without a real
    parser -- re-parsing arithmetic text as a "command" costs a wasted scan
    with nothing to match, never a false allow.
    """
    n = len(text)
    if start + 1 >= n:
        return "$", start + 1
    nxt = text[start + 1]
    if nxt == "'":
        i = start + 2
        while i < n:
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == "'":
                break
            i += 1
        body = text[start + 2 : min(i, n)]
        end = min(i, n) + 1 if i < n else n
        return _decode_ansi_c_body(body), end
    if nxt == "(":
        end = _consume_balanced(text, start + 1, "(", ")")
        if substitutions is not None:
            body = text[start + 2 : max(end - 1, start + 2)]
            if body:
                substitutions.append(body)
        return "*", end
    if nxt == "{":
        return "*", _consume_balanced(text, start + 1, "{", "}")
    match = _DOLLAR_VAR_NAME_RE.match(text, start + 1)
    if match and match.end() > start + 1:
        return "*", match.end()
    return "$", start + 1


def _decode_span(
    text: str, start: int, stop_chars: str, *, substitutions: list[str] | None = None
) -> tuple[str, int]:
    """Quote/escape/substitution-decode ``text`` from ``start``, stopping at
    the first UNQUOTED character in ``stop_chars`` (or at the end of
    ``text`` when ``stop_chars`` is empty) -- the one shared scanner behind
    both :func:`normalise_word` (a single already-isolated word, never
    stops early) and :func:`iter_normalised_shell_words` (a whole command,
    splitting on unquoted whitespace/operators).

    Review 7 MAJOR-2: ``substitutions``, when given, collects the raw body
    text of every ``$(...)`` and backtick command substitution encountered
    (inside or outside a double-quoted span) -- see
    :func:`_consume_dollar`'s docstring. ``None`` (the default, used by
    :func:`normalise_word`) keeps the prior behaviour of collapsing them to
    a bare ``*`` with nothing collected.
    """
    out: list[str] = []
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if stop_chars and ch in stop_chars:
            break
        if ch == "'":
            j = text.find("'", i + 1)
            if j == -1:
                out.append(text[i + 1 :])
                i = n
            else:
                out.append(text[i + 1 : j])
                i = j + 1
            continue
        if ch == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n and text[i + 1] in ("\\", '"', "$", "`", "\n"):
                    if text[i + 1] != "\n":
                        out.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == "$":
                    piece, end = _consume_dollar(text, i, substitutions=substitutions)
                    out.append(piece)
                    i = end
                    continue
                if text[i] == "`":
                    j = text.find("`", i + 1)
                    if substitutions is not None and j != -1:
                        substitutions.append(text[i + 1 : j])
                    out.append("*")
                    i = (j + 1) if j != -1 else n
                    continue
                out.append(text[i])
                i += 1
            if i < n and text[i] == '"':
                i += 1
            continue
        if ch == "\\":
            if i + 1 < n:
                if text[i + 1] == "\n":
                    i += 2
                else:
                    out.append(text[i + 1])
                    i += 2
            else:
                i += 1
            continue
        if ch == "$":
            piece, end = _consume_dollar(text, i, substitutions=substitutions)
            out.append(piece)
            i = end
            continue
        if ch == "`":
            j = text.find("`", i + 1)
            if substitutions is not None and j != -1:
                substitutions.append(text[i + 1 : j])
            out.append("*")
            i = (j + 1) if j != -1 else n
            continue
        out.append(ch)
        i += 1
    return "".join(out), i


def normalise_word(word: str) -> str:
    """``word`` with quotes removed, backslash escapes and ``$'...'``
    ANSI-C sequences decoded, and any unresolvable substitution collapsed
    to a single ``*``.

    For a single already-isolated word (e.g. one spelling
    :func:`expand_braces` already produced -- a brace ALTERNATIVE can
    itself carry a quote, ``{'a',x}``, which needs this pass too, run
    AFTER brace expansion so the composition matches what a shell actually
    does: strip quotes from the concrete spelling, not from the group
    template).
    """
    decoded, _ = _decode_span(word, 0, "")
    return decoded


#: `echo -e`/`-ne`/`-en` -- the common, single-token spellings of "turn on
#: backslash-escape interpretation". A combined cluster carrying anything
#: else (`-ne x`) is deliberately NOT matched here -- see
#: :func:`_resolve_collected_producer_text`'s docstring for the scope this
#: leaves out.
_ECHO_ESCAPE_FLAGS: Final[frozenset[str]] = frozenset({"-e", "-ne", "-en"})


def _resolve_collected_producer_text(head: str | None, words: list[str]) -> str:
    """The text a collected ``eval``/``echo``/``printf``/other-producer
    argument list resolves to, once joined -- review 6 MAJOR-1: "printf and
    echo -e are NOT literal producers", so a plain space-join (correct for
    ``eval`` and for a bare ``echo``) is no longer applied unconditionally.

    - ``echo`` with a leading ``-e``/``-ne``/``-en`` flag word: that flag is
      dropped and the REST is backslash-escape decoded (reusing the same
      decoder :func:`_consume_dollar` uses for ``$'...'`` bodies -- echo's
      escape table is a subset of ANSI-C's, so this is a safe superset, not
      an exact match).
    - ``printf``: backslash escapes are ALWAYS interpreted in printf's
      format (unconditionally, unlike echo), so the whole joined text is
      decoded the same way.
    - Anything else (plain ``echo``, ``eval``, or a non-producer command's
      own text inside a process substitution): an unmodified space join --
      exactly the previous behaviour.

    Deliberately NOT a printf format-directive engine: ``%s``/``%d`` are
    left as literal text in the output, with every operand word still
    present (space-joined) alongside them. That is sufficient for MENTION
    detection -- a protected word supplied as an operand is still findable
    as its own word -- even though the reconstructed text does not
    positionally substitute it the way real ``printf`` would.
    """
    content = list(words)
    if head == "echo" and content and content[0] in _ECHO_ESCAPE_FLAGS:
        content = content[1:]
        return _decode_ansi_c_body(" ".join(content))
    if head == "printf":
        return _decode_ansi_c_body(" ".join(content))
    return " ".join(content)


#: A heredoc introducer whose delimiter is QUOTED or backslash-escaped
#: (`<<'EOF'`, `<<"EOF"`, `<<\EOF`, `<<-'EOF'`) -- review 7 follow-up
#: (team-lead): this spelling means bash treats the BODY as literal data,
#: expanding nothing in it (no `$(...)`, no `$VAR`, no backtick) -- exactly
#: the inverse of an UNQUOTED delimiter (`<<EOF`), which still undergoes
#: expansion and so stays fully scanned by :func:`_iter_normalised_shell_
#: words` the ordinary way.
_HEREDOC_QUOTED_INTRODUCER_RE: Final[re.Pattern[str]] = re.compile(
    r"<<(-)?[ \t]*(?:'([A-Za-z_][A-Za-z0-9_]*)'"
    r"|\"([A-Za-z_][A-Za-z0-9_]*)\""
    r"|\\([A-Za-z_][A-Za-z0-9_]*))"
)


def _heredoc_body_skip_ranges(command: str) -> list[tuple[int, int]]:
    """``(start, end)`` byte ranges of every QUOTED-delimiter heredoc BODY
    in ``command`` -- the body only, not its introducer or closing-
    delimiter line.

    A quoted-delimiter heredoc body is inert data handed to a CONSUMER
    (``cat > f <<'EOF'``, ``tee``, ``git commit -F- <<'EOF'``) -- nothing
    in it can be a shell trigger, since the surrounding shell expands
    NOTHING in it either. It can legitimately be large (long prose, a
    generated file), so counting its every word against the volume cap
    :func:`_iter_normalised_shell_words` enforces would deny an everyday
    command for no security benefit -- the OTHER token streams
    (``_tokenise``/``_brace_expansion_tokens`` in ``secret_file_matching``)
    still scan this same span for a literal mention, unaffected by this
    exclusion, which is scoped to nested-COMMAND discovery only.

    ``<<-`` (the tab-stripping form) is honoured: the closing line may be
    indented with tabs, stripped before comparing to the delimiter.
    """
    ranges: list[tuple[int, int]] = []
    n = len(command)
    for match in _HEREDOC_QUOTED_INTRODUCER_RE.finditer(command):
        strip_tabs = match.group(1) is not None
        delimiter = match.group(2) or match.group(3) or match.group(4)
        newline = command.find("\n", match.end())
        if newline == -1:
            continue  # no body at all (introducer is the last line)
        body_start = newline + 1
        cursor = body_start
        closing_start = n
        while cursor <= n:
            line_end = command.find("\n", cursor)
            line_stop = line_end if line_end != -1 else n
            line = command[cursor:line_stop]
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate == delimiter:
                closing_start = cursor
                break
            if line_end == -1:
                break
            cursor = line_end + 1
        ranges.append((body_start, closing_start))
    return ranges


def iter_normalised_shell_words(
    command: str, *, max_words: int = DEFAULT_MAX_NORMALISED_WORDS
) -> Iterator[str]:
    """Every shell WORD in ``command``, quote/escape-decoded, with any
    statically-unresolvable substitution collapsed to a single ``*``.

    Deliberately conservative, not a real shell: quote removal, backslash
    escapes and ``$'...'`` ANSI-C decoding are resolved exactly (POSIX/bash
    rules); anything that would need to actually RUN a shell to resolve
    becomes a single ``*``, so the word this yields is then judged as a
    GLOB by the caller's existing glob-intersection machinery, exactly like
    a literal ``*``/``?``/bracket expression the caller already handles.
    Fails toward denying more, never toward silently dropping a
    substitution's contribution to a word.

    Bounded to the first ``max_words`` words, the same direction
    :func:`iter_brace_words` bounds its own volume.

    n466-n24 review 5 minor-1 / review 6: several shapes feed a NESTED
    command through as literal text, whose own quotes/escapes only resolve
    on a SECOND parse -- each is recognised and re-parsed with this SAME
    function, recursively, bounded by ``_MAX_NESTED_SHELL_DEPTH``/
    ``_MAX_NESTED_SHELL_BYTES`` (shared across every shape and every
    nesting level):

    - ``<interpreter> [options...] -c <code>`` -- a proper option walk,
      including bash's `+`-form options (`+x`, `+O value`), not just their
      `-`-form mirrors; long options, short clusters with `-c` recognised
      anywhere in one, `-o`/`-O`/`--rcfile`/`--init-file` consuming a value
      glued or separate; see :func:`_classify_interpreter_option_word`.
      Also entered for `su -c`/`script -c` (never preceded by a positional
      word) and, tolerantly, `flock <file> -c` (a positional word first is
      fine); `watch [options] CODE` has no introducing flag at all and is
      handled separately.
    - ``eval <words...>`` -- every argument word is reassembled with a
      SINGLE space each (matching eval's own semantics) and the join is
      re-parsed, not just the first word. ``builtin eval ...``/
      ``command eval ...`` are covered for free (this triggers on the
      literal word ``eval`` appearing at all).
    - A process substitution ``<(...)`` ANYWHERE (after `source`/`.`, as an
      interpreter's own script `bash <(...)`, or as a plain argument to any
      other command) -- collected and re-parsed as its own nested command,
      the same way `eval`'s argument is. `echo`/`printf` are joined the way
      they actually print (see below); anything else is judged by its OWN
      command text -- denied only if THAT text mentions a protected path,
      never failed closed just for being an unrecognised producer.
    - ``echo|printf '...' | <interpreter>`` (no ``-c``, i.e. reading
      stdin) -- the producer's joined output is what the shell executes,
      re-parsed the same way. The pipeline may carry the shell behind a
      wrapper (`sudo`/`env`/`nice`/`timeout`/`nohup`/`exec`/`command`/
      `doas`), the shell may carry its own flags (`bash -s`, `bash -x`),
      and a `tee` stage in between still forwards the content on.
    - ``<interpreter> [-s|-|/dev/stdin] <<<'...'`` (a here-string, with no
      ``-c``) -- bash reads its own stdin as the script; `source`/`.
      /dev/stdin <<<...` reads the same way.
    - ``echo``'s ``-e``/``-ne``/``-en`` and ``printf``'s ALWAYS-interpreted
      format both undergo backslash-escape decoding before being re-parsed
      -- see :func:`_resolve_collected_producer_text` for what is (and is
      not) simulated.
    """
    remaining_bytes = [_MAX_NESTED_SHELL_BYTES]
    yield from _iter_normalised_shell_words(
        command, max_words=max_words, depth=0, remaining_bytes=remaining_bytes
    )


def _recurse_into_nested_command(
    text: str,
    *,
    max_words: int,
    depth: int,
    remaining_bytes: list[int],
) -> Iterator[str]:
    """Shared recursion entry point for every nested-command trigger in
    :func:`_iter_normalised_shell_words` -- one place enforcing both
    bounds identically, and failing CLOSED (raising) past either: "cannot
    rule out a protected path" must never be conflated with "no protected
    path" (this module's existing doctrine for
    :func:`expand_braces`/:func:`bounded_recursive_glob`).
    """
    if depth >= _MAX_NESTED_SHELL_DEPTH:
        raise TooManyToEnumerateError("nested shell re-parsing exceeded its depth bound")
    if remaining_bytes[0] <= 0:
        raise TooManyToEnumerateError("nested shell re-parsing exceeded its byte budget")
    remaining_bytes[0] -= min(len(text), remaining_bytes[0])
    yield from _iter_normalised_shell_words(
        text, max_words=max_words, depth=depth + 1, remaining_bytes=remaining_bytes
    )


def _iter_normalised_shell_words(
    command: str,
    *,
    max_words: int,
    depth: int,
    remaining_bytes: list[int],
) -> Iterator[str]:
    """One linear word-by-word state machine (Plan 00466 review 6): every
    trigger below shares the same mutable per-call state (which word is
    pending what), so the sections stay numbered comments in one function
    rather than several small ones that would each need the same state
    threaded through them.
    """
    count = 0
    i = 0
    n = len(command)
    # Review 7 follow-up: quoted-delimiter heredoc bodies are inert data,
    # not command text -- skipped entirely from word decoding/counting
    # (see `_heredoc_body_skip_ranges`'s docstring). Sorted by
    # construction (`finditer` runs left to right), so a single advancing
    # pointer suffices.
    heredoc_skip_ranges = _heredoc_body_skip_ranges(command)
    heredoc_skip_index = 0

    # `<interpreter> [options...] -c <code>` option walk (also entered for
    # the `su`/`script`/`flock` wrapper shapes below).
    scanning_interpreter_options = False
    scanning_tolerant = False  # flock: a positional word does not end the walk
    awaiting_dash_c_argument = False
    awaiting_option_value = False
    # Which walk `awaiting_option_value` resumes into once its value word is
    # consumed -- `"interpreter_options"` (the initial walk, looking for
    # `-c`) or `"dash_c"` (already past `-c`, still skipping its own flags
    # before the real code word).
    option_value_resume = "interpreter_options"
    # A bare interpreter's (no `-c` found) here-string may sit several
    # words later, past intervening redirects (review 7 MAJOR-3).
    awaiting_bare_interpreter_herestring = False
    # A wrapper (`sudo`/`env`/`timeout`/...) invoked DIRECTLY, not through
    # a pipe -- review 7 MAJOR-3: `env -S '...'` and friends were
    # previously invisible outside the pipe-stage-resolution machinery.
    scanning_direct_wrapper: str | None = None
    direct_wrapper_awaiting_value = False
    direct_wrapper_value_is_code = False  # `env -S STRING` -- STRING is code
    direct_wrapper_positionals_remaining = 0

    # `eval`/a process substitution's content/`echo|printf ... | <shell>`
    # word-joining.
    collecting_words: list[str] | None = None
    # "eval" | "procsub" | "pipe_echo" | "output_procsub" (review 7 MAJOR-3)
    collecting_purpose: str | None = None
    collecting_head: str | None = None  # the trigger word, for echo/printf decode

    # `echo|printf '...' | <shell>` -- content captured, looking for the
    # pipeline stage that actually consumes it.
    pipe_content: str | None = None
    pipe_stage_awaiting_head = False
    pipe_stage_passthrough = False  # inside a `tee` stage; content survives it
    # `echo '...' > >(shell)` (review 7 MAJOR-3) -- an OUTPUT process
    # substitution reads what was just redirected INTO it, the same
    # content a `|` would have piped to a plain shell.
    pipe_content_awaiting_output_procsub = False
    pending_output_procsub_content: str | None = None
    # Review 7 MAJOR-3: walking a pipe-wrapper's OWN options/positionals
    # (`sudo -u root bash`, `timeout 5 bash`) before its eventual command.
    pipe_wrapper_name: str | None = None
    pipe_wrapper_awaiting_value = False
    pipe_wrapper_positionals_remaining = 0

    # `watch [options] CODE` -- CODE is implicit (no introducing flag).
    awaiting_implicit_code_word = False
    awaiting_implicit_code_value = False

    # `source`/`.` immediately followed by `/dev/stdin` -- looking for a
    # trailing here-string on the NEXT word.
    awaiting_source_stdin_herestring = False

    # Single-word lookback for `source`/`.` immediately followed by `<(`.
    previous_word: str | None = None
    # Non-whitespace operator characters skipped since the last WORD was
    # yielded (e.g. "<<<", "<(", "|") -- whitespace itself is dropped, only
    # genuine shell operators are tracked, so a plain space between words
    # never masquerades as one of these triggers.
    last_operators = ""

    while i < n:
        while (
            heredoc_skip_index < len(heredoc_skip_ranges)
            and i >= heredoc_skip_ranges[heredoc_skip_index][1]
        ):
            heredoc_skip_index += 1
        if (
            heredoc_skip_index < len(heredoc_skip_ranges)
            and heredoc_skip_ranges[heredoc_skip_index][0] <= i
        ):
            i = heredoc_skip_ranges[heredoc_skip_index][1]
            continue
        char = command[i]
        if char in _WORD_SEPARATOR_CHARS:
            if char not in " \t\n":
                last_operators += char
            i += 1
            continue
        if count >= max_words:
            # Review 7 MAJOR-1: fail CLOSED past the word cap, the same
            # direction `iter_brace_words` raises -- a caller that saw a
            # quiet `return` here and treated exhaustion as "no more words"
            # would allow a mention placed only past the cap, exactly the
            # fail-open the module's own docstring says every bound here
            # must not reintroduce.
            raise TooManyToEnumerateError(
                f"more than {max_words} normalised shell words in a single command"
            )

        this_word_operators = last_operators
        last_operators = ""
        nested_substitutions: list[str] = []
        decoded, end = _decode_span(
            command, i, _WORD_SEPARATOR_CHARS, substitutions=nested_substitutions
        )
        count += 1
        yield decoded
        # Review 7 MAJOR-2: every `$(...)`/backtick body this word's decode
        # just collapsed to a bare `*` is a genuine nested COMMAND -- judged
        # by its OWN text the same way `eval`'s/a process substitution's
        # content already is, not left unexamined behind the `*`.
        for nested_body in nested_substitutions:
            yield from _recurse_into_nested_command(
                nested_body, max_words=max_words, depth=depth, remaining_bytes=remaining_bytes
            )
        # Peek PAST any pure whitespace (not other operators) to find the
        # real next boundary -- a plain space right after this word does
        # NOT mean "nothing follows"; `echo a | bash` must see the `|`, not
        # stop at the space directly after `a`.
        peek = end
        while peek < n and command[peek] in " \t\n":
            peek += 1
        stop_char = command[peek] if peek < n else None
        is_terminator_next = stop_char is None or stop_char in _COMMAND_TERMINATOR_CHARS
        i = end

        # 0a. A tolerant (flock-style) option walk must not run past a
        #     genuine command terminator -- unlike a real interpreter's
        #     STRICT walk, it does not stop on the first ordinary word, so
        #     this is the only thing that ends it short of finding `-c`.
        if scanning_interpreter_options and scanning_tolerant and any(
            ch in _COMMAND_TERMINATOR_CHARS for ch in this_word_operators
        ):
            scanning_interpreter_options = False
            scanning_tolerant = False

        # 0b. A `tee`-passthrough stage: once it ends, does it still hand
        #     captured pipe content on to a FURTHER stage? This can only
        #     set up the NEXT word to be a stage head -- captured BEFORE
        #     updating, so 0c below (which resolves THIS word) never
        #     mistakes tee's own trailing argument for the stage head that
        #     update was arming.
        entering_pipe_stage_awaiting_head = pipe_stage_awaiting_head
        if pipe_stage_passthrough and is_terminator_next:
            pipe_stage_passthrough = False
            pipe_stage_awaiting_head = stop_char == _PIPE_OPERATOR
            if not pipe_stage_awaiting_head:
                pipe_content = None

        # 0c. Resolve the head of a pipeline stage pending content is
        #     waiting on: a wrapper (keep looking, walking ITS OWN options
        #     and positionals -- review 7 MAJOR-3), a shell (recurse), a
        #     `tee` passthrough (keep content alive), or neither (drop).
        if entering_pipe_stage_awaiting_head:
            pipe_stage_awaiting_head = False
            if pipe_wrapper_awaiting_value:
                # This word is the VALUE of the previous wrapper flag
                # (`sudo -u root …` -- `root` belongs to `-u`), not itself
                # a candidate command.
                pipe_wrapper_awaiting_value = False
                pipe_stage_awaiting_head = True
                previous_word = decoded
                continue
            if pipe_wrapper_name is not None:
                kind = _classify_wrapper_option_word(pipe_wrapper_name, decoded)
                if kind == "value":
                    pipe_wrapper_awaiting_value = True
                    pipe_stage_awaiting_head = True
                    previous_word = decoded
                    continue
                if kind == "skip":
                    pipe_stage_awaiting_head = True
                    previous_word = decoded
                    continue
                # kind == "command": either a mandatory positional
                # (`timeout 5 …` -- `5` is the DURATION, not the command
                # yet) or the wrapper's real command word.
                if pipe_wrapper_positionals_remaining > 0:
                    pipe_wrapper_positionals_remaining -= 1
                    pipe_stage_awaiting_head = True
                    previous_word = decoded
                    continue
                pipe_wrapper_name = None
            basename = _interpreter_basename(decoded)
            if basename in _PIPE_WRAPPER_BASENAMES:
                pipe_wrapper_name = basename
                pipe_wrapper_positionals_remaining = _WRAPPER_POSITIONAL_COUNT.get(basename, 0)
                pipe_stage_awaiting_head = True
            elif _is_shell_interpreter(basename):
                content = pipe_content
                pipe_content = None
                yield from _recurse_into_nested_command(
                    content or "",
                    max_words=max_words,
                    depth=depth,
                    remaining_bytes=remaining_bytes,
                )
                # This word is ALSO an interpreter in its own right -- let
                # its own flags/`-c` be walked normally, e.g. `echo … |
                # bash -c '…'`.
                scanning_interpreter_options = True
                scanning_tolerant = False
            elif basename in _PIPE_PASSTHROUGH_BASENAMES:
                pipe_stage_passthrough = True
                # Review 7 MAJOR-3 (`| cat | bash`, no trailing argument):
                # 0b only ends a passthrough stage on a LATER word (a
                # trailing argument such as `tee`'s file), because it runs
                # BEFORE 0c in iteration order and so cannot see a state
                # 0c has not set yet THIS iteration. A passthrough word
                # with NO trailing argument -- immediately followed by
                # its own `|` -- must resolve HERE, in the same
                # iteration, or the content is lost one word too early.
                if is_terminator_next:
                    pipe_stage_passthrough = False
                    pipe_stage_awaiting_head = stop_char == _PIPE_OPERATOR
                    if not pipe_stage_awaiting_head:
                        pipe_content = None
            else:
                pipe_content = None
            previous_word = decoded
            continue

        # 0d. `watch [options] CODE` -- CODE has no introducing flag.
        if awaiting_implicit_code_word:
            if awaiting_implicit_code_value:
                awaiting_implicit_code_value = False
                previous_word = decoded
                continue
            if decoded in _IMPLICIT_CODE_VALUE_FLAGS:
                awaiting_implicit_code_value = True
                previous_word = decoded
                continue
            if decoded.startswith("-"):
                previous_word = decoded
                continue
            awaiting_implicit_code_word = False
            # Review 7 MAJOR-3 (`watch -x bash -c 'code'`): when the
            # implicit COMMAND is itself an interpreter, hand off to the
            # normal interpreter option walk so ITS OWN `-c ARGUMENT` is
            # found -- recursing into just this one word (`bash`) would
            # lose the `-c 'code'` that follows.
            implicit_basename = _interpreter_basename(decoded)
            if _is_shell_interpreter(implicit_basename):
                scanning_interpreter_options = True
                scanning_tolerant = False
            else:
                yield from _recurse_into_nested_command(
                    decoded, max_words=max_words, depth=depth, remaining_bytes=remaining_bytes
                )
            previous_word = decoded
            continue

        # 1. Resolve a pending `-c` code argument. Review 7 MAJOR-3: real
        #    bash keeps parsing FLAGS after `-c` is seen -- the first
        #    NON-option word is the code, not simply the very next word --
        #    so `-c --` and `-c -x` before the real code no longer steal
        #    it. Reuses the SAME option classifier the initial interpreter
        #    walk uses, since `--`/`-x`/a value-taking flag mean the exact
        #    same thing here.
        if awaiting_dash_c_argument:
            kind = _classify_interpreter_option_word(decoded)
            if kind in ("dash_c", "value_glued", "plain"):
                previous_word = decoded
                continue
            if kind == "value_separate":
                awaiting_option_value = True
                option_value_resume = "dash_c"
                previous_word = decoded
                continue
            # "non_option": this word IS the code.
            awaiting_dash_c_argument = False
            scanning_interpreter_options = False
            scanning_tolerant = False
            yield from _recurse_into_nested_command(
                decoded, max_words=max_words, depth=depth, remaining_bytes=remaining_bytes
            )
            previous_word = decoded
            continue

        # 2. Resolve a pending plain option VALUE (not code) -- resume
        #    walking for `-c` afterward, in whichever MODE was pending
        #    when the value-taking flag was seen.
        if awaiting_option_value:
            awaiting_option_value = False
            if option_value_resume == "dash_c":
                awaiting_dash_c_argument = True
            else:
                scanning_interpreter_options = True
            previous_word = decoded
            continue

        # 2b. Walking a DIRECT (non-piped) wrapper's own options/
        #     positionals -- review 7 MAJOR-3 (`env -S '...'`,
        #     `sudo -u root bash -c '...'`, `timeout 5 bash -c '...'`).
        if direct_wrapper_awaiting_value:
            direct_wrapper_awaiting_value = False
            if direct_wrapper_value_is_code:
                direct_wrapper_value_is_code = False
                scanning_direct_wrapper = None
                yield from _recurse_into_nested_command(
                    decoded, max_words=max_words, depth=depth, remaining_bytes=remaining_bytes
                )
            previous_word = decoded
            continue
        if scanning_direct_wrapper is not None:
            wrapper = scanning_direct_wrapper
            kind = _classify_wrapper_option_word(wrapper, decoded)
            if kind == "value":
                direct_wrapper_awaiting_value = True
                direct_wrapper_value_is_code = wrapper == "env" and decoded in (
                    "-S",
                    "--split-string",
                )
                previous_word = decoded
                continue
            if kind == "skip":
                previous_word = decoded
                continue
            # kind == "command": a mandatory positional (`timeout 5 …`) or
            # the wrapper's real command word.
            if direct_wrapper_positionals_remaining > 0:
                direct_wrapper_positionals_remaining -= 1
                previous_word = decoded
                continue
            scanning_direct_wrapper = None
            wrapped_basename = _interpreter_basename(decoded)
            if wrapped_basename in _PIPE_WRAPPER_BASENAMES:
                # A further wrapper (`sudo env bash -c '…'`) -- keep going.
                scanning_direct_wrapper = wrapped_basename
                direct_wrapper_positionals_remaining = _WRAPPER_POSITIONAL_COUNT.get(
                    wrapped_basename, 0
                )
            elif _is_shell_interpreter(wrapped_basename):
                scanning_interpreter_options = True
                scanning_tolerant = False
            elif wrapped_basename == _EVAL_COMMAND_NAME:
                collecting_words = []
                collecting_purpose = "eval"
                collecting_head = None
            # else: an ordinary wrapped command (`sudo ls`) -- nothing
            # further to recurse into; `decoded` was already yielded as a
            # plain word above.
            previous_word = decoded
            continue

        # 3. Currently walking an interpreter's (or code-flag wrapper's)
        #    option words.
        if scanning_interpreter_options:
            kind = _classify_interpreter_option_word(decoded)
            if kind == "dash_c":
                awaiting_dash_c_argument = True
                previous_word = decoded
                continue
            if kind == "dash_c_glued_command":
                scanning_interpreter_options = False
                scanning_tolerant = False
                yield from _recurse_into_nested_command(
                    decoded.split("=", 1)[1],
                    max_words=max_words,
                    depth=depth,
                    remaining_bytes=remaining_bytes,
                )
                previous_word = decoded
                continue
            if kind == "value_glued":
                previous_word = decoded
                continue
            if kind == "value_separate":
                awaiting_option_value = True
                option_value_resume = "interpreter_options"
                scanning_interpreter_options = False
                previous_word = decoded
                continue
            if kind == "plain":
                previous_word = decoded
                continue
            # "non_option": for a TOLERANT wrapper (flock), a positional
            # word does not end the walk -- keep looking for `-c`.
            if scanning_tolerant:
                previous_word = decoded
                continue
            # For everything else, the option walk concluded with no `-c`
            # found; `decoded` is the first non-option word. A here-string
            # may not be on THIS word -- an intervening redirect
            # (`bash 2>/dev/null <<< '...'`) sits between the interpreter
            # and its here-string as further ordinary words -- so the wait
            # persists (review 7 MAJOR-3) via `awaiting_bare_interpreter_
            # herestring` below, rather than being a one-shot check here.
            scanning_interpreter_options = False
            if this_word_operators.endswith(_HERE_STRING_OPERATOR):
                yield from _recurse_into_nested_command(
                    decoded, max_words=max_words, depth=depth, remaining_bytes=remaining_bytes
                )
                previous_word = decoded
                continue
            awaiting_bare_interpreter_herestring = True
            # Not (yet) a here-string -- fall through, `decoded` may still
            # be a fresh trigger in its own right (checked below).

        # 3b. A bare interpreter's here-string may sit several words later
        #     (past intervening redirects) -- reviewed 7 MAJOR-3. Ends on
        #     a genuine command terminator (`;`, `|`, ...), never on an
        #     ordinary redirect target word.
        if awaiting_bare_interpreter_herestring:
            if this_word_operators.endswith(_HERE_STRING_OPERATOR):
                awaiting_bare_interpreter_herestring = False
                yield from _recurse_into_nested_command(
                    decoded, max_words=max_words, depth=depth, remaining_bytes=remaining_bytes
                )
                previous_word = decoded
                continue
            if any(ch in _BARE_HERESTRING_STOP_CHARS for ch in this_word_operators):
                awaiting_bare_interpreter_herestring = False
                # Falls through -- `decoded` still checked as an ordinary
                # word/fresh trigger below.
            else:
                previous_word = decoded
                continue

        # 4. Currently collecting eval/procsub/pipe-echo argument words.
        if collecting_words is not None:
            collecting_words.append(decoded)
            if is_terminator_next:
                joined = _resolve_collected_producer_text(collecting_head, collecting_words)
                purpose = collecting_purpose
                collecting_words = None
                collecting_purpose = None
                collecting_head = None
                if purpose == "pipe_echo":
                    if stop_char == _PIPE_OPERATOR:
                        pipe_content = joined
                        pipe_stage_awaiting_head = True
                    elif stop_char == ">":
                        # Review 7 MAJOR-3: might feed an OUTPUT process
                        # substitution (`echo '...' > >(bash)`) -- held,
                        # not dropped, until the next word resolves it.
                        pipe_content = joined
                        pipe_content_awaiting_output_procsub = True
                    # else: not piped/redirected to anything relevant --
                    # no recursion; the words were already scanned
                    # individually above.
                elif purpose == "output_procsub":
                    # The substitution's OWN command text (e.g. `bash`,
                    # `tee file`) is judged like any other nested command,
                    # AND -- if something was just redirected into it via
                    # `>` -- so is THAT content, since a bare `bash` here
                    # has no code of its own; the code is what it reads
                    # from stdin.
                    fed_content = pending_output_procsub_content
                    pending_output_procsub_content = None
                    yield from _recurse_into_nested_command(
                        joined, max_words=max_words, depth=depth, remaining_bytes=remaining_bytes
                    )
                    if fed_content:
                        yield from _recurse_into_nested_command(
                            fed_content,
                            max_words=max_words,
                            depth=depth,
                            remaining_bytes=remaining_bytes,
                        )
                else:
                    yield from _recurse_into_nested_command(
                        joined, max_words=max_words, depth=depth, remaining_bytes=remaining_bytes
                    )
            previous_word = decoded
            continue

        # 5. `source`/`.` immediately followed by a stdin alias -- looking
        #    for a trailing here-string on THIS word. `/dev/fd/0` and
        #    `/proc/self/fd/0` (review 7 MAJOR-3) are the same stdin-alias
        #    family as `/dev/stdin`.
        if previous_word in _SOURCE_COMMAND_NAMES and decoded in (
            "/dev/stdin",
            "/dev/fd/0",
            "/proc/self/fd/0",
        ):
            awaiting_source_stdin_herestring = True
            previous_word = decoded
            continue
        if awaiting_source_stdin_herestring:
            awaiting_source_stdin_herestring = False
            if this_word_operators.endswith(_HERE_STRING_OPERATOR):
                yield from _recurse_into_nested_command(
                    decoded, max_words=max_words, depth=depth, remaining_bytes=remaining_bytes
                )
                previous_word = decoded
                continue
            # Not a here-string after all -- `decoded` still checked below.

        # 5b. `cat <<< '...' | <shell>` (review 7 MAJOR-3) -- a passthrough
        #     command (`cat`/`tee`) fed by a here-string, as the FIRST
        #     stage of a pipeline, forwards that content exactly like a
        #     literal `echo`/`printf` producer would.
        if (
            previous_word is not None
            and _interpreter_basename(previous_word) in _PIPE_PASSTHROUGH_BASENAMES
            and this_word_operators.endswith(_HERE_STRING_OPERATOR)
        ):
            pipe_content = decoded
            if stop_char == _PIPE_OPERATOR:
                pipe_stage_awaiting_head = True
            elif stop_char == ">":
                pipe_content_awaiting_output_procsub = True
            previous_word = decoded
            continue

        # 6. A process substitution `<(...)` (input) or `>(...)` (output,
        #    review 7 MAJOR-3) ANYWHERE -- its own command text is judged
        #    like any other nested command (review 6 MAJOR-1's
        #    `bash <(echo …)`, and MAJOR-2's false-positive fix: a
        #    non-literal producer such as `kubectl completion bash` is no
        #    longer failed closed, just scanned the same way `eval` is).
        #    Matched by SUFFIX, not exact equality (review 7 MAJOR-3): an
        #    intervening redirect (`< <(...)`) accumulates as `"<<("`,
        #    which a bare `==` comparison never equals `"<("`.
        if this_word_operators.endswith(_PROCESS_SUBSTITUTION_OPERATOR):
            collecting_words = []
            collecting_purpose = "procsub"
            collecting_head = decoded
            previous_word = decoded
            continue
        if this_word_operators.endswith(_OUTPUT_PROCESS_SUBSTITUTION_OPERATOR):
            collecting_words = []
            collecting_purpose = "output_procsub"
            collecting_head = decoded
            pending_output_procsub_content = (
                pipe_content if pipe_content_awaiting_output_procsub else None
            )
            pipe_content_awaiting_output_procsub = False
            pipe_content = None
            previous_word = decoded
            continue

        # 7. Fresh triggers.
        basename = _interpreter_basename(decoded)
        if _is_shell_interpreter(basename):
            scanning_interpreter_options = True
            scanning_tolerant = False
        elif basename in _TOLERANT_DASH_C_WRAPPER_BASENAMES:
            scanning_interpreter_options = True
            scanning_tolerant = True
        elif basename in _IMPLICIT_CODE_WRAPPER_BASENAMES:
            awaiting_implicit_code_word = True
        elif decoded == _EVAL_COMMAND_NAME:
            collecting_words = []
            collecting_purpose = "eval"
            collecting_head = None
        elif decoded in _LITERAL_PRODUCER_COMMANDS:
            collecting_words = []
            collecting_purpose = "pipe_echo"
            collecting_head = decoded
        elif basename in _PIPE_WRAPPER_BASENAMES:
            # Review 7 MAJOR-3: a wrapper invoked DIRECTLY (not through a
            # pipe) -- `sudo -u root bash -c '…'`, `env -S '…'`,
            # `timeout 5 bash -c '…'`.
            scanning_direct_wrapper = basename
            direct_wrapper_positionals_remaining = _WRAPPER_POSITIONAL_COUNT.get(basename, 0)

        previous_word = decoded

    # Review 7 MAJOR-3: a pending eval/procsub/pipe-echo collection with NO
    # further word to trigger its `is_terminator_next` resolution --
    # end-of-command IS a terminator too. Without this, a bare producer
    # with nothing following it inside the SAME command (`>(bash)` with no
    # trailing args, `eval` as literally the last word) is silently
    # abandoned mid-collection and never re-parsed at all.
    if collecting_words is not None:
        joined = _resolve_collected_producer_text(collecting_head, collecting_words)
        if collecting_purpose == "output_procsub":
            yield from _recurse_into_nested_command(
                joined, max_words=max_words, depth=depth, remaining_bytes=remaining_bytes
            )
            if pending_output_procsub_content:
                yield from _recurse_into_nested_command(
                    pending_output_procsub_content,
                    max_words=max_words,
                    depth=depth,
                    remaining_bytes=remaining_bytes,
                )
        elif collecting_purpose != "pipe_echo":
            # A `pipe_echo` collection ending at end-of-string was never
            # piped/redirected to anything -- its words were already
            # scanned individually, matching the mid-command behaviour.
            yield from _recurse_into_nested_command(
                joined, max_words=max_words, depth=depth, remaining_bytes=remaining_bytes
            )


# ── Bounded recursive glob walk ──────────────────────────────────────────

#: Directory names never worth descending into for a secret-mention style
#: scan: version control internals and the classic huge/generated trees. A
#: real protected file living INSIDE one of these is an accepted residual
#: (the same trade-off `daemon.exclude_paths` makes project-wide) -- the
#: alternative is walking gigabytes of vendored/generated content on a
#: PreToolUse hot path.
_PRUNED_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".cache",
    }
)

#: Filesystem entries (files AND directories) visited before
#: :func:`bounded_recursive_glob` gives up -- bounds the WALK itself, not
#: just how many matches it returns (M-1, Plan 00466 review 3:
#: `Path.glob("**/…")` yields nothing for a pattern whose final component
#: matches nothing, so a cap on YIELDED matches never trips and the walk
#: runs to completion however large the tree is).
DEFAULT_MAX_GLOB_ENTRIES_VISITED: Final[int] = 2000

_RECURSIVE_MARKER: Final[str] = "**"


def bounded_recursive_glob(
    base: Path,
    pattern: str,
    *,
    max_entries_visited: int = DEFAULT_MAX_GLOB_ENTRIES_VISITED,
    deadline: float | None = None,
) -> Iterator[Path]:
    """Lazily yield paths under ``base`` matching ``pattern`` (which may
    contain a recursive ``**`` component), bounded by entries VISITED.

    A pattern rooted at the filesystem root (``base`` is itself an anchor,
    e.g. ``Path("/")``) is refused outright, without attempting to walk at
    all, whenever it carries a recursive ``**`` component OR two or more
    wildcarded path segments (``/*/*/*/…``) -- bounding entries visited
    there still means walking into a hostile or simply huge subtree before
    concluding, and a real client filesystem's `/` has no legitimate reason
    for a secret-mention glob to be evaluated against it (M-1 fix direction,
    Plan 00466 review 3). The multi-segment case is an own live finding, own
    RED test, not in the review report: ``/*/*/*/*/*/*/*.se?ret-zq9x`` (one
    of review 3's own probe shapes, alongside its two ``**``-marked ones)
    carries no literal ``**`` at all, yet ``Path.glob`` still has to expand
    a full directory listing at EVERY one of seven root-relative levels --
    measured at 1.1s against a small container's `/`, and the multiplicative
    cost only grows with a real filesystem's breadth.

    For every other base, this is a manual bounded walk (``os.scandir``, not
    ``Path.glob``) precisely because ``Path.glob`` only ever counts YIELDED
    matches -- it gives no signal for "examined and rejected". Each
    directory/file entry visited counts against ``max_entries_visited``
    REGARDLESS of whether it matches, so a wide tree with nothing matching
    the final component still trips the cap instead of running to
    completion. A small, fixed set of huge/ignored directory names
    (``.git``, ``node_modules``, ``__pycache__``, build/cache dirs) is
    pruned before descending into them.

    ``deadline`` (a ``time.monotonic()`` cutoff), when given, is checked
    once per entry visited -- covering the walk ITSELF, not merely the
    per-token loop around it, which is exactly the gap review 3 found in
    the pre-existing per-token-only deadline check.
    """
    is_root = bool(base.anchor) and str(base) == base.anchor
    if is_root:
        wildcard_segments = sum(
            1 for segment in pattern.split("/") if any(char in segment for char in "*?[")
        )
        if _RECURSIVE_MARKER in pattern or wildcard_segments >= 2:
            raise TooManyToEnumerateError(
                f"refusing to walk a broad glob rooted at the filesystem root: {base}/{pattern}"
            )
    if _RECURSIVE_MARKER not in pattern:
        # No recursive component: a single directory listing bounds the
        # cost naturally (the pre-existing, non-flagged behaviour).
        # `base.glob(pattern)` is a generator: a malformed pattern raises
        # ValueError, an unreadable directory raises OSError, both on first
        # iteration -- deliberately NOT caught here. Every current caller of
        # this function reaches it through `_expand_glob_token`'s own
        # ENOENT-narrow fail-closed wrapper around consuming this same
        # iterator (Plan 00272/00357, Plan 00466 n466-n24 review 4), so
        # catching a second time here would only duplicate that decision,
        # not add one.
        yield from base.glob(pattern)
        return

    parts = pattern.split("/")
    try:
        marker_index = parts.index(_RECURSIVE_MARKER)
    except ValueError:
        # `**` occurs as a SUBSTRING of one segment (`a**b`) rather than as
        # its own path component (`a/**/b`) -- not a recursive marker in
        # the glob-syntax sense, so the whole pattern is treated as the
        # (non-recursive) suffix with no prefix to descend through first.
        logger.debug(
            "shell_expansion: %r contains '**' but not as its own path segment; "
            "treating as non-recursive",
            pattern,
        )
        marker_index = -1
    prefix_parts = parts[:marker_index] if marker_index >= 0 else []
    suffix_pattern = "/".join(parts[marker_index + 1 :]) if marker_index >= 0 else pattern

    start_dir = base.joinpath(*prefix_parts) if prefix_parts else base
    if not start_dir.is_dir():
        return

    visited = 0
    stack: list[Path] = [start_dir]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            if exc.errno != errno.ENOENT:
                # A directory that could not be READ (permission denied, an
                # I/O error, ...) is not proof there is nothing inside it --
                # this walk cannot rule out a protected-path mention hiding
                # behind whatever raised, so it must NOT be silently treated
                # as "contributes nothing" (Plan 00466 n466-n24 review 4).
                # Propagates out of this generator to whichever caller is
                # consuming it -- currently always `_expand_glob_token`,
                # itself uncaught there, reaching the SAFETY guard's own
                # fail-closed wrapper.
                raise
            # ENOENT is filesystem TRUTH: the directory was removed between
            # being found as an entry and being scanned (a race), or never
            # existed -- either way there is nothing under it to find, so
            # skipping it proves a negative rather than masking a failure.
            logger.debug("shell_expansion: %r no longer exists: %s", current, exc)
            continue
        for entry in entries:
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("bounded_recursive_glob exceeded its deadline")
            visited += 1
            if visited > max_entries_visited:
                raise TooManyToEnumerateError(
                    f"glob walk under {start_dir} exceeded {max_entries_visited} " "entries visited"
                )
            entry_path = Path(entry.path)
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError as exc:
                # A stat race (the entry was removed between scandir and
                # this check) means there is nothing left to descend into
                # -- treated as a file, not a directory, so it is still
                # tried against the leaf pattern below rather than dropped
                # outright.
                logger.debug("shell_expansion: could not stat %r: %s", entry_path, exc)
                is_dir = False
            if is_dir:
                if entry.name in _PRUNED_DIR_NAMES:
                    continue
                stack.append(entry_path)
            if _fnmatch_leaf(entry.name, suffix_pattern):
                yield entry_path


def _fnmatch_leaf(name: str, pattern: str) -> bool:
    """True when ``name`` matches ``pattern``'s final path component.

    A ``**``-anchored glob's remaining pattern may still contain further
    ``/`` components (rare in practice for a mention scan, but not
    impossible); only the LEAF name is meaningful for a single directory
    entry, so a multi-component suffix is reduced to its last segment.
    """
    leaf_pattern = pattern.rsplit("/", maxsplit=1)[-1]
    return fnmatch.fnmatch(name, leaf_pattern)
