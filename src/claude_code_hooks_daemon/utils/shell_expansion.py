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
    """
    count = 0
    last_end = 0
    for match in _BRACE_GROUP_RE.finditer(text):
        if match.start() < last_end:
            continue  # already inside the span just yielded
        if count >= max_words:
            return
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


def _consume_dollar(text: str, start: int) -> tuple[str, int]:
    """At ``text[start] == '$'``: ``(piece, end)``.

    ``piece`` is statically-decoded text for the one form this CAN resolve
    without running a shell (``$'...'`` ANSI-C quoting), or the single
    character ``'*'`` for every form it cannot (``$VAR``, ``${...}``,
    ``$(...)``, ``$((...))``) -- turning the word carrying it into a GLOB
    rather than silently dropping the substitution's contribution. ``end``
    is always ``> start``, so a caller advancing by it can never loop even
    on a malformed/unterminated form.
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
        return "*", _consume_balanced(text, start + 1, "(", ")")
    if nxt == "{":
        return "*", _consume_balanced(text, start + 1, "{", "}")
    match = _DOLLAR_VAR_NAME_RE.match(text, start + 1)
    if match and match.end() > start + 1:
        return "*", match.end()
    return "$", start + 1


def _decode_span(text: str, start: int, stop_chars: str) -> tuple[str, int]:
    """Quote/escape/substitution-decode ``text`` from ``start``, stopping at
    the first UNQUOTED character in ``stop_chars`` (or at the end of
    ``text`` when ``stop_chars`` is empty) -- the one shared scanner behind
    both :func:`normalise_word` (a single already-isolated word, never
    stops early) and :func:`iter_normalised_shell_words` (a whole command,
    splitting on unquoted whitespace/operators).
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
                    piece, end = _consume_dollar(text, i)
                    out.append(piece)
                    i = end
                    continue
                if text[i] == "`":
                    j = text.find("`", i + 1)
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
            piece, end = _consume_dollar(text, i)
            out.append(piece)
            i = end
            continue
        if ch == "`":
            j = text.find("`", i + 1)
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
    """
    count = 0
    i = 0
    n = len(command)
    while i < n:
        if command[i] in _WORD_SEPARATOR_CHARS:
            i += 1
            continue
        if count >= max_words:
            return
        decoded, end = _decode_span(command, i, _WORD_SEPARATOR_CHARS)
        count += 1
        yield decoded
        i = end


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
