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

import ast
import bisect
import codecs
import errno
import fnmatch
import io
import itertools
import logging
import os
import re
import stat
import time
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, NamedTuple

from claude_code_hooks_daemon.utils.heredoc_operators import (
    Heredoc,
    scan_heredocs,
    substitution_end,
)
from claude_code_hooks_daemon.utils.shell_segmentation import (
    resolve_shell_word,
    segment_command_chain,
    segment_command_word,
)

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

    ``limit`` is the cap that was exceeded, when it is a count of examined
    paths, so a guard can tell the user what ran out (ledger 00474 N348).
    ``tree_walk`` says the cap counted entries of a recursive search's tree
    rather than the paths one glob expands to.
    """

    def __init__(
        self, message: str = "", *, limit: int | None = None, tree_walk: bool = False
    ) -> None:
        super().__init__(message)
        self.limit = limit
        self.tree_walk = tree_walk


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

    Every word is read a second way too, as bash reads it (Plan 00466 N107,
    N115): a quoted or escaped brace or comma is not brace syntax, so
    ``.p-{"}",q}`` spells ``.p-q``, and a ``}`` before a group's first
    comma is text, so ``.p-{},q}`` does too. The quote-blind reading above
    pairs ``{"}`` and ``{}`` instead and never reaches it. Both readings are
    returned, each under the same caps: the word may be a fragment of a
    longer shell word whose quoting began before it, and the quote-blind
    reading is the one every earlier caller relied on.
    A substitution that cannot be placed with certainty raises
    :class:`UnresolvableBraceQuotingError` (:func:`_substitution_end`) when
    a group could be at stake (:func:`_may_hold_a_group`).
    """
    spellings = _capped(
        _raw_brace_expansions(word, depth=0, max_depth=max_depth), word, max_spellings
    )
    try:
        braces = _BashBraces(word, max_depth=max_depth)
        quote_aware = _capped(
            braces.expansions(0, len(word), depth=0, region=None), word, max_spellings
        )
    except UnresolvableBraceQuotingError:
        if _may_hold_a_group(word, 0):
            raise
        return spellings
    seen = set(spellings)
    for spelling in quote_aware:
        if spelling not in seen:
            seen.add(spelling)
            spellings.append(spelling)
    return spellings


def _capped(expansions: Iterator[str], word: str, max_spellings: int) -> list[str]:
    spellings = list(itertools.islice(expansions, max_spellings + 1))
    if len(spellings) > max_spellings:
        raise TooManyToEnumerateError(
            f"brace expansion of {word[:80]!r} exceeds {max_spellings} spellings"
        )
    return spellings


# ── Quote-aware brace syntax (Plan 00466 N107) ──────────────────────────────
#
# Bash's brace expansion skips quoted text, a backslash-escaped character,
# `${...}`, and command and process substitutions: a brace or comma inside
# any of them is text, not syntax. :data:`_BRACE_GROUP_RE` ignores quotes,
# so a group whose first alternative is a quoted `"}"` hid a brace-spelled
# path from the guard. The quote-aware expansion is bash 5.2's own
# (:class:`_BashBraces`), checked against bash by a differential test. :func:`_quoted_span_end` places the
# spans the shell word splitter (:func:`iter_shell_brace_words`) skips.


class UnresolvableBraceQuotingError(TooManyToEnumerateError):
    """A span whose extent the scanner cannot establish with certainty, so
    which braces are syntax cannot be either. A :class:`TooManyToEnumerateError`,
    so every caller already fails closed on it."""


#: Characters that can make a brace or comma text rather than syntax. A
#: word holding none of them reads the same quote-aware or not.
_QUOTING_CHARS: Final[frozenset[str]] = frozenset("'\"\\$`")

#: What ends an unquoted shell word.
_SHELL_WORD_STOP_CHARS: Final[frozenset[str]] = frozenset(" \t\n;|&<>()")

#: A `$` form whose extent is certain without further scanning: a name or
#: a special parameter.
_PLAIN_DOLLAR_RE: Final[re.Pattern[str]] = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|[0-9@*#?$!-])")

#: The opening of a parameter expansion whose operator takes a word that
#: quoting reads as it reads any word: `${name:-`, `=`, `+` or `?`.
_DEFAULT_WORD_OPENER_RE: Final[re.Pattern[str]] = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*:?[-=+?]")

#: A `case` word inside a substitution: where it is the reserved word, its
#: patterns' bare `)` would end the substitution early for a paren count.
_CASE_WORD_RE: Final[re.Pattern[str]] = re.compile(r"case(?=\s)")

#: The `$` forms a double-quoted span or a parameter expansion nests.
_NESTED_DOLLAR_OPENERS: Final[tuple[str, ...]] = ("${", "$(")


def _quoted_span_end(text: str, i: int, substitutions: list[str] | None = None) -> int | None:
    """If ``text[i]`` opens a span bash's brace expansion skips, the index
    just past it; otherwise ``None``.

    The spans: a backslash and the character it escapes, ``'...'``,
    ``"..."``, ``$'...'``, ``$"..."``, ``${...}``, a backtick substitution
    and ``$(...)``, ``<(...)``, ``>(...)``. An unterminated span runs to the
    end of ``text``, as its quoting does for bash. Every command
    substitution's body is appended to ``substitutions`` when given.
    Raises :class:`UnresolvableBraceQuotingError` where the extent depends
    on syntax this does not model (:func:`_parameter_end`,
    :func:`_substitution_end`).
    """
    n = len(text)
    ch = text[i]
    nxt = text[i + 1] if i + 1 < n else ""
    if ch == "\\":
        return min(i + 2, n)
    if ch == "'":
        close = text.find("'", i + 1)
        return n if close == -1 else close + 1
    if ch == '"':
        return _double_quote_end(text, i + 1, substitutions)
    if ch == "`":
        close, body = _close_backtick(text, i + 1)
        if substitutions is not None:
            substitutions.append(body)
        return n if close == -1 else close + 1
    if ch == "$" and nxt == "'":
        j = i + 2
        while j < n and text[j] != "'":
            j += 2 if text[j] == "\\" else 1
        return min(j + 1, n)
    if ch == "$" and nxt == '"':
        return _double_quote_end(text, i + 2, substitutions)
    if ch == "$" and nxt == "{":
        return _parameter_end(text, i, substitutions)
    if ch in "$<>" and nxt == "(":
        return _substitution_end(text, i + 1, substitutions)
    return None


def _double_quote_end(text: str, start: int, substitutions: list[str] | None) -> int:
    """Just past the ``"`` closing a double-quoted span whose body starts at
    ``start``: a backslash escapes the next character, and a substitution
    inside is skipped whole."""
    n = len(text)
    j = start
    while j < n:
        ch = text[j]
        if ch == '"':
            return j + 1
        if ch == "\\":
            j += 2
            continue
        if text.startswith("${", j):
            j = _parameter_end(text, j, substitutions, in_double=True)
            continue
        if ch == "`" or text.startswith(_NESTED_DOLLAR_OPENERS, j):
            j = _quoted_span_end(text, j, substitutions) or j + 1
            continue
        j += 1
    return n


def _parameter_end(
    text: str, start: int, substitutions: list[str] | None, *, in_double: bool = False
) -> int:
    """Just past the ``}`` closing the ``${`` at ``start``.

    Bash reads quotes, escapes and braces inside a parameter expansion by
    rules that depend on its operator (``${x:-'}'}``). A body holding any
    of them, other than a nested substitution or plain ``$name``, cannot be
    read with certainty, and neither can an unterminated one. The exception
    is the word of a ``-``, ``=``, ``+`` or ``?`` operator after a plain
    name (:data:`_DEFAULT_WORD_OPENER_RE`), read by :func:`_default_word_end`;
    ``in_double`` says the expansion sits inside double quotes."""
    if _DEFAULT_WORD_OPENER_RE.match(text, start) is not None:
        return _default_word_end(text, start, substitutions, in_double)
    n = len(text)
    j = start + 2
    while j < n:
        ch = text[j]
        if ch == "}":
            return j + 1
        if text.startswith(_NESTED_DOLLAR_OPENERS, j):
            j = _quoted_span_end(text, j, substitutions) or j + 1
            continue
        plain = _PLAIN_DOLLAR_RE.match(text, j)
        if plain is not None:
            j = plain.end()
            continue
        if ch in "{'\"\\`":
            raise UnresolvableBraceQuotingError(
                f"quoting inside ${{...}} in {text[start : start + 80]!r} cannot be resolved"
            )
        j += 1
    raise UnresolvableBraceQuotingError(f"unterminated ${{...}} in {text[start : start + 80]!r}")


def _default_word_end(
    text: str, start: int, substitutions: list[str] | None, in_double: bool
) -> int:
    """Just past the ``}`` closing ``${name<op>word}`` at ``start``. In the
    word a backslash escapes, ``'...'`` quotes (literal inside double
    quotes), ``"..."`` quotes, and substitutions and expansions nest; a
    bare ``{`` or an unterminated quote is not read with certainty."""
    n = len(text)
    opener = _DEFAULT_WORD_OPENER_RE.match(text, start)
    if opener is None:
        raise ValueError(f"not a parameter expansion with a word: {text[start : start + 80]!r}")
    j = opener.end()
    while j < n:
        ch = text[j]
        if ch == "}":
            return j + 1
        if ch == "\\":
            j += 2
            continue
        if ch == "'" and not in_double:
            close = text.find("'", j + 1)
            if close == -1:
                break
            j = close + 1
            continue
        if ch == '"':
            j = _double_quote_end(text, j + 1, substitutions)
            continue
        if text.startswith("${", j):
            j = _parameter_end(text, j, substitutions, in_double=in_double)
            continue
        if ch == "`" or text.startswith("$(", j):
            j = _quoted_span_end(text, j, substitutions) or j + 1
            continue
        if ch == "{":
            break
        j += 1
    raise UnresolvableBraceQuotingError(
        f"quoting inside ${{...}} in {text[start : start + 80]!r} cannot be resolved"
    )


def _substitution_end(text: str, open_paren: int, substitutions: list[str] | None) -> int:
    """Just past the ``)`` closing the command or process substitution
    whose ``(`` is at ``open_paren``, its body read as a command: quotes and
    nested substitutions skipped whole, nested parentheses counted, and a
    comment running to the end of its line. A body holding a ``case`` word
    or a heredoc, whose ``)`` and lines a paren count cannot place, is read
    by the shared scanner, and is not read with certainty where that stops.
    An unterminated body runs to the end of ``text``.
    Only this body is appended to ``substitutions``: the ones nested in it
    are found when it is read in turn.
    """
    n = len(text)
    depth = 1
    j = open_paren + 1
    word_start = True
    while j < n:
        ch = text[j]
        if word_start and ch == "#":
            newline = text.find("\n", j)
            j = n if newline == -1 else newline
            continue
        if text.startswith(_HERE_STRING_OPERATOR, j):
            j += len(_HERE_STRING_OPERATOR)
            word_start = True
            continue
        if text.startswith("<<", j) or (word_start and _CASE_WORD_RE.match(text, j)):
            # The shared scanner reads heredoc bodies by bash's grammar
            # (Plan 00466 N101 round 10, check 2), and knows where bash reads
            # `case` as the reserved word (round 12, review 11 MAJOR 2).
            close = substitution_end(text, open_paren)
            if close is None:
                raise UnresolvableBraceQuotingError(
                    f"a heredoc or case command inside {text[open_paren - 1 : open_paren + 80]!r}"
                )
            if substitutions is not None:
                substitutions.append(text[open_paren + 1 : close - 1])
            return close
        end = _quoted_span_end(text, j)
        if end is not None:
            j = end
            word_start = False
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                if substitutions is not None:
                    substitutions.append(text[open_paren + 1 : j])
                return j + 1
        word_start = ch in _SHELL_WORD_STOP_CHARS
        j += 1
    if substitutions is not None:
        substitutions.append(text[open_paren + 1 :])
    return n


#: Brace-syntax characters one word's bash-aware expansion may visit before
#: it gives up. Bash retries every `{` against the rest of the word, so a
#: word of many unmatched braces costs the square of their number; past
#: this it fails closed, like every other cap here.
_BRACE_SCAN_BUDGET: Final[int] = 250_000


class _BashBraces:
    """Bash 5.2's brace expansion (``braces.c``: ``brace_expand``,
    ``expand_amble``, ``brace_gobbler``) over one word, lazily.

    Bash scans a word left to right for the first ``{`` that has a matching
    ``}``, expands it, and expands the text after it on its own; each
    alternative is expanded in turn. Every text it scans is a slice of the
    word that starts and ends outside quoting, so the characters it acts on
    -- unquoted ``{``, ``}``, ``,``, ``..`` and ``${`` -- are found once,
    for the whole word, and each scan visits only those. The parser has
    already turned ``$'...'`` into a quoted string and ``$"..."`` into
    ``"..."``, so both are quoted here. A substitution whose extent cannot
    be established raises :class:`UnresolvableBraceQuotingError`
    (:func:`_substitution_end`)."""

    def __init__(self, word: str, *, max_depth: int) -> None:
        self.word = word
        self.max_depth = max_depth
        self.budget = _BRACE_SCAN_BUDGET
        self.events = self._syntax_events()
        self.positions = [position for position, _kind in self.events]
        self.closers = [position for position, kind in self.events if kind == "}"]
        self.separators = [position for position, kind in self.events if kind in ",."]

    def _syntax_events(self) -> list[tuple[int, str]]:
        """``(index, kind)`` of every character bash's scanner acts on:
        ``{``, ``}``, ``,``, ``.`` for a ``..``, and ``$`` for a ``${``
        outside quotes, which opens a level as ``{`` does."""
        text = self.word
        n = len(text)
        events: list[tuple[int, str]] = []
        quoted = ""
        i = 0
        while i < n:
            ch = text[i]
            nxt = text[i + 1] if i + 1 < n else ""
            if ch == "\\" and quoted in ("", '"', "`"):
                i += 2
            elif ch == "$" and nxt == "{" and quoted != "'":
                if not quoted:
                    events.append((i, "$"))
                i += 2
            elif quoted:
                if quoted == '"' and ch == "$" and nxt == "(":
                    i = _substitution_end(text, i + 1, None)
                    continue
                if ch == quoted:
                    quoted = ""
                i += 1
            elif ch == "$" and nxt == "'":
                i = _quoted_span_end(text, i) or i + 1
            elif ch in "\"'`":
                quoted = ch
                i += 1
            elif ch in "$<>" and nxt == "(":
                i = _substitution_end(text, i + 1, None)
            else:
                if ch in "{},":
                    events.append((i, ch))
                elif text.startswith("..", i):
                    events.append((i, "."))
                i += 1
        return events

    def _gobble(self, start: int, stop: int, satisfy: str) -> int | None:
        """``brace_gobbler`` over ``word[start:stop]``: the index of the
        first ``satisfy`` it accepts, or ``None``. A ``}`` closes a group
        only after a ``,`` or a ``..`` not followed by ``}`` outside any
        inner group; before that it is text. A ``{`` with whitespace or the
        start before it and whitespace, the end or a ``}`` after it is
        text."""
        level = 0
        commas = 0 if satisfy == "}" else 1
        index = bisect.bisect_left(self.positions, start)
        while index < len(self.events) and self.events[index][0] < stop:
            self.budget -= 1
            if self.budget < 0:
                raise TooManyToEnumerateError(
                    f"brace scan of {self.word[:80]!r} exceeds its budget"
                )
            position, kind = self.events[index]
            index += 1
            if kind == satisfy and level == 0 and commas > 0:
                if not (kind == "{" and self._isolated(position, start, stop)):
                    return position
            elif kind in "{$":
                level += 1
            elif kind == "}" and level:
                level -= 1
            elif satisfy == "}" and level == 0 and kind in ",.":
                after = self.word[position + 2] if position + 2 < stop else ""
                if kind == "," or after != "}":
                    commas += 1
        return None

    def _isolated(self, position: int, start: int, stop: int) -> bool:
        before = self.word[position - 1] if position > start else ""
        after = self.word[position + 1] if position + 1 < stop else ""
        return before in ("", " ", "\t", "\n") and after in ("", " ", "\t", "\n", "}")

    def _first_group(self, start: int, stop: int) -> tuple[int, int] | None:
        """``(open, close)`` of the group ``brace_expand`` expands first in
        ``word[start:stop]``. No ``{`` can match once no ``}``, or no
        separator, is left after it."""
        while True:
            opened = self._gobble(start, stop, "{")
            if opened is None:
                return None
            for later in (self.closers, self.separators):
                following = bisect.bisect_right(later, opened)
                if following == len(later) or later[following] >= stop:
                    return None
            closed = self._gobble(opened + 1, stop, "}")
            if closed is not None:
                return opened, closed
            start = opened + 1

    def top_level_groups(self) -> Iterator[tuple[int, int]]:
        """Every group ``brace_expand`` reaches at the top level, in order."""
        start = 0
        while (group := self._first_group(start, len(self.word))) is not None:
            yield group
            start = group[1] + 1

    def expansions(
        self, start: int, stop: int, *, depth: int, region: tuple[int, int] | None
    ) -> Iterator[str]:
        """``brace_expand`` of ``word[start:stop]``. A group body with no
        comma that is not a sequence is text. Each alternative keeps its
        quotes, which :func:`normalise_word` strips from the finished
        spelling. ``region``, when given, limits expansion to the groups
        opening inside it (:func:`shell_word_spellings`)."""
        if depth > self.max_depth:
            raise TooManyToEnumerateError(
                f"brace nesting exceeds the depth cap ({self.max_depth}) in {self.word[:80]!r}"
            )
        group = self._first_group(start, stop)
        if group is None:
            yield self.word[start:stop]
            return
        opened, closed = group
        preamble = self.word[start:opened]
        literal = self.word[opened : closed + 1]
        tacks: Iterator[str]
        if region is not None and not region[0] <= opened < region[1]:
            tacks = iter([literal])
        elif self._holds_a_raw_comma(opened + 1, closed):
            tacks = self._amble(opened + 1, closed, depth=depth)
        else:
            sequence = _sequence_alternatives(self.word[opened + 1 : closed])
            if sequence is not None:
                tacks = sequence
            elif closed + 1 < stop:
                tacks = iter([literal])
            else:
                yield self.word[start:stop]
                return
        for tack in tacks:
            if closed + 1 >= stop:
                yield preamble + tack
                continue
            for rest in self.expansions(closed + 1, stop, depth=depth + 1, region=region):
                yield preamble + tack + rest

    def _amble(self, start: int, stop: int, *, depth: int) -> Iterator[str]:
        """``expand_amble``: each alternative of a group body, split at the
        commas the scanner accepts, expanded in turn."""
        while True:
            comma = self._gobble(start, stop, ",")
            end = stop if comma is None else comma
            yield from self.expansions(start, end, depth=depth + 1, region=None)
            if comma is None:
                return
            start = comma + 1

    def _holds_a_raw_comma(self, start: int, stop: int) -> bool:
        """Whether ``word[start:stop]`` holds a ``,`` no backslash escapes,
        which is what bash checks before it tries a sequence: it does not
        read quotes here."""
        i = start
        while i < stop:
            if self.word[i] == "\\":
                i += 2
            elif self.word[i] == ",":
                return True
            else:
                i += 1
        return False


def shell_word_spellings(
    word: str,
    *,
    max_spellings: int = DEFAULT_MAX_BRACE_SPELLINGS,
    max_depth: int = DEFAULT_MAX_BRACE_DEPTH,
) -> Iterator[str]:
    """Every whitespace-free token of every spelling of a word found by
    :func:`iter_shell_brace_words`, quote-removed (Plan 00466 N107).

    Such a word may hold quoted whitespace, and a token never spans
    whitespace. Whitespace outside every matched group is in every
    spelling, so the tokens on either side of it are independent: each
    piece between two such characters is expanded on its own, under the
    caps, and a piece holding no group adds nothing the other streams lack.
    A group holding quoted whitespace keeps its piece whole."""
    braces = _BashBraces(word, max_depth=max_depth)
    groups = list(braces.top_level_groups())
    covered = [False] * len(word)
    for start, end in groups:
        covered[start : end + 1] = [True] * (end + 1 - start)
    cuts = [i for i, char in enumerate(word) if char.isspace() and not covered[i]]
    for low, high in itertools.pairwise([-1, *cuts, len(word)]):
        if not any(low < start < high for start, _end in groups):
            continue
        expansions = braces.expansions(0, len(word), depth=0, region=(low + 1, high))
        for spelling in _capped(expansions, word, max_spellings):
            yield from normalise_word(spelling).split()


def iter_shell_brace_words(text: str) -> Iterator[str]:
    """Every word of ``text``, split as bash splits it, that holds a brace
    (Plan 00466 N107, N115).

    :func:`iter_brace_words` splits on every whitespace character, quoted or
    not, so a group holding quoted whitespace (``.p-{"} x",q}``) reaches the
    expander in pieces, none of which spells the path. This splitter reads
    quotes, escapes and substitutions with :func:`_quoted_span_end` and
    skips comments. A word holding no quoting character is reported too:
    bash's grouping rules differ from :func:`iter_brace_words`' quote-blind
    pairing even there (a ``}`` before the first comma is text, so
    ``.p-{},q}`` spells ``.p-q``). A here-string (``<<<``) word is an
    ordinary word, not a heredoc delimiter (Plan 00466 N116).

    Text a shell may run is read as a command in its own right, as the
    quote-blind reading always did implicitly: every command substitution's
    body; every heredoc body (``bash <<'EOF'``), whose extent its delimiter
    line fixes whatever its quoting; the substitutions of an unquoted
    heredoc body, where quotes are text; every word after quote removal,
    the code ``bash -c``, ``su -c`` or ``ssh`` receive; and ``eval``'s
    arguments after quote removal, joined by spaces. Each level strips a
    layer of quoting, and nesting is bounded by
    :data:`_MAX_NESTED_SHELL_DEPTH`.

    ANSI-C decoding is the one quote removal that makes braces the raw text
    lacks (``$'\\x7b'``), which :func:`iter_brace_words` never sees: text
    decoded from a ``$'...'`` word is read as a command whatever it holds,
    and every word of it holding a brace is reported (Plan 00466 N112).

    Its words are read by :func:`shell_word_spellings`.

    Where a span's extent cannot be resolved with certainty, the rest of
    ``text`` cannot be split with certainty either: if a group could still
    arrive (:func:`_may_hold_a_group`) this raises
    :class:`UnresolvableBraceQuotingError`, otherwise there is none left to
    miss and the scan ends.
    """
    return _shell_brace_words(text, depth=0)


def _shell_brace_words(text: str, *, depth: int) -> Iterator[str]:
    """The words of :func:`iter_shell_brace_words`."""
    if depth > _MAX_NESTED_SHELL_DEPTH:
        raise UnresolvableBraceQuotingError("shell word nesting exceeds its depth bound")
    n = len(text)
    i = 0
    # Where each heredoc starts and what closes it is the shared scanner's
    # call (Plan 00466 N101 round 10, check 2). A `<<` it did not report as
    # an operator is text, and the lines after it are read as commands.
    scanned = scan_heredocs(text).heredocs if "<<" in text else []
    operators = {heredoc.operator.start: heredoc for heredoc in scanned}
    heredocs: list[Heredoc] = []
    command_words: list[str] = []
    while i < n:
        ch = text[i]
        if ch in _COMMAND_END_CHARS and command_words:
            yield from _eval_words(command_words, depth=depth)
            command_words = []
        if ch == "\n":
            i += 1
            if heredocs:
                for pending in heredocs:
                    body = pending.body(text)
                    yield from _heredoc_body_words(body, pending.operator.quoted, depth=depth)
                i = max(i, min(heredocs[-1].closer_end + 1, n))
                heredocs = []
            continue
        if ch in " \t":
            i += 1
            continue
        if text.startswith(_HERE_STRING_OPERATOR, i):
            i += len(_HERE_STRING_OPERATOR)
            continue
        if text.startswith("<<", i):
            heredoc = operators.get(i)
            if heredoc is None:
                i += len("<<")
                continue
            heredocs.append(heredoc)
            i = heredoc.operator.end
            continue
        if ch in _SHELL_WORD_STOP_CHARS:
            i += 1
            continue
        if ch == "#":
            newline = text.find("\n", i)
            i = n if newline == -1 else newline
            continue
        substitutions: list[str] = []
        end = _checked_word_end(text, i, substitutions)
        if end is None:
            break
        word = text[i:end]
        if _holds_braces(word):
            yield word
        for body in substitutions:
            yield from _shell_brace_words(body, depth=depth + 1)
        value = word if _QUOTING_CHARS.isdisjoint(word) else normalise_word(word)
        if value != word:
            yield from _nested_command_words(value, depth=depth, decoded=_ANSI_C_OPENER in word)
        command_words.append(word)
        i = end
    if command_words:
        yield from _eval_words(command_words, depth=depth)


#: What ends a simple command for :func:`_eval_words`.
_COMMAND_END_CHARS: Final[frozenset[str]] = frozenset(";&|()\n")

#: Words that run ``eval`` on the rest of a simple command.
_EVAL_PREFIXES: Final[tuple[tuple[str, ...], ...]] = (
    ("eval",),
    ("builtin", "eval"),
    ("command", "eval"),
)


#: What opens an ANSI-C quoted span, whose decoding can make braces.
_ANSI_C_OPENER: Final[str] = "$'"


def _holds_braces(text: str) -> bool:
    return "{" in text and "}" in text


def _nested_command_words(code: str, *, depth: int, decoded: bool) -> Iterator[str]:
    """``code`` read as a command: a word's value after quote removal, when
    that removed something, or ``eval``'s joined arguments. Read when it
    still holds a brace, or whatever it holds when ANSI-C decoding
    (``decoded``) made it, since a nested ``$'...'`` in it may decode to a
    brace in turn (``$'$\\'\\\\x7b\\''``)."""
    if decoded or _holds_braces(code):
        yield from _shell_brace_words(code, depth=depth + 1)


def _eval_words(words: list[str], *, depth: int) -> Iterator[str]:
    """``eval``'s arguments after quote removal, joined by single spaces as
    ``eval`` joins them, read as a command."""
    if all(_QUOTING_CHARS.isdisjoint(word) for word in words):
        return
    values = [normalise_word(word) for word in words]
    for prefix in _EVAL_PREFIXES:
        if tuple(values[: len(prefix)]) == prefix:
            code = " ".join(values[len(prefix) :])
            decoded = any(_ANSI_C_OPENER in word for word in words[len(prefix) :])
            yield from _nested_command_words(code, depth=depth, decoded=decoded)
            return


def _checked_word_end(text: str, start: int, substitutions: list[str] | None) -> int | None:
    """The end of the unquoted shell word at ``start``; ``None`` when a span
    in it cannot be resolved and no group can arrive after it, so nothing
    is left to find. Re-raises when one can."""
    try:
        return _shell_word_end(text, start, substitutions)
    except UnresolvableBraceQuotingError as error:
        if _may_hold_a_group(text, start):
            raise
        logger.debug("brace-word scan ends: no group can follow %s", error)
    return None


#: A `{` that could open a brace group: any not opening a `${`.
_GROUP_OPENER_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\$)\{")

#: A `$'...'` span, its body (escapes undecoded) in group 1; an
#: unterminated one runs to the end.
_ANSI_C_SPAN_RE: Final[re.Pattern[str]] = re.compile(r"\$'((?:[^'\\]|\\.)*)", re.DOTALL)

#: An expansion whose value is not known statically: a parameter, or a
#: command or arithmetic substitution.
_UNKNOWN_EXPANSION_RE: Final[re.Pattern[str]] = re.compile(r"\$[({A-Za-z_0-9@*#?$!-]|`")

#: A word that hands text to a shell to read again: ``eval``, ``source``,
#: ``.``, ``su``, ``ssh``, a shell by name, or an option cluster holding
#: ``c`` (``-c``, ``-lc``).
_SHELL_READER_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![^\s;&|(`'\"])"
    r"(?:eval|source|\.|su|ssh|(?:\S*/)?(?:ba|da|z|k|mk|a)?sh|-[A-Za-z]*c[A-Za-z]*)"
    r"(?![^\s;&|)`'\"])"
)


def _may_hold_a_group(text: str, start: int) -> bool:
    """Whether a brace group could still arrive in ``text`` from ``start``
    (Plan 00466 N113): a ``{`` other than a ``${`` with a ``}`` after it; a
    ``$'...'`` whose decoded body holds a brace; or an expansion whose value
    is unknown where a word hands text to a shell to read again. Only when
    none of them can is it safe to stop scanning."""
    opener = _GROUP_OPENER_RE.search(text, start)
    if opener is not None and text.find("}", opener.end()) != -1:
        return True
    for span in _ANSI_C_SPAN_RE.finditer(text, start):
        if not {"{", "}"}.isdisjoint(_decode_ansi_c_body(span.group(1))):
            return True
    return (
        _UNKNOWN_EXPANSION_RE.search(text, start) is not None
        and _SHELL_READER_RE.search(text, start) is not None
    )


def _shell_word_end(text: str, start: int, substitutions: list[str] | None) -> int:
    n = len(text)
    j = start
    while j < n:
        end = _quoted_span_end(text, j, substitutions)
        if end is not None:
            j = end
            continue
        if text[j] in _SHELL_WORD_STOP_CHARS:
            break
        j += 1
    return j


def _heredoc_body_words(body: str, quoted: bool, *, depth: int) -> Iterator[str]:
    """Words of a heredoc body read as a command, which a shell fed the
    body runs; and, for an unquoted body, of the commands it substitutes,
    where quotes are text and a backslash and a substitution are not."""
    yield from _shell_brace_words(body, depth=depth + 1)
    if quoted:
        return
    substitutions: list[str] = []
    j = 0
    try:
        while j < len(body):
            if body[j] == "\\":
                j += 2
            elif body[j] == "`" or body.startswith(_NESTED_DOLLAR_OPENERS, j):
                j = _quoted_span_end(body, j, substitutions) or j + 1
            else:
                j += 1
    except UnresolvableBraceQuotingError:
        if _may_hold_a_group(body, j):
            raise
    for nested in substitutions:
        yield from _shell_brace_words(nested, depth=depth + 1)


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

    A word in which bash reads no brace as syntax (``'{a,b}'``, ``\\{a,b}``)
    is neither yielded nor counted (ledger 00466 N238): prose quoting
    hundreds of such words hit the cap, which is a quoted literal being
    enumerated. Where the word is a fragment of a longer shell word whose
    quoting began before it (``'x '{a,b}' y'``), the quote-aware splitter
    (:func:`iter_shell_brace_words`) reads the whole word as bash does.
    """
    count = 0
    for start, end in _brace_word_spans(text):
        word = text[start:end]
        if not _holds_brace_syntax(word):
            continue
        if count >= max_words:
            raise TooManyToEnumerateError(
                f"more than {max_words} brace-carrying words in a single command"
            )
        count += 1
        yield word


def _holds_brace_syntax(word: str) -> bool:
    """Does bash, reading ``word`` alone, expand a brace group in it? A word
    whose quoting cannot be read with certainty, or past the scan budget,
    counts as one that does."""
    try:
        braces = _BashBraces(word, max_depth=DEFAULT_MAX_BRACE_DEPTH)
        return next(braces.top_level_groups(), None) is not None
    except TooManyToEnumerateError:
        return True


def _brace_word_spans(text: str) -> Iterator[tuple[int, int]]:
    """``(start, end)`` of every word :func:`iter_brace_words` yields, in
    order and uncapped: a match inside the span just yielded is skipped
    without a second boundary scan."""
    last_end = 0
    for match in _BRACE_GROUP_RE.finditer(text):
        if match.start() < last_end:
            continue  # already inside the span just yielded
        start = match.start()
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        end = match.end()
        while end < len(text) and not text[end].isspace():
            end += 1
        last_end = end
        yield start, end


# ── What a shell actually brace-expands (Plan 00466 N101) ───────────────────
#
# Bash brace-expands only UNQUOTED shell words. A Python program handed to
# `python3` as a quoted-delimiter heredoc or a single-quoted `-c` argument
# reaches Python verbatim, so enumerating its dict literals and f-strings as
# brace "spellings" models nothing bash does -- and hits the caps above,
# failing a guard closed on a command that names no protected path.
#
# :func:`brace_expansion_view` neutralises the braces of that program text
# that are CODE -- dict and set displays, comprehensions, f-string fields --
# and reports every string literal and comment for the caller to enumerate
# on its own. Only a literal can spell a path, so a brace-spelled path in any
# literal still denies, whoever reads the program's output and however the
# call is reached. It does so only while nothing on the command line can
# turn the program back into shell text. The guard fails closed, so every
# condition must be established: anything the scanner is not sure about is
# returned unchanged, and the caller keeps enumerating it and keeps failing
# closed past the cap.

#: A command named bare (resolved through PATH) or from a system directory.
#: A relative or other absolute path (`./python3`, `/tmp/cat`) may be a
#: shell under a trusted name.
_SYSTEM_DIRECTORY_PREFIX: Final[str] = r"(?:/usr/bin/|/bin/|/usr/local/bin/)?"

#: The one interpreter whose program text is exempt. Ruby, Perl, PHP and
#: Node expand braces in their own glob APIs (`Dir.glob`, `glob`,
#: `GLOB_BRACE`, `fs.glob`), so their text stays shell text.
_PYTHON_INTERPRETER_RE: Final[re.Pattern[str]] = re.compile(
    _SYSTEM_DIRECTORY_PREFIX + r"python(?:\d+(?:\.\d+)*)?"
)

#: A command word naming its command bare or from a system directory.
_TRUSTED_COMMAND_RE: Final[re.Pattern[str]] = re.compile(
    _SYSTEM_DIRECTORY_PREFIX + r"(?P<name>[^/]+)"
)

#: Python options that take no value, and those whose value follows. Any
#: other option (`-m`, `--isolated`, a cluster holding `c`) withholds the
#: exemption rather than being guessed at.
_PYTHON_FLAG_LETTERS: Final[frozenset[str]] = frozenset("bBdEhiIOPqsSuvVx")
_PYTHON_VALUE_FLAG_LETTERS: Final[frozenset[str]] = frozenset("WX")

#: A `NAME=value` prefix word of a simple command.
_ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")

#: A redirection word: optional fd, operator, and an optional glued target.
_REDIRECT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<fd>\d*)(?P<op><<<|<<-|<<|<>|<&|<|>>|>\||>&|>|&>>|&>)(?P<target>.*)", re.DOTALL
)

#: Output targets that no later command can read back.
_HARMLESS_OUTPUT_TARGETS: Final[frozenset[str]] = frozenset({"/dev/null"})
_HARMLESS_DUP_TARGETS: Final[frozenset[str]] = frozenset({"1", "2", "-"})

#: The only commands that may run anywhere in a line holding an exempted
#: program, substitutions included (Plan 00466 N101 round 4, D-RULE MAJOR
#: 2). An ALLOWLIST: a deny-list of heads that run text as shell missed
#: `trap` and `mapfile -C`, and `bind -x`, `complete -C`, `fc`, `eval`,
#: `source`, a compound command and every unreviewed name have the same
#: shape, so any other head withdraws every exemption. Each named here runs
#: no text as shell and evaluates no arithmetic (an array subscript in
#: arithmetic runs `$(...)`):
#:
#: - `cd`, `pushd`, `popd`, `pwd`: move or print the working directory;
#: - `echo`, `true`, `false`, `:`: print or ignore their arguments;
#: - `set`: shell options, except `-x`/`xtrace`, whose trace expands PS4;
#: - `export`: plain `NAME` or `NAME=value` operands only -- no option
#:   (`-f` exports functions) and no subscript (`a[$(x)]=1`);
#: - `mkdir`, `ls`, `cat`, `grep`, `sleep`: create, list or read files;
#: - Python (:data:`_PYTHON_INTERPRETER_RE`), which can do nothing the
#:   exempted program cannot.
#:
#: Each is named bare or from a system directory. A wrapper
#: (`shell_segmentation._WRAPPER_GRAMMARS`: `sudo`, `env`, `nice`, `nohup`,
#: `timeout`, `command`) is seen through, and what it runs must be on this
#: list too; `set` and `export` are builtins no wrapper need run.
_INERT_HEADS: Final[frozenset[str]] = frozenset(
    {
        "cd",
        "pushd",
        "popd",
        "pwd",
        "echo",
        "true",
        "false",
        ":",
        "set",
        "export",
        "mkdir",
        "ls",
        "cat",
        "grep",
        "sleep",
    }
)

#: Allowlisted builtins whose operands are judged too (:data:`_INERT_HEADS`).
_SET_BUILTIN: Final[str] = "set"
_EXPORT_BUILTIN: Final[str] = "export"

#: A `set` operand that turns tracing on.
_XTRACE_OPERAND_RE: Final[re.Pattern[str]] = re.compile(r"[-+][A-Za-z]*x[A-Za-z]*|xtrace")

#: An `export` operand naming a plain variable, with or without a value.
_EXPORT_OPERAND_RE: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:=.*)?", re.DOTALL
)

#: A `${...}` body the view models: a plain parameter name. Anything else
#: (`${a[i]}`, `${!x}`, `${x:y}`) may evaluate a value as arithmetic, whose
#: array subscripts run `$(...)`.
_PLAIN_PARAMETER_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*#?$!-]")

#: Characters that start an expansion in an unquoted heredoc body.
_EXPANDING_CHARS: Final[frozenset[str]] = frozenset("$`")

#: Heads that may share a line with a program whose output is redirected
#: into a file: none of them can execute that file.
_INERT_SIBLING_HEADS: Final[frozenset[str]] = frozenset(
    {"set", "cd", "pushd", "popd", "echo", "pwd", "true", "false", ":", "mkdir"}
)

#: Separators after which a program's output flows on to another command.
_PIPE_TERMINATORS: Final[frozenset[str]] = frozenset({"|", "|&"})

#: What a neutralised brace becomes: same length, so every index into the
#: view is an index into the command, and inert to both the brace-group
#: regex and ``fnmatch``.
_NEUTRAL_BRACES: Final[dict[str, str]] = {"{": "(", "}": ")"}

#: Nesting of substitutions/subshells the view scanner follows before
#: giving up (returning the command unchanged).
_MAX_VIEW_DEPTH: Final[int] = 32

#: Characters that end a heredoc DELIMITER word when unquoted.
_DELIMITER_STOP_CHARS: Final[str] = " \t\n;&|<>()"

#: Shell-level text (quotes, comments and heredoc bodies blanked) that can
#: make `python3` name something else: a function definition, an alias,
#: `hash -p`, `enable`, or any touch of PATH (`PATH=`, `export PATH=`,
#: `read PATH`). Anywhere in the command, it withdraws every exemption.
#: Quoted and escaped spellings are judged word by word after quote removal
#: (:data:`_REDEFINING_WORDS`, :data:`_REDEFINED_VARIABLE_RE`).
_NAME_REDEFINITION_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[\s;&|(`])(?:alias|hash|enable|function)(?=[\s;&|)]|$)" r"|\bPATH\b" r"|[\w.-]\s*\(\s*\)"
)

#: Words that redefine what a command name runs, compared after quote and
#: backslash removal wherever they appear in a top-level command.
_REDEFINING_WORDS: Final[frozenset[str]] = frozenset({"alias", "hash", "enable", "function"})

#: A variable whose value changes which interpreter runs or what code it
#: loads before the program: PATH, and every PYTHON* setting except the
#: ones below. Matched inside a resolved word (`PATH=x`, `export PATH`).
_REDEFINED_VARIABLE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9_])(?:PATH|PYTHON[A-Z0-9_]*)(?![A-Za-z0-9_])"
)

#: PYTHON* settings that change only how the interpreter reports, buffers
#: or encodes, never what code it loads.
_HARMLESS_PYTHON_VARIABLES: Final[frozenset[str]] = frozenset(
    {
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
        "PYTHONIOENCODING",
        "PYTHONHASHSEED",
        "PYTHONUTF8",
        "PYTHONFAULTHANDLER",
        "PYTHONNOUSERSITE",
        "PYTHONSAFEPATH",
    }
)

#: Builtins that assign a variable NAMED by an argument (`export $v`,
#: `read -r "$v"`): an argument they take that cannot be resolved may name
#: PATH, so it withdraws the exemption.
_NAME_ASSIGNING_BUILTINS: Final[frozenset[str]] = frozenset(
    {
        "export",
        "declare",
        "typeset",
        "readonly",
        "local",
        "read",
        "printf",
        "mapfile",
        "readarray",
        "let",
        "getopts",
        "unset",
        "alias",
        "hash",
        "enable",
    }
)


class ScannedHeredoc(NamedTuple):
    """One heredoc the view scanner read: the command word it feeds (or
    ``None`` when the segment names none), its raw body, and whether its
    delimiter was quoted."""

    receiver: str | None
    body: str
    quoted: bool


class BraceExpansionView(NamedTuple):
    """``text``: the command with braces neutralised in exempted Python
    program text. ``heredocs``: every heredoc read, in order -- empty when
    the command could not be parsed with confidence. ``literals``: every
    string literal and comment of every exempted program, which the caller
    enumerates each on its own (:func:`python_string_literals`).
    ``code_words``: every brace word of every exempted program that is not
    wholly inside one literal or comment (:func:`python_program_streams`),
    which the caller enumerates each on its own, failing closed past the
    caps. ``shell_words``: the same, as bash splits the text
    (:func:`iter_shell_brace_words`), read by :func:`shell_word_spellings`."""

    text: str
    heredocs: tuple[ScannedHeredoc, ...]
    literals: tuple[str, ...] = ()
    code_words: tuple[str, ...] = ()
    shell_words: tuple[str, ...] = ()


class _ViewParseError(Exception):
    """The scanner met syntax it does not model with confidence."""


@dataclass
class _PendingHeredoc:
    delimiter: str
    strip_tabs: bool
    quoted: bool
    receiver: str | None
    #: Where ``<<`` sits, and the index just past its delimiter word.
    opener: int
    opener_end: int
    #: ``(start, end)`` of the body once read.
    body: tuple[int, int] | None = None


@dataclass
class _Segment:
    """One top-level simple command: its words as ``(start, end)`` spans
    and the separator that ended it (``""`` at the end of the command)."""

    words: list[tuple[int, int]]
    terminator: str


class _Program(NamedTuple):
    """An exemptible program's text span, and whether its stdout is
    redirected into a file."""

    start: int
    end: int
    writes_a_file: bool


def brace_expansion_view(command: str) -> BraceExpansionView:
    """``command`` with ``{``/``}`` neutralised in Python program text that
    no shell can read.

    Neutralised, and only this: the program of a TOP-LEVEL simple command
    whose command word is ``python``/``python3``/``python3.X``, bare or from
    a system directory, after nothing but ``NAME=value`` words --

    - the single-quoted word following ``-c``, or
    - the one quoted-delimiter heredoc (not ``<<-``) that is Python's stdin
      program (``python3 - <<'EOF'`` or ``python3 <<'EOF'``);

    and only when every one of these holds (D-RULE F1-F3, F5; D-SEC F1-F2):

    - no pipe stage follows the command, and no process substitution appears
      anywhere in the line;
    - the command is not inside ``( )``, ``{ }``, a compound command, a
      substitution, or under any wrapper (``sudo``, ``eval``, ``xargs``);
    - every command anywhere in the line, substitutions included, is on the
      allowlist of commands known not to run text as shell
      (:data:`_INERT_HEADS`, round 4), and nothing redefines ``python3`` or
      what it loads (a function, an alias, ``hash``, ``enable``, PATH, a
      ``PYTHON*`` setting). Heads and redefinition words are judged after
      quote and backslash removal (``'exec'``, ``\\exec`` and ``e\\xec`` are
      ``exec``), and a head, or an argument of a name-assigning builtin,
      that cannot be resolved with certainty withdraws the exemption;
    - no subshell, arithmetic command or function definition (a bare
      ``(``), no arithmetic expansion, no ``${...}`` but a plain name, and
      no unquoted heredoc whose body holds an expansion;
    - stdout goes to the terminal, a descriptor dup, ``/dev/null``, or a
      file no other command in the line can execute;
    - every Python option is one the scanner knows, and the program both
      tokenises and parses.

    Every string literal and comment of an exempted program is returned in
    ``literals`` (Plan 00466 N101 round 3): only CODE braces are exempt from
    the caps, so a brace-spelled path in a literal denies whatever the
    program does with it. Every brace word of the program text that is not
    wholly inside one literal or comment is returned in ``code_words``
    (round 5, D-RULE-4 MAJOR 1): a program can read its own command line
    back, so a set display against a name (``x .p-{"a",z}``) still spells a
    shell word. The conditions above keep code braces out of any shell's
    reach otherwise.

    Deliberately a scanner, not a shell parser: comments, backslash escapes,
    ``$'...'`` escapes, nested substitutions and heredoc bodies are tracked
    so quote state cannot be desynchronised into neutralising live shell
    text, and any construct outside that model (a ``case`` pattern's bare
    ``)``, an unterminated quote or heredoc, a quoted ``${...}``) returns
    the command UNCHANGED, with no heredocs reported.
    """
    scanner = _BraceViewScanner(command)
    try:
        scanner.scan(0, closer=None, top=True, depth=0)
    except _ViewParseError:
        return BraceExpansionView(command, ())
    literals: list[str] = []
    code_words: list[str] = []
    shell_words: list[str] = []
    for program in scanner.exempt_programs():
        streams = python_program_streams(command[program.start : program.end])
        if streams is None:
            continue
        scanner.neutralise(program.start, program.end)
        literals.extend(streams.literals)
        code_words.extend(streams.code_words)
        shell_words.extend(streams.shell_words)
    return BraceExpansionView(
        "".join(scanner.out),
        tuple(scanner.heredocs),
        tuple(literals),
        tuple(code_words),
        tuple(shell_words),
    )


def python_string_literals(source: str) -> tuple[str, ...] | None:
    """Every string literal and comment in the Python program ``source``,
    or ``None`` when it does not tokenise or parse (Plan 00466 N101 round 3).

    The boundaries are Python's own (:mod:`tokenize`, :mod:`ast`), so a
    brace in code -- a dict or set display, a comprehension, an f-string
    replacement field -- is never reported, and every literal is:

    - each ``str`` and ``bytes`` token on its own, raw or not, with escapes
      decoded (``'\\x7b'`` is ``{``), including each part of an implicit
      concatenation;
    - every constant the parsed program holds, which adds the concatenated
      value (``'/p{a,' 'x}ss'``), the literal text of an f-string with
      ``{{``/``}}`` unescaped, and strings nested in its fields;
    - every comment, since a program can read its own command line back;
    - the full source of every f-string, where a brace group can straddle
      its text and a field (``f'/p{a,x}ss'``, D-RULE MAJOR 1);
    - for every expression, the literals inside it joined in source order,
      so a group split across literals (``'/p{a,' + x + 'x}ss'``,
      ``''.join([...])``, ``f'{"{"}'``) is whole again (D-SEC minor 1);
    - every literal and comment of the program joined in source order with
      a space, so a group split across statements (``a = '/p{a,'`` then
      ``b = a + 'x}ss'``) is whole again: a brace group spans whitespace,
      which is how main's scan of the raw text denied it.

    ``None`` makes the caller keep the program's text as shell text, as
    :func:`python_program_streams` decides.
    """
    streams = python_program_streams(source)
    return None if streams is None else streams.literals


class PythonProgramStreams(NamedTuple):
    """What of a Python program the caller enumerates on its own:
    ``literals`` (:func:`python_string_literals`); ``code_words``, every
    brace word of the raw text found quote-blind and not wholly inside one
    literal or comment; and ``shell_words``, every brace word of the raw
    text as bash splits it."""

    literals: tuple[str, ...]
    code_words: tuple[str, ...]
    shell_words: tuple[str, ...] = ()


def python_program_streams(source: str) -> PythonProgramStreams | None:
    """The literals and code words of the Python program ``source``, or
    ``None`` when the program is not exempted (Plan 00466 N101 rounds 3-5).

    The scanner models CPython 3.8 to 3.14 source grammar, apart from the
    shapes withdrawn here. ``None`` -- the caller keeps the program's text
    as shell text -- when:

    - it does not tokenise or parse;
    - Python would decode its bytes differently from this ``str`` (a PEP
      263 declaration of any encoding but UTF-8, or a byte-order mark);
    - it holds a ``\\r``, which Python reads as a newline (alone or before
      ``\\n``) and the scanner does not model;
    - an f- or t-string field holds the string's own quote character, a
      backslash, a ``#``, a newline, or a nested f- or t-string: PEP 701
      (3.12) reads those differently from earlier versions, and the daemon's
      Python need not be the one that runs the program;
    - :mod:`tokenize` and :mod:`ast` disagree on where any literal starts or
      ends.

    ``code_words`` are the words :func:`iter_brace_words` finds in the raw
    text, less those wholly inside one string literal or comment, which
    ``literals`` reports already (D-RULE-4 MAJOR 1). ``shell_words`` are
    every word :func:`iter_shell_brace_words` finds, inside a literal
    or not (D-RULE-6 MAJOR 1): Python's quoting and bash's can disagree
    about where a literal ends, and an escape can change the literal's
    braces, so its decoded value does not stand for the word bash reads.
    Bash's own quoting makes a brace inside a shell quote text, so an
    ordinary literal expands nothing.
    """
    if "\r" in source:
        return None
    try:
        if not _decodes_as_utf8(source):
            return None
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        tree = ast.parse(source)
        lines = source.split("\n")
        line_starts = [0]
        for line in lines:
            line_starts.append(line_starts[-1] + len(line) + 1)
        found = _literal_tokens(source, line_starts, tokens)
        if any(_template_field_may_drift(template) for template in found.templates):
            return None
        if not _literal_spans_agree(lines, line_starts, tree, found.strings):
            return None
        literals: list[str] = []
        in_order: list[str] = []
        for token in tokens:
            if token.type == tokenize.COMMENT:
                in_order.append(token.string)
            elif token.type == tokenize.STRING:
                in_order.extend(_constant_strings(ast.parse(token.string, mode="eval")))
            elif token.type in _TEMPLATE_MIDDLE_TOKENS:
                in_order.append(token.string)
        literals.extend(in_order)
        literals.append(" ".join(in_order))
        literals.extend(_constant_strings(tree))
        literals.extend(_f_string_sources(source, tree))
        literals.extend(_assembled_literals(tree))
    except (SyntaxError, ValueError, RecursionError, LookupError, tokenize.TokenError) as error:
        logger.warning(
            "python3 program not readable as Python, so its text is enumerated whole: %s",
            error,
        )
        streams: PythonProgramStreams | None = None
    else:
        streams = PythonProgramStreams(
            tuple(dict.fromkeys(literals)),
            tuple(dict.fromkeys(_code_brace_words(source, found.spans))),
            tuple(dict.fromkeys(iter_shell_brace_words(source))),
        )
    return streams


def _token_type(name: str) -> int | None:
    value = getattr(tokenize, name, None)
    return value if isinstance(value, int) else None


#: f- and t-string tokens, on Pythons that split them into tokens (3.12+
#: and 3.14+); earlier ones tokenise an f-string as one STRING.
_TEMPLATE_START_TOKENS: Final[frozenset[int]] = frozenset(
    token for token in (_token_type("FSTRING_START"), _token_type("TSTRING_START")) if token
)
_TEMPLATE_MIDDLE_TOKENS: Final[frozenset[int]] = frozenset(
    token for token in (_token_type("FSTRING_MIDDLE"), _token_type("TSTRING_MIDDLE")) if token
)
_TEMPLATE_END_TOKENS: Final[frozenset[int]] = frozenset(
    token for token in (_token_type("FSTRING_END"), _token_type("TSTRING_END")) if token
)

#: A string token's prefix and opening quote.
_STRING_OPENER_RE: Final[re.Pattern[str]] = re.compile(r"([A-Za-z]*)('''|\"\"\"|'|\")")

#: Characters in an f- or t-string field that PEP 701 reads differently
#: from earlier versions (the string's own quote is checked separately).
_DRIFTING_FIELD_CHARS: Final[frozenset[str]] = frozenset("\\#\n")

#: String prefix letters that make a string an f- or t-string.
_TEMPLATE_PREFIX_LETTERS: Final[frozenset[str]] = frozenset("fFtT")

#: String node types of the parsed program; ``TemplateStr`` is 3.14+.
_TEMPLATE_NODES: Final[tuple[type[ast.expr], ...]] = tuple(
    node
    for node in (ast.JoinedStr, getattr(ast, "TemplateStr", None))
    if isinstance(node, type) and issubclass(node, ast.expr)
)


class _LiteralTokens(NamedTuple):
    """``spans``: ``(start, end)`` of every string and comment token, a
    whole f- or t-string as one, in order. ``strings``: the same without
    comments. ``templates``: the source of every f- or t-string."""

    spans: list[tuple[int, int]]
    strings: list[tuple[int, int]]
    templates: list[str]


def _literal_tokens(
    source: str, line_starts: list[int], tokens: list[tokenize.TokenInfo]
) -> _LiteralTokens:
    """Where the literals and comments of ``source`` are, by
    :mod:`tokenize` (row and character column, ``\\n``-split lines)."""

    def offset(position: tuple[int, int]) -> int:
        return line_starts[position[0] - 1] + position[1]

    found = _LiteralTokens([], [], [])
    open_templates: list[int] = []
    for token in tokens:
        if token.type in _TEMPLATE_START_TOKENS:
            open_templates.append(offset(token.start))
        elif token.type in _TEMPLATE_END_TOKENS:
            start = open_templates.pop()
            if not open_templates:
                span = (start, offset(token.end))
                found.spans.append(span)
                found.strings.append(span)
                found.templates.append(source[span[0] : span[1]])
        elif open_templates:
            continue
        elif token.type in (tokenize.STRING, tokenize.COMMENT):
            span = (offset(token.start), offset(token.end))
            found.spans.append(span)
            if token.type == tokenize.COMMENT:
                continue
            found.strings.append(span)
            opener = _STRING_OPENER_RE.match(token.string)
            if opener is not None and _TEMPLATE_PREFIX_LETTERS & set(opener.group(1)):
                found.templates.append(token.string)
    return found


def _template_field_may_drift(template: str) -> bool:
    """Whether a field of the f- or t-string ``template`` (its full source,
    prefix and quotes included) holds a shape PEP 701 reads differently:
    the string's own quote, a backslash, ``#``, a newline, or a nested f-
    or t-string. Unreadable text counts as drift."""
    opener = _STRING_OPENER_RE.match(template)
    if opener is None or not template.endswith(opener.group(2)):
        return True
    raw = "r" in opener.group(1).lower()
    quote = opener.group(2)
    body = template[opener.end() : len(template) - len(quote)]
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and not raw:
            if body.startswith("\\", index + 1):
                index += 2
            elif body.startswith("N{", index + 1):
                close = body.find("}", index + 3)
                if close < 0:
                    return True
                index = close + 1
            else:
                index += 1
        elif char == "{" and body.startswith("{", index + 1):
            index += 2
        elif char == "{":
            end = _field_end(body, index + 1, quote[0])
            if end is None:
                return True
            index = end + 1
        else:
            index += 1
    return False


def _field_end(body: str, start: int, quote: str) -> int | None:
    """Index of the ``}`` closing the field opened just before ``start``,
    or ``None`` when the field holds a drifting shape or never closes."""
    depth = 0
    for index in range(start, len(body)):
        char = body[index]
        if char in _DRIFTING_FIELD_CHARS or char == quote:
            return None
        if char in "'\"" and _opens_a_template(body, start, index):
            return None
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if char == "}" and depth == 0:
                return index
            depth -= 1
    return None


def _opens_a_template(body: str, field_start: int, quote_index: int) -> bool:
    """Whether the quote at ``quote_index`` opens an f- or t-string: the
    letters just before it, a whole name, hold ``f`` or ``t``."""
    index = quote_index
    while index > field_start and body[index - 1].isalpha():
        index -= 1
    if index > field_start and (body[index - 1].isalnum() or body[index - 1] == "_"):
        return False
    return bool(_TEMPLATE_PREFIX_LETTERS & set(body[index:quote_index]))


#: A UTF-8 continuation byte is ``0b10xxxxxx``: a column there splits a
#: character, so it is not the start of one.
_UTF8_CONTINUATION_MASK: Final[int] = 0xC0
_UTF8_CONTINUATION: Final[int] = 0x80


def _literal_spans_agree(
    lines: list[str], line_starts: list[int], tree: ast.AST, strings: list[tuple[int, int]]
) -> bool:
    """Whether every string node :mod:`ast` reports starts where a string
    token starts and ends where one ends, and every string token lies
    inside a string node (D-SEC-4, unexamined 2c). Nodes inside an f- or
    t-string are not visited: before 3.12 their positions are not the
    source's. ``ast`` columns are UTF-8 byte offsets."""
    token_starts = {start for start, _ in strings}
    token_ends = {end for _, end in strings}
    encoded = [line.encode("utf-8") for line in lines]

    def offset(row: int | None, column: int | None) -> int | None:
        if row is None or column is None or not 0 < row <= len(lines):
            return None
        raw = encoded[row - 1]
        if column < len(raw) and raw[column] & _UTF8_CONTINUATION_MASK == _UTF8_CONTINUATION:
            return None
        return line_starts[row - 1] + len(raw[:column].decode("utf-8"))

    nodes: list[tuple[int, int]] = []
    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        is_string = isinstance(node, _TEMPLATE_NODES) or (
            isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes))
        )
        if not is_string:
            stack.extend(ast.iter_child_nodes(node))
            continue
        start = offset(getattr(node, "lineno", None), getattr(node, "col_offset", None))
        end = offset(getattr(node, "end_lineno", None), getattr(node, "end_col_offset", None))
        if start is None or end is None or start not in token_starts or end not in token_ends:
            return False
        nodes.append((start, end))
    nodes.sort()
    node_starts = [start for start, _ in nodes]
    for start, end in strings:
        index = bisect.bisect_right(node_starts, start) - 1
        if index < 0 or nodes[index][1] < end:
            return False
    return True


def _code_brace_words(source: str, spans: list[tuple[int, int]]) -> Iterator[str]:
    """Every word :func:`iter_brace_words` finds in ``source`` that is not
    wholly inside one of ``spans`` (sorted, non-overlapping)."""
    span_starts = [span_start for span_start, _ in spans]
    for start, end in _brace_word_spans(source):
        if _outside_every_span(spans, span_starts, start, end):
            yield source[start:end]


def _outside_every_span(
    spans: list[tuple[int, int]], span_starts: list[int], start: int, end: int
) -> bool:
    index = bisect.bisect_right(span_starts, start) - 1
    return index < 0 or end > spans[index][1]


def _decodes_as_utf8(source: str) -> bool:
    """Whether Python, reading ``source`` as the UTF-8 bytes bash hands it,
    decodes exactly this text (D-SEC round 3, the unexamined question)."""
    encoded = source.encode("utf-8")
    encoding, _ = tokenize.detect_encoding(io.BytesIO(encoded).readline)
    return codecs.lookup(encoding).name == "utf-8" and encoded.decode(encoding) == source


#: One physical line, split where the parser splits (``\r\n``, ``\r``,
#: ``\n``), its terminator kept.
_SOURCE_LINE_RE: Final[re.Pattern[str]] = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)?")


def _f_string_sources(source: str, tree: ast.AST) -> Iterator[str]:
    """The source text of every f- or t-string in ``tree``. Positions are UTF-8
    byte offsets into lines, as :func:`ast.get_source_segment` reads them,
    with the lines split once rather than once per node."""
    lines = [match.group(0).encode("utf-8") for match in _SOURCE_LINE_RE.finditer(source)]
    for node in ast.walk(tree):
        if not isinstance(node, _TEMPLATE_NODES) or node.end_lineno is None:
            continue
        if node.end_col_offset is None:
            continue
        first, last = node.lineno - 1, node.end_lineno - 1
        if first == last:
            segment = lines[first][node.col_offset : node.end_col_offset]
        else:
            segment = b"".join(
                [
                    lines[first][node.col_offset :],
                    *lines[first + 1 : last],
                    lines[last][: node.end_col_offset],
                ]
            )
        yield segment.decode("utf-8")


def _assembled_literals(tree: ast.AST) -> Iterator[str]:
    """For every outermost expression (one whose parent is not itself an
    expression: a statement's value, an argument default, a keyword's
    value), its string and bytes literals joined in source order."""
    for parent in ast.walk(tree):
        if isinstance(parent, ast.expr):
            continue
        for child in ast.iter_child_nodes(parent):
            if isinstance(child, ast.expr):
                joined = "".join(_literals_in_source_order(child))
                if joined:
                    yield joined


def _literals_in_source_order(root: ast.expr) -> Iterator[str]:
    """Every ``str`` or ``bytes`` constant under ``root``, in source order."""
    stack: list[ast.AST] = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                yield node.value
            elif isinstance(node.value, bytes):
                yield node.value.decode("latin-1")
            continue
        if isinstance(node, ast.Dict):
            children: list[ast.AST] = [
                part
                for key, value in zip(node.keys, node.values, strict=True)
                for part in (key, value)
                if part is not None
            ]
        elif isinstance(node, ast.IfExp):
            children = [node.body, node.test, node.orelse]
        else:
            children = list(ast.iter_child_nodes(node))
        stack.extend(reversed(children))


def _constant_strings(tree: ast.AST) -> Iterator[str]:
    """Every ``str`` or ``bytes`` constant in ``tree``; bytes decoded one
    character per byte, so every byte keeps its own position."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                yield node.value
            elif isinstance(node.value, bytes):
                yield node.value.decode("latin-1")


class _BraceViewScanner:
    """One pass over a command for :func:`brace_expansion_view`."""

    def __init__(self, command: str) -> None:
        self.text = command
        self.out = list(command)
        self.heredocs: list[ScannedHeredoc] = []
        #: Positions inside a quote, comment or heredoc body -- not shell
        #: syntax, so never read as a redefinition of a command name.
        self.masked = [False] * len(command)
        #: Top-level simple commands, heredocs and single-quoted spans
        #: (opening quote index -> closing quote index).
        self.segments: list[_Segment] = []
        #: Every simple command at any depth, substitutions included.
        self.all_segments: list[_Segment] = []
        self.top_heredocs: dict[int, _PendingHeredoc] = {}
        self.single_quotes: dict[int, int] = {}
        self.saw_process_substitution = False
        #: A bare `(` anywhere: a subshell, an arithmetic command `((...))`
        #: or a function definition (`python3() { ...; }`, however its name
        #: is spelled).
        self.saw_bare_paren = False
        #: An arithmetic expansion (`$((...))`, `$[...]`), whose array
        #: subscripts run `$(...)`.
        self.saw_arithmetic = False

    def mask(self, start: int, end: int) -> None:
        for index in range(start, end):
            self.masked[index] = True

    def shell_level_text(self) -> str:
        return "".join(
            " " if hidden else char for char, hidden in zip(self.text, self.masked, strict=True)
        )

    def neutralise(self, start: int, end: int) -> None:
        for index in range(start, end):
            replacement = _NEUTRAL_BRACES.get(self.text[index])
            if replacement is not None:
                self.out[index] = replacement

    def command_word(self, start: int, end: int) -> str | None:
        return segment_command_word(self.text[start:end])

    def word(self, span: tuple[int, int]) -> str:
        return self.text[span[0] : span[1]]

    def exempt_programs(self) -> list[_Program]:
        """Every program whose braces may be neutralised; empty when any
        line-wide condition fails."""
        if self.saw_process_substitution or self.saw_bare_paren or self.saw_arithmetic:
            return []
        if _NAME_REDEFINITION_RE.search(self.shell_level_text()):
            return []
        # An unquoted heredoc body is expanded: its substitutions run.
        if any(
            not heredoc.quoted and _EXPANDING_CHARS & set(heredoc.body) for heredoc in self.heredocs
        ):
            return []
        programs: list[_Program] = []
        for segment in self.segments:
            program = self.segment_program(segment)
            if program is None:
                continue
            if program.writes_a_file and not self.only_inert_siblings(segment):
                continue
            programs.append(program)
        # A `-c` program's own word is Python, not a shell word: its text
        # may mention PATH without assigning it.
        program_words = {program.start - 1 for program in programs}
        if any(
            self.withdraws_the_exemption(segment, program_words) for segment in self.all_segments
        ):
            return []
        return programs

    def head_index(self, segment: _Segment) -> int | None:
        """Index of the segment's command word, past ``NAME=value`` words
        and redirections (``>f exec`` is ``exec``); ``None`` if it has none."""
        words = segment.words
        index = 0
        while index < len(words):
            word = self.word(words[index])
            redirect = _REDIRECT_RE.fullmatch(word)
            if redirect is not None:
                index += 1 if redirect.group("target") else 2
            elif _ASSIGNMENT_RE.match(word):
                index += 1
            else:
                return index
        return None

    def head(self, segment: _Segment) -> str | None:
        """The segment's command word after quote removal; ``""`` when it
        has none, ``None`` when it cannot be resolved."""
        index = self.head_index(segment)
        if index is None:
            return ""
        return resolve_shell_word(self.word(segment.words[index]))

    def withdraws_the_exemption(self, segment: _Segment, program_words: set[int]) -> bool:
        """Whether ``segment`` runs anything but an inert command
        (:data:`_INERT_HEADS`), or can change what ``python3`` names or
        loads -- judged on every word after quote and backslash removal
        (D-RULE B1 and M1). Words starting at ``program_words`` are exempted
        program text."""
        index = self.head_index(segment)
        if index is not None and not self.runs_an_inert_command(segment, index):
            return True
        head = self.head(segment)
        for span in segment.words:
            if span[0] in program_words:
                continue
            raw = self.word(span)
            resolved = resolve_shell_word(raw)
            if resolved is None:
                if head in _NAME_ASSIGNING_BUILTINS:
                    return True
                resolved = raw
            if resolved in _REDEFINING_WORDS:
                return True
            for variable in _REDEFINED_VARIABLE_RE.finditer(resolved):
                if variable.group(0) not in _HARMLESS_PYTHON_VARIABLES:
                    return True
        return False

    def runs_an_inert_command(self, segment: _Segment, index: int) -> bool:
        """Whether the command at word ``index`` of ``segment``, seen
        through any wrapper, is Python or on :data:`_INERT_HEADS`, each
        word in command position named bare or from a system directory."""
        words = segment.words
        head = resolve_shell_word(self.word(words[index]))
        chain = segment_command_chain(self.text[words[index][0] : words[-1][1]])
        if head is None or chain is None or chain[0] != head:
            return False
        names: list[str] = []
        for word in chain:
            trusted = _TRUSTED_COMMAND_RE.fullmatch(word)
            if trusted is None:
                return False
            names.append(trusted.group("name"))
        if _PYTHON_INTERPRETER_RE.fullmatch(chain[-1]):
            return True
        if names[-1] not in _INERT_HEADS:
            return False
        if names[-1] in (_SET_BUILTIN, _EXPORT_BUILTIN):
            return len(chain) == 1 and self.inert_builtin_operands(names[-1], words[index + 1 :])
        return True

    def inert_builtin_operands(self, builtin: str, spans: list[tuple[int, int]]) -> bool:
        """Whether every operand of ``set`` or ``export`` is one that runs
        nothing: no tracing for ``set``, plain names for ``export``."""
        for span in spans:
            raw = self.word(span)
            if _REDIRECT_RE.fullmatch(raw):
                continue
            operand = resolve_shell_word(raw)
            if operand is None:
                return False
            if builtin == _SET_BUILTIN and _XTRACE_OPERAND_RE.fullmatch(operand):
                return False
            if builtin == _EXPORT_BUILTIN and not _EXPORT_OPERAND_RE.fullmatch(operand):
                return False
        return True

    def only_inert_siblings(self, own: _Segment) -> bool:
        return all(
            segment is own or self.head(segment) in _INERT_SIBLING_HEADS or not segment.words
            for segment in self.segments
        )

    def has_unquoted_redirect_char(self, span: tuple[int, int]) -> bool:
        return any(self.text[index] in "<>" and not self.masked[index] for index in range(*span))

    def segment_program(self, segment: _Segment) -> _Program | None:
        """The program of ``segment`` if it is an exemptible Python command."""
        if segment.terminator in _PIPE_TERMINATORS:
            return None
        words = segment.words
        index = 0
        while index < len(words) and _ASSIGNMENT_RE.match(self.word(words[index])):
            index += 1
        if index >= len(words) or not _PYTHON_INTERPRETER_RE.fullmatch(self.word(words[index])):
            return None
        index += 1
        code: tuple[int, int] | None = None
        options_done = False
        writes_a_file = False
        heredocs: list[_PendingHeredoc] = []
        while index < len(words):
            span = words[index]
            word = self.word(span)
            redirect = _REDIRECT_RE.fullmatch(word)
            if redirect is not None:
                op, target = redirect.group("op"), redirect.group("target")
                if op in ("<<", "<<-"):
                    heredoc = self.top_heredocs.get(span[0] + len(redirect.group("fd")))
                    if heredoc is None or heredoc.opener_end != span[1]:
                        return None
                    heredocs.append(heredoc)
                    index += 1
                    continue
                if op.startswith("<"):
                    return None
                if not target:
                    if index + 1 >= len(words):
                        return None
                    target = self.word(words[index + 1])
                    index += 1
                index += 1
                if any(char in target for char in "<>&|;"):
                    return None
                if op == ">&" and target.isdigit():
                    if target not in _HARMLESS_DUP_TARGETS:
                        return None
                elif target not in _HARMLESS_OUTPUT_TARGETS | _HARMLESS_DUP_TARGETS:
                    writes_a_file = True
                continue
            if self.has_unquoted_redirect_char(span):
                return None
            if options_done:
                index += 1
                continue
            if word == "-c":
                if index + 1 >= len(words):
                    return None
                start, end = words[index + 1]
                if self.single_quotes.get(start) != end - 1:
                    return None
                code = (start + 1, end - 1)
                options_done = True
                index += 2
                continue
            if word == "-":
                options_done = True
                index += 1
                continue
            consumed = self.python_option_words(words, index)
            if consumed is None:
                return None
            index += consumed
        if code is not None:
            return _Program(code[0], code[1], writes_a_file)
        if len(heredocs) != 1:
            return None
        heredoc = heredocs[0]
        if not heredoc.quoted or heredoc.strip_tabs or heredoc.body is None:
            return None
        return _Program(heredoc.body[0], heredoc.body[1], writes_a_file)

    def python_option_words(self, words: list[tuple[int, int]], index: int) -> int | None:
        """How many words the option cluster at ``index`` takes, or ``None``
        when it is not an option this scanner knows."""
        word = self.word(words[index])
        if not word.startswith("-") or word.startswith("--"):
            return None
        letters = word[1:]
        for position, letter in enumerate(letters):
            if letter in _PYTHON_FLAG_LETTERS:
                continue
            if letter not in _PYTHON_VALUE_FLAG_LETTERS:
                return None
            if position + 1 < len(letters):
                return 1
            if index + 1 >= len(words):
                return None
            value = words[index + 1]
            if self.has_unquoted_redirect_char(value) or _REDIRECT_RE.fullmatch(self.word(value)):
                return None
            return 2
        return 1

    def scan(self, index: int, *, closer: str | None, top: bool, depth: int) -> int:
        """Scan one command context from ``index`` to its ``closer`` (``)``
        or a backtick; ``None`` for the whole command). Returns the index
        just past the closer. Only the ``top`` context records segments,
        heredoc openers and single-quoted spans: nothing inside a subshell
        or a substitution is ever exempted."""
        if depth > _MAX_VIEW_DEPTH:
            raise _ViewParseError("nesting too deep")
        text = self.text
        length = len(text)
        command_start = index
        pending: list[_PendingHeredoc] = []
        at_word_start = True
        words: list[tuple[int, int]] = []
        word_start: int | None = None
        while index < length:
            char = text[index]
            if closer is not None and char == closer:
                if pending:
                    raise _ViewParseError("heredoc opened but never read")
                if word_start is not None:
                    words.append((word_start, index))
                self.all_segments.append(_Segment(words, closer))
                return index + 1
            if char in " \t":
                if word_start is not None:
                    words.append((word_start, index))
                    word_start = None
                at_word_start = True
                index += 1
                continue
            if char == "#" and at_word_start:
                newline = text.find("\n", index)
                end = length if newline == -1 else newline
                self.mask(index, end)
                index = end
                continue
            separator = self.separator_at(index)
            if separator:
                if word_start is not None:
                    words.append((word_start, index))
                    word_start = None
                segment = _Segment(words, separator)
                self.all_segments.append(segment)
                if top:
                    self.segments.append(segment)
                words = []
                index += len(separator)
                if separator == "\n" and pending:
                    index = self.read_bodies(index, pending)
                    pending = []
                command_start = index
                at_word_start = True
                continue
            if word_start is None:
                word_start = index
            at_word_start = False
            if char == "\\":
                index += 2
                continue
            if char == "'":
                end = text.find("'", index + 1)
                if end == -1:
                    raise _ViewParseError("unterminated single quote")
                if top:
                    self.single_quotes[index] = end
                self.mask(index, end + 1)
                index = end + 1
                continue
            if text.startswith("$'", index):
                end = self.ansi_c_end(index + 2)
                self.mask(index, end + 1)
                index = end + 1
                continue
            if char == '"':
                end = self.scan_double(index + 1, depth)
                self.mask(index, end)
                index = end
                continue
            if text.startswith(("$((", "$["), index):
                self.saw_arithmetic = True
            if text.startswith("$((", index):
                index = self.skip_arithmetic(index + 3)
                continue
            if text.startswith(("<(", ">("), index):
                self.saw_process_substitution = True
                index = self.scan(index + 2, closer=")", top=False, depth=depth + 1)
                continue
            if text.startswith("$(", index):
                index = self.scan(index + 2, closer=")", top=False, depth=depth + 1)
                continue
            if text.startswith("${", index):
                index = self.skip_parameter(index + 2)
                continue
            if char == "`":
                index = self.scan(index + 1, closer="`", top=False, depth=depth + 1)
                continue
            if char == "(":
                self.saw_bare_paren = True
                index = self.scan(index + 1, closer=")", top=False, depth=depth + 1)
                continue
            if char == ")":
                raise _ViewParseError("unmatched )")
            if text.startswith("<<<", index):
                index += 3
                at_word_start = True
                continue
            if text.startswith("<<", index):
                index = self.read_heredoc_opener(index, command_start, top, pending)
                at_word_start = True
                continue
            index += 1
        if word_start is not None:
            words.append((word_start, index))
        if closer is not None:
            raise _ViewParseError(f"unterminated context awaiting {closer!r}")
        if pending:
            raise _ViewParseError("heredoc opened with no body")
        segment = _Segment(words, "")
        self.all_segments.append(segment)
        if top:
            self.segments.append(segment)
        return index

    def separator_at(self, index: int) -> str:
        """The command separator starting at ``index``, or ``""`` -- an
        ``&`` inside a redirection (``2>&1``, ``&>f``) is not one."""
        text = self.text
        char = text[index]
        if char == "\n":
            return "\n"
        if char not in ";&|":
            return ""
        if char == "&" and (
            (index > 0 and text[index - 1] in "<>") or text.startswith("&>", index)
        ):
            return ""
        for token in ("||", "&&", ";;", "|&"):
            if text.startswith(token, index):
                return token
        return char

    def ansi_c_end(self, index: int) -> int:
        """Index of the quote closing a ``$'...'`` body starting at ``index``."""
        text = self.text
        while index < len(text):
            if text[index] == "\\":
                index += 2
                continue
            if text[index] == "'":
                return index
            index += 1
        raise _ViewParseError("unterminated $'...'")

    def scan_double(self, index: int, depth: int) -> int:
        """Skip a double-quoted span; substitutions inside are scanned as
        their own (substitution) contexts. Returns the index past the ``"``."""
        text = self.text
        while index < len(text):
            char = text[index]
            if char == '"':
                return index + 1
            if char == "\\":
                index += 2
                continue
            if text.startswith(("$((", "$["), index):
                self.saw_arithmetic = True
            if text.startswith("$((", index):
                index = self.skip_arithmetic(index + 3)
                continue
            if text.startswith("$(", index):
                index = self.scan(index + 2, closer=")", top=False, depth=depth + 1)
                continue
            if text.startswith("${", index):
                index = self.skip_parameter(index + 2)
                continue
            if char == "`":
                index = self.scan(index + 1, closer="`", top=False, depth=depth + 1)
                continue
            index += 1
        raise _ViewParseError("unterminated double quote")

    def skip_arithmetic(self, index: int) -> int:
        """Skip a ``$((...))`` body; quotes inside are outside the model."""
        text = self.text
        depth = 2
        while index < len(text):
            char = text[index]
            if char in "'\"`":
                raise _ViewParseError("quote inside arithmetic expansion")
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index + 1
            index += 1
        raise _ViewParseError("unterminated arithmetic expansion")

    def skip_parameter(self, index: int) -> int:
        """Skip a ``${...}`` body; anything but a plain parameter name
        (:data:`_PLAIN_PARAMETER_RE`) is outside the model."""
        end = self.text.find("}", index)
        if end == -1:
            raise _ViewParseError("unterminated ${...}")
        if not _PLAIN_PARAMETER_RE.fullmatch(self.text, index, end):
            raise _ViewParseError("${...} other than a plain parameter name")
        return end + 1

    def read_heredoc_opener(
        self,
        index: int,
        command_start: int,
        top: bool,
        pending: list[_PendingHeredoc],
    ) -> int:
        """Record the heredoc whose ``<<`` sits at ``index``; return the
        index past its delimiter word."""
        text = self.text
        cursor = index + 2
        strip_tabs = text.startswith("-", cursor)
        if strip_tabs:
            cursor += 1
        while cursor < len(text) and text[cursor] in " \t":
            cursor += 1
        pieces: list[str] = []
        quoted = False
        while cursor < len(text) and text[cursor] not in _DELIMITER_STOP_CHARS:
            char = text[cursor]
            if char in "'\"":
                end = text.find(char, cursor + 1)
                if end == -1:
                    raise _ViewParseError("unterminated quote in heredoc delimiter")
                pieces.append(text[cursor + 1 : end])
                quoted = True
                cursor = end + 1
                continue
            if char == "\\":
                quoted = True
                pieces.append(text[cursor + 1 : cursor + 2])
                cursor += 2
                continue
            if char in "$`":
                raise _ViewParseError("expansion in heredoc delimiter")
            pieces.append(char)
            cursor += 1
        delimiter = "".join(pieces)
        if not delimiter:
            raise _ViewParseError("empty heredoc delimiter")
        heredoc = _PendingHeredoc(
            delimiter=delimiter,
            strip_tabs=strip_tabs,
            quoted=quoted,
            receiver=self.command_word(command_start, index),
            opener=index,
            opener_end=cursor,
        )
        pending.append(heredoc)
        if top:
            self.top_heredocs[index] = heredoc
        return cursor

    def read_bodies(self, index: int, pending: list[_PendingHeredoc]) -> int:
        """Read each pending heredoc's body in order from ``index``; return
        the index past the last closing delimiter line."""
        text = self.text
        for heredoc in pending:
            body_start = index
            while True:
                if index >= len(text):
                    raise _ViewParseError("heredoc closer never found")
                newline = text.find("\n", index)
                line_end = len(text) if newline == -1 else newline
                line = text[index:line_end]
                if (line.lstrip("\t") if heredoc.strip_tabs else line) == heredoc.delimiter:
                    body_end = index
                    index = line_end + 1 if newline != -1 else len(text)
                    break
                if newline == -1:
                    raise _ViewParseError("heredoc closer never found")
                index = newline + 1
            heredoc.body = (body_start, body_end)
            self.heredocs.append(
                ScannedHeredoc(heredoc.receiver, text[body_start:body_end], heredoc.quoted)
            )
            self.mask(body_start, body_end)
        return index


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

#: `ssh` invoked with a LOOPBACK target (`ssh localhost CMD`, `ssh user@
#: 127.0.0.1 CMD`) executes CMD on THIS machine, not a remote one -- review
#: 7 follow-up (gd6_shell2 residual). Any OTHER target is a genuine remote
#: host, whose filesystem this project's protected-path patterns say
#: nothing about, so `ssh host CMD` for a non-loopback host is
#: deliberately NOT recursed into (that would fail closed on every
#: everyday `ssh deploy@server 'systemctl restart myapp'`).
_SSH_BASENAMES: Final[frozenset[str]] = frozenset({"ssh"})
_SSH_LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1"})
#: Common `ssh` short flags that take their value as the NEXT word -- a
#: best-effort walk (an unrecognised flag simply is not skipped, so the
#: NEXT word is misread as the target and, if it happens not to be a
#: loopback host, this recursion just does not fire -- fails toward NOT
#: recursing, never toward a false deny).
_SSH_SHORT_VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "-p",
        "-i",
        "-o",
        "-l",
        "-F",
        "-J",
        "-c",
        "-S",
        "-w",
        "-B",
        "-b",
        "-m",
        "-O",
        "-Q",
        "-e",
        "-R",
        "-L",
        "-D",
        "-W",
    }
)


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


#: `source <(PRODUCER)` -- review 7 follow-up (gd6_shell2 residual, row
#: "source nonliteral -> fail closed"): review 6 MAJOR-2's own deliberate
#: default is "scan the producer's own command text, deny only if THAT
#: mentions a protected path" -- kept UNCHANGED for the general case
#: (`source <(cat somefile)`, `source <(some-devops-tool print-env)`,
#: every completion/init generator already pinned in the false-positive
#: corpus), since that default is precisely what avoids failing closed on
#: everyday `source <(kubectl completion bash)`-shaped commands.
#:
#: The gap review 7 found is narrower: a producer that OPAQUELY TRANSFORMS
#: its input (base64/openssl/gzip-family decoding) can turn ANY payload
#: into the sourced script, and scanning the DECODER's own invocation text
#: (`base64 -d`) can never reveal what it decodes TO. These are the only
#: basenames that override review 6's default and fail closed.
_OPAQUE_SOURCE_TRANSFORM_BASENAMES: Final[frozenset[str]] = frozenset(
    {
        "base64",
        "base32",
        "openssl",
        "xxd",
        "gzip",
        "gunzip",
        "zcat",
        "bzip2",
        "bunzip2",
        "bzcat",
        "xz",
        "unxz",
        "xzcat",
        "uudecode",
        "iconv",
    }
)


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


def _close_backtick(text: str, start: int) -> tuple[int, str]:
    """Find the backtick that closes a backtick command substitution whose
    body begins at ``start`` (just past the opening backtick), and return
    its index together with the body UN-ESCAPED per bash's backtick rules.

    Plan 00466 review 8 MAJOR-B: a plain ``text.find("`", start)`` finds an
    ESCAPED inner backtick (``\\```) first, cutting the outer body short --
    ``` `echo \\`bash -c '...'\\`` ``` closed after the first ``\\```
    instead of the real outer close, so the inner ``bash -c`` was never
    re-parsed as its own nested command. Inside a backtick span, bash gives
    backslash its literal meaning EXCEPT before another backtick, a dollar
    sign, or itself (bash manual, "Command Substitution") -- so those three
    escapes are undone here and every other backslash is kept literal,
    matching what the shell itself hands the nested command.

    Returns ``(-1, body)`` with ``body`` running to the end of ``text`` when
    no closing backtick is found (an unterminated span).
    """
    out: list[str] = []
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in ("`", "$", "\\"):
            out.append(text[i + 1])
            i += 2
            continue
        if ch == "`":
            return i, "".join(out)
        out.append(ch)
        i += 1
    return -1, "".join(out)


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
                    j, body = _close_backtick(text, i + 1)
                    if substitutions is not None and j != -1:
                        substitutions.append(body)
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
        if ch == "$" and text.startswith('"', i + 1):
            # `$"..."` is locale translation: bash drops the `$` and reads
            # the rest as `"..."` (Plan 00466 N111).
            i += 1
            continue
        if ch == "$":
            piece, end = _consume_dollar(text, i, substitutions=substitutions)
            out.append(piece)
            i = end
            continue
        if ch == "`":
            j, body = _close_backtick(text, i + 1)
            if substitutions is not None and j != -1:
                substitutions.append(body)
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


def iter_normalised_shell_words(
    command: str,
    *,
    max_words: int = DEFAULT_MAX_NORMALISED_WORDS,
    deadline: float | None = None,
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

    Review 7 follow-up (team-lead): flat, non-recursive word decoding is
    LINEAR in ``command``'s length -- no word here multiplies into more
    work the way a brace group or a nested re-parse can, so a hard
    per-command word-COUNT cap was the wrong instrument for it. Denying
    "every command/file over ~2000 words" this way cost real everyday
    input -- a long plan document, a long commit message, an ordinary
    source file -- for no matching security benefit: nothing about a
    flat word stream explodes.

    ``max_words`` therefore no longer bounds this stream at all (kept as a
    parameter only for signature/API stability with :func:`iter_brace_words`,
    whose OWN cap -- brace expansion genuinely IS combinatorial -- is
    unaffected). The real backstop for VOLUME is ``deadline`` (a
    ``time.monotonic()`` cutoff, checked periodically as words are
    produced): past it this raises ``TimeoutError``, the SAME fail-closed
    signal :func:`secret_file_matching.iter_protected_mentions` already
    treats as "cannot rule out a protected path" for its own whole-scan
    deadline -- one doctrine, not two competing ones. A caller that omits
    ``deadline`` gets an unbounded-in-principle generator, same as before
    this fix; every caller inside this project supplies one.

    Genuine combinatorial growth stays capped exactly as before: brace
    expansion (:func:`iter_brace_words`/:func:`expand_braces`, their own
    spelling/depth caps) and nested `-c`/`eval`/process-substitution
    re-parsing (``_MAX_NESTED_SHELL_DEPTH``/``_MAX_NESTED_SHELL_BYTES``
    below) are unchanged -- those are the loci where a small input really
    can expand into disproportionate work, which a flat word scan is not.

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
        command, max_words=max_words, depth=0, remaining_bytes=remaining_bytes, deadline=deadline
    )


def _recurse_into_nested_command(
    text: str,
    *,
    max_words: int,
    depth: int,
    remaining_bytes: list[int],
    deadline: float | None,
) -> Iterator[str]:
    """Shared recursion entry point for every nested-command trigger in
    :func:`_iter_normalised_shell_words` -- one place enforcing both
    bounds identically, and failing CLOSED (raising) past either: "cannot
    rule out a protected path" must never be conflated with "no protected
    path" (this module's existing doctrine for
    :func:`expand_braces`/:func:`bounded_recursive_glob`). ``deadline`` is
    forwarded, not re-armed, so a chain of nested re-parses shares the
    SAME clock as the flat scan around it (review 7 follow-up).
    """
    if depth >= _MAX_NESTED_SHELL_DEPTH:
        raise TooManyToEnumerateError("nested shell re-parsing exceeded its depth bound")
    if remaining_bytes[0] <= 0:
        raise TooManyToEnumerateError("nested shell re-parsing exceeded its byte budget")
    if deadline is not None and time.monotonic() > deadline:
        raise TimeoutError("nested shell re-parsing exceeded its deadline")
    remaining_bytes[0] -= min(len(text), remaining_bytes[0])
    yield from _iter_normalised_shell_words(
        text,
        max_words=max_words,
        depth=depth + 1,
        remaining_bytes=remaining_bytes,
        deadline=deadline,
    )


#: How many words pass between ``deadline`` checks -- cheap enough
#: (``time.monotonic()`` is a handful of nanoseconds) to check every word,
#: but batched anyway so the per-word cost stays dominated by the actual
#: decode work, not clock reads, on the common case where ``deadline`` is
#: still comfortably far off.
_DEADLINE_CHECK_INTERVAL: Final[int] = 200


def _iter_normalised_shell_words(
    command: str,
    *,
    max_words: int,
    depth: int,
    remaining_bytes: list[int],
    deadline: float | None,
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

    # `ssh [options] [user@]TARGET [COMMAND...]` -- looking for TARGET to
    # decide whether COMMAND (an eval-style joined trailing argument list)
    # is executed on THIS machine (review 7 follow-up).
    scanning_ssh_target = False
    ssh_awaiting_value = False

    # `eval`/a process substitution's content/`echo|printf ... | <shell>`
    # word-joining.
    collecting_words: list[str] | None = None
    # "eval" | "procsub" | "source_procsub" | "pipe_echo" | "output_procsub"
    # ("source_procsub" is review 7 follow-up; the rest are review 7 MAJOR-3)
    collecting_purpose: str | None = None
    collecting_head: str | None = None  # the trigger word, for echo/printf decode

    # `echo|printf '...' | <shell>` -- content captured, looking for the
    # pipeline stage that actually consumes it.
    pipe_content: str | None = None
    pipe_stage_awaiting_head = False
    pipe_stage_passthrough = False  # inside a `tee` stage; content survives it
    # Review 7 follow-up (gd6_shell2 residual): `pipe_content` passed
    # through an UNRECOGNISED stage (`base64 -d`, `openssl enc -d`, any
    # command that is not a known wrapper/shell/passthrough) -- the
    # content is no longer reliable (the unrecognised stage may have
    # transformed it into anything), so it is kept PENDING rather than
    # silently dropped: if a shell interpreter is later reached while this
    # is set, that is "known producer content reached a shell through an
    # opaque transform we cannot see through" and fails CLOSED, rather
    # than the prior silent drop (a genuine fail-open this review found:
    # `echo BASE64 | base64 -d | bash`).
    pipe_content_opaque = False
    # Walking an unrecognised stage's OWN trailing words (`base64 -d`) --
    # mirrors `pipe_stage_passthrough`'s own multi-word tracking, since an
    # unrecognised command's flags are not in any known option table.
    scanning_opaque_stage = False
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
        char = command[i]
        if char in _WORD_SEPARATOR_CHARS:
            if char not in " \t\n":
                last_operators += char
            i += 1
            continue
        # Review 7 follow-up (team-lead, superseding review 7 MAJOR-1's
        # word-COUNT cap): flat per-word decoding is linear cost, so it is
        # bounded by TIME, not by how many words happen to be in the
        # command -- checked every `_DEADLINE_CHECK_INTERVAL` words so an
        # ordinary long command (a plan document, a long commit message, a
        # large source file) never trips a volume wall a real shell never
        # would either. A heredoc body's words are still decoded and
        # yielded exactly like any other word's, unaffected by this check.
        if (
            deadline is not None
            and count % _DEADLINE_CHECK_INTERVAL == 0
            and time.monotonic() > deadline
        ):
            raise TimeoutError("normalised shell word scan exceeded its deadline")

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
                nested_body,
                max_words=max_words,
                depth=depth,
                remaining_bytes=remaining_bytes,
                deadline=deadline,
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
        if (
            scanning_interpreter_options
            and scanning_tolerant
            and any(ch in _COMMAND_TERMINATOR_CHARS for ch in this_word_operators)
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
                pipe_content_opaque = False
        if scanning_opaque_stage and is_terminator_next:
            scanning_opaque_stage = False
            pipe_stage_awaiting_head = stop_char == _PIPE_OPERATOR
            if not pipe_stage_awaiting_head:
                pipe_content = None
                pipe_content_opaque = False

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
                opaque = pipe_content_opaque
                pipe_content_opaque = False
                if opaque:
                    # Review 7 follow-up: known producer content reached
                    # this shell through an unrecognised intermediate
                    # transform (e.g. `base64 -d`) -- the actual bytes the
                    # shell receives cannot be verified, so this fails
                    # CLOSED (raises) rather than recursing into a
                    # possibly-stale `content` and answering "no mention".
                    raise TooManyToEnumerateError(
                        "pipe content reached a shell through an unrecognised "
                        "intermediate transform -- cannot rule out a protected path"
                    )
                yield from _recurse_into_nested_command(
                    content or "",
                    max_words=max_words,
                    depth=depth,
                    remaining_bytes=remaining_bytes,
                    deadline=deadline,
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
                        pipe_content_opaque = False
            elif pipe_content is not None:
                # Review 7 follow-up: an UNRECOGNISED stage (not a
                # wrapper, shell or passthrough) sits between known
                # producer content and whatever comes next -- the content
                # is kept PENDING (opaque) rather than dropped, so a
                # LATER shell stage in the SAME pipeline still fails
                # closed on it, instead of the prior silent drop.
                # `scanning_opaque_stage` (mirrors `pipe_stage_
                # passthrough`) tracks this stage's OWN trailing words
                # (`base64 -d`'s `-d`) since an unrecognised command's
                # flags are not in any known option table; the 0b check
                # above resolves it exactly like a passthrough stage once
                # its last word is reached.
                pipe_content_opaque = True
                scanning_opaque_stage = True
                if is_terminator_next:
                    scanning_opaque_stage = False
                    pipe_stage_awaiting_head = stop_char == _PIPE_OPERATOR
                    if not pipe_stage_awaiting_head:
                        pipe_content = None
                        pipe_content_opaque = False
                # else: more words in this SAME unrecognised stage follow
                # (`base64 -d`'s `-d`) -- state stays as set above,
                # resolved by the `scanning_opaque_stage` check in 0b once
                # this stage's LAST word is reached.
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
                    decoded,
                    max_words=max_words,
                    depth=depth,
                    remaining_bytes=remaining_bytes,
                    deadline=deadline,
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
                decoded,
                max_words=max_words,
                depth=depth,
                remaining_bytes=remaining_bytes,
                deadline=deadline,
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
                    decoded,
                    max_words=max_words,
                    depth=depth,
                    remaining_bytes=remaining_bytes,
                    deadline=deadline,
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

        # 2c. Walking `ssh`'s OWN options, looking for its TARGET argument
        #     (review 7 follow-up) -- once found, a LOOPBACK target means
        #     everything after it is an eval-style joined command executed
        #     on THIS machine; any other target is a genuine remote host
        #     and nothing further is done (the rest is scanned as
        #     ordinary words, same as before this fix).
        if scanning_ssh_target:
            if ssh_awaiting_value:
                ssh_awaiting_value = False
                previous_word = decoded
                continue
            if decoded in _SSH_SHORT_VALUE_FLAGS:
                ssh_awaiting_value = True
                previous_word = decoded
                continue
            if decoded.startswith("-"):
                # A plain flag (`-4`, `-A`, ...) or an unrecognised one
                # (best-effort: fails toward NOT recursing, see above).
                previous_word = decoded
                continue
            scanning_ssh_target = False
            target = decoded.rsplit("@", 1)[-1]
            if target in _SSH_LOOPBACK_HOSTS:
                collecting_words = []
                collecting_purpose = "eval"
                collecting_head = None
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
                    deadline=deadline,
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
                    decoded,
                    max_words=max_words,
                    depth=depth,
                    remaining_bytes=remaining_bytes,
                    deadline=deadline,
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
                    decoded,
                    max_words=max_words,
                    depth=depth,
                    remaining_bytes=remaining_bytes,
                    deadline=deadline,
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
                head = collecting_head
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
                    elif depth > 0:
                        # Review 7 follow-up (gd6_shell2 residual): a bare
                        # `echo`/`printf` INSIDE a nested substitution
                        # (`$(...)`, an `eval` argument, a process
                        # substitution) is unconditionally EXECUTED by the
                        # shell to produce its output -- that is what
                        # command substitution means -- and the produced
                        # text commonly becomes CODE for an outer `-c`/
                        # `eval` context (a `bash -c` or `eval` argument
                        # built entirely from one such substitution) that
                        # this forward, single-pass parser cannot see from
                        # inside the substitution body itself. Recursing
                        # into the resolved text as its own command
                        # reveals a mention hidden behind exactly this
                        # "the shell re-parses the produced text as
                        # source" shape -- the same second-parse-reveal
                        # mechanism a nested `-c`/`eval` argument already
                        # gets, and the same "fail toward denying more"
                        # trade-off MAJOR-2 already makes for `$(...)`
                        # bodies themselves.
                        #
                        # Scoped to `depth > 0` (inside a substitution)
                        # specifically so a plain TOP-LEVEL echo of some
                        # arbitrary text -- a harmless PRINT with nothing
                        # consuming its output -- is not recursed into and
                        # denied: that command never executes what it
                        # prints.
                        yield from _recurse_into_nested_command(
                            joined,
                            max_words=max_words,
                            depth=depth,
                            remaining_bytes=remaining_bytes,
                            deadline=deadline,
                        )
                    # else: top-level (depth == 0), not piped/redirected --
                    # no recursion; the words were already scanned
                    # individually above, and nothing executes this text.
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
                        joined,
                        max_words=max_words,
                        depth=depth,
                        remaining_bytes=remaining_bytes,
                        deadline=deadline,
                    )
                    if fed_content:
                        yield from _recurse_into_nested_command(
                            fed_content,
                            max_words=max_words,
                            depth=depth,
                            remaining_bytes=remaining_bytes,
                            deadline=deadline,
                        )
                else:
                    # `purpose` is "eval", "procsub" or "source_procsub"
                    # here. For "eval", `joined` genuinely BECOMES the
                    # executed command, so recursing into it is exact, not
                    # a heuristic. For a plain "procsub" (`diff <(...)`,
                    # `bash <(...)`, any consumer other than `source`/`.`),
                    # the substitution is a DATA file-like argument, and
                    # scanning its own command text (the existing,
                    # unaffected behaviour) is the right level.
                    #
                    # For "source_procsub" (`source <(PRODUCER)`), the
                    # producer is classified by `head` (its OWN command
                    # name, never `joined` -- for a literal producer,
                    # `joined` is already its RESOLVED OUTPUT, i.e. DATA,
                    # not a command to classify). Review 6 MAJOR-2's
                    # default (scan the producer's own text, deny only if
                    # THAT mentions a protected path) is kept for every
                    # producer except the narrow OPAQUE-TRANSFORM set
                    # (base64/openssl/gzip-family decoders): those can
                    # turn ANY payload into the sourced script, and
                    # scanning the DECODER's own invocation can never
                    # reveal what it decodes TO -- review 7 follow-up
                    # (gd6_shell2 residual).
                    head_basename = _interpreter_basename(head or "")
                    if (
                        purpose == "source_procsub"
                        and head_basename in _OPAQUE_SOURCE_TRANSFORM_BASENAMES
                    ):
                        raise TooManyToEnumerateError(
                            "source <(...) fed by an opaque encode/decode transform "
                            "-- cannot rule out a protected path"
                        )
                    yield from _recurse_into_nested_command(
                        joined,
                        max_words=max_words,
                        depth=depth,
                        remaining_bytes=remaining_bytes,
                        deadline=deadline,
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
                    decoded,
                    max_words=max_words,
                    depth=depth,
                    remaining_bytes=remaining_bytes,
                    deadline=deadline,
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
            # Review 7 follow-up: a process substitution fed to `source`/
            # `.` becomes a SCRIPT that is executed -- its producer's
            # OUTPUT matters, not just its own command text (see the
            # "source_procsub" handling below). Any OTHER consumer
            # (`diff <(...)`, `bash <(...)`, a plain argument) treats the
            # substitution as a DATA file-like argument, unaffected.
            collecting_purpose = (
                "source_procsub" if previous_word in _SOURCE_COMMAND_NAMES else "procsub"
            )
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
            pipe_content_opaque = False
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
        elif basename in _SSH_BASENAMES:
            scanning_ssh_target = True

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
                joined,
                max_words=max_words,
                depth=depth,
                remaining_bytes=remaining_bytes,
                deadline=deadline,
            )
            if pending_output_procsub_content:
                yield from _recurse_into_nested_command(
                    pending_output_procsub_content,
                    max_words=max_words,
                    depth=depth,
                    remaining_bytes=remaining_bytes,
                    deadline=deadline,
                )
        elif collecting_purpose != "pipe_echo":
            # A `pipe_echo` collection ending at end-of-string was never
            # piped/redirected to anything -- its words were already
            # scanned individually, matching the mid-command behaviour.
            # (This is the rare zero-word-collected edge case -- a real
            # `source_procsub` producer text with actual words to judge
            # is always resolved by the mid-loop branch above, since
            # `is_terminator_next` already accounts for end-of-string.)
            end_head_basename = _interpreter_basename(collecting_head or "")
            if (
                collecting_purpose == "source_procsub"
                and end_head_basename in _OPAQUE_SOURCE_TRANSFORM_BASENAMES
            ):
                raise TooManyToEnumerateError(
                    "source <(...) fed by an opaque encode/decode transform "
                    "-- cannot rule out a protected path"
                )
            yield from _recurse_into_nested_command(
                joined,
                max_words=max_words,
                depth=depth,
                remaining_bytes=remaining_bytes,
                deadline=deadline,
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
    errors: list[OSError] | None = None,
    skip_hidden: bool = False,
) -> Iterator[Path]:
    """Lazily yield paths under ``base`` matching ``pattern`` (which may
    contain a recursive ``**`` component), bounded by entries VISITED.

    ``skip_hidden`` follows bash's default: a wildcard or ``**`` component
    does not match an entry whose name starts with ``.`` unless the pattern
    component itself starts with ``.``. Off by default, so every other caller
    still sees dot-entries.

    A pattern rooted at the filesystem root (``base`` is itself an anchor,
    e.g. ``Path("/")``) whose leading non-wildcard components name an
    existing directory is walked from THAT directory (``/tmp/x/*/*`` is a
    walk of ``/tmp/x``, not of ``/``); a prefix that resolves back to the
    root (``/usr/..``, a symlink to ``/``) narrows nothing. Only a walk that
    still starts at the root is refused. It is refused outright, without
    attempting to walk at all, whenever it carries a recursive ``**``
    component OR two or more
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

    The walk goes one pattern component at a time (``_GlobWalk``). A failed
    lookup that proves nothing about the target (permission denied, an I/O
    error, a joined path past PATH_MAX) is an error. With ``errors=None``
    the first such error propagates. With a list, it is appended and every
    other branch is still walked, so one bad sibling cannot hide the rest;
    the caller then decides (Plan 00466 N101 round 9).
    """
    parts = [part for part in pattern.split("/") if part]
    is_root = bool(base.anchor) and str(base) == base.anchor
    if is_root and not _literal_prefix_exists(base, pattern):
        # The pattern's leading non-wildcard components name a path that is
        # not there, so nothing can match and there is nothing to walk.
        return
    if is_root:
        literal = _leading_literal_parts(parts)
        narrowed = base.joinpath(*literal)
        if literal and not _is_filesystem_root(narrowed):
            # An existing literal prefix confines the walk to that one
            # directory (GitHub #68). The refusal below judges a walk that
            # starts at the root, so it is not applied to this one.
            base, parts, is_root = narrowed, parts[len(literal) :], False
    if is_root:
        wildcard_segments = sum(1 for segment in parts if _is_glob_component(segment))
        if _RECURSIVE_MARKER in pattern or wildcard_segments >= 2:
            raise TooManyToEnumerateError(
                f"refusing to walk a broad glob rooted at the filesystem root: {base}/{pattern}"
            )
    walk = _GlobWalk(
        parts=parts,
        errors=errors,
        # A pattern with no `**` lists at most one directory per literal
        # prefix, which bounds its own cost; only a recursive walk is capped.
        max_entries_visited=max_entries_visited if _RECURSIVE_MARKER in pattern else None,
        deadline=deadline,
        skip_hidden=skip_hidden,
    )
    if walk.parts:
        yield from walk.select(base, 0)


def _leading_literal_parts(parts: list[str]) -> list[str]:
    """The components before the first wildcard, when a wildcard follows them.

    A pattern with no wildcard at all names one path and has no prefix to
    narrow: its last component is looked up as the target, not as a directory.
    """
    literal: list[str] = []
    for part in parts:
        if _is_glob_component(part):
            return literal
        literal.append(part)
    return []


def _is_filesystem_root(path: Path) -> bool:
    """Whether ``path`` is the filesystem root once ``..`` and symlinks are resolved."""
    real = os.path.realpath(path)
    return real == os.path.realpath(path.anchor)


def _literal_prefix_exists(base: Path, pattern: str) -> bool:
    """Whether the leading non-wildcard components of ``pattern`` exist under ``base``.

    ``True`` when the pattern has no literal prefix (it starts with a
    wildcard) or when the prefix is there. Only a lookup that proves absence
    (``ENOENT``/``ENOTDIR``/``ELOOP``) answers ``False``; any other failure,
    including a joined path past PATH_MAX that the relative word may not
    have exceeded, answers ``True`` so the walk itself decides and reports
    it (fail closed).
    """
    prefix_parts: list[str] = []
    for part in pattern.split("/"):
        if not part:
            continue
        if _is_glob_component(part):
            break
        prefix_parts.append(part)
    if not prefix_parts:
        return True
    try:
        base.joinpath(*prefix_parts).stat()
    except OSError as exc:
        return exc.errno not in _ABSENT_ERRNOS
    return True


#: ``OSError`` numbers that prove a looked-up path does not exist, so no
#: shell naming it can read anything through it. They are the lookups
#: pathlib's own glob ignored.
_ABSENT_ERRNOS: Final[frozenset[int]] = frozenset({errno.ENOENT, errno.ENOTDIR, errno.ELOOP})

#: ``OSError`` numbers for a lookup the caller may not make: the path's
#: existence is hidden, but its NAME is whatever was asked for.
_UNSEARCHABLE_ERRNOS: Final[frozenset[int]] = frozenset({errno.EACCES, errno.EPERM})

#: Name limit assumed when the filesystem cannot be asked (``PC_NAME_MAX``).
_FALLBACK_NAME_MAX: Final[int] = 255


def _name_max(directory: Path) -> int:
    """The longest entry name ``directory``'s filesystem allows."""
    try:
        limit = os.pathconf(directory, "PC_NAME_MAX")
    except (OSError, ValueError) as exc:
        logger.debug("shell_expansion: no PC_NAME_MAX for %r: %s", directory, exc)
        return _FALLBACK_NAME_MAX
    return limit if limit > 0 else _FALLBACK_NAME_MAX


def _is_glob_component(part: str) -> bool:
    return any(char in part for char in "*?[")


@dataclass
class _GlobWalk:
    """One glob walk: its pattern components and its per-call bookkeeping."""

    parts: list[str]
    errors: list[OSError] | None
    max_entries_visited: int | None
    deadline: float | None
    skip_hidden: bool = False
    visited: int = 0
    listings: dict[Path, list[os.DirEntry[str]]] = field(default_factory=dict)

    def select(self, directory: Path, index: int) -> Iterator[Path]:
        """Paths under ``directory`` matching ``parts[index:]``."""
        part = self.parts[index]
        last = index == len(self.parts) - 1
        if part == _RECURSIVE_MARKER:
            yield from self._select_recursive(directory, index, last)
        elif _is_glob_component(part):
            yield from self._select_wildcard(directory, index, last)
        else:
            yield from self._select_literal(directory, index, last)

    def _select_literal(self, directory: Path, index: int, last: bool) -> Iterator[Path]:
        # Bash opens a literal component by name, so the lookup is the
        # same one the shell makes (apart from the base prefix).
        part = self.parts[index]
        candidate = directory / part
        try:
            status = candidate.lstat() if last else candidate.stat()
        except OSError as exc:
            if (
                exc.errno in _UNSEARCHABLE_ERRNOS
                and self._reached_by_wildcard(index)
                and self._names_one_path(index)
            ):
                # A sibling the wildcard selected, which this process cannot
                # search, hides whether the path exists, not what it is
                # called. The remaining components are all literal, so the
                # path is fully named: yield it for the caller to judge by
                # name, exactly as for a readable one, instead of failing the
                # whole walk on it. A path the word itself names outright
                # that cannot be looked up stays an error.
                yield directory.joinpath(*self.parts[index:])
            else:
                self._record(exc, directory, part)
        else:
            if last:
                yield candidate
            elif stat.S_ISDIR(status.st_mode):
                yield from self.select(candidate, index + 1)

    def _reached_by_wildcard(self, index: int) -> bool:
        """Whether a wildcard component chose the directory ``parts[index]`` is in."""
        return any(_is_glob_component(part) for part in self.parts[:index])

    def _names_one_path(self, index: int) -> bool:
        """Whether ``parts[index:]`` holds only literal components."""
        return not any(_is_glob_component(part) for part in self.parts[index:])

    def _select_wildcard(self, directory: Path, index: int, last: bool) -> Iterator[Path]:
        # A wildcard component is matched against the directory's entries;
        # bash never opens it, so its own length proves nothing.
        part = self.parts[index]
        for entry in self._list(directory):
            if self.skip_hidden and entry.name.startswith(".") and not part.startswith("."):
                continue
            if not fnmatch.fnmatchcase(entry.name, part):
                continue
            if last:
                yield Path(entry.path)
            elif self._is_dir(entry, follow_symlinks=True):
                yield from self.select(Path(entry.path), index + 1)

    def _select_recursive(self, directory: Path, index: int, last: bool) -> Iterator[Path]:
        # `**` stands for zero or more directories (a superset of bash's
        # own reading, with or without globstar). Huge or ignored trees
        # are not descended into.
        if not last:
            yield from self.select(directory, index + 1)
        for entry in self._list(directory):
            if self.skip_hidden and entry.name.startswith("."):
                continue
            if last:
                yield Path(entry.path)
            if entry.name in _PRUNED_DIR_NAMES:
                continue
            if self._is_dir(entry, follow_symlinks=False):
                yield from self._select_recursive(Path(entry.path), index, last)

    def _list(self, directory: Path) -> list[os.DirEntry[str]]:
        # A `**` walk reaches each directory twice (as zero directories
        # and as a descent), so each listing is read and counted once.
        cached = self.listings.get(directory)
        if cached is not None:
            return cached
        entries = self._scan(directory)
        self.listings[directory] = entries
        for _entry in entries:
            if self.deadline is not None and time.monotonic() > self.deadline:
                raise TimeoutError("bounded_recursive_glob exceeded its deadline")
            if self.max_entries_visited is not None:
                self.visited += 1
                if self.visited > self.max_entries_visited:
                    raise TooManyToEnumerateError(
                        f"glob walk under {directory} exceeded "
                        f"{self.max_entries_visited} entries visited"
                    )
        return entries

    def _scan(self, directory: Path) -> list[os.DirEntry[str]]:
        """The directory's entries. One that cannot be listed has none, and
        its error has gone through ``_record``: skipped as proof of absence,
        raised, or collected for the caller to deny on."""
        try:
            return list(os.scandir(directory))
        except OSError as exc:
            self._record(exc, directory, None)
        return []

    def _is_dir(self, entry: os.DirEntry[str], *, follow_symlinks: bool) -> bool:
        try:
            return entry.is_dir(follow_symlinks=follow_symlinks)
        except OSError as exc:
            self._record(exc, Path(entry.path).parent, entry.name)
            return False

    def _record(self, exc: OSError, directory: Path, component: str | None) -> None:
        """Skip a lookup that proves absence; otherwise record or raise.

        ENAMETOOLONG proves absence only when the component bash would
        open is longer than the filesystem's name limit. A joined path past
        PATH_MAX is a fact about this walk's base, not about the target:
        bash, opening the relative word, can still read it.
        """
        if exc.errno in _ABSENT_ERRNOS:
            logger.debug("shell_expansion: %r under %r is absent: %s", component, directory, exc)
            return
        if (
            exc.errno == errno.ENAMETOOLONG
            and component is not None
            and len(os.fsencode(component)) > _name_max(directory)
        ):
            logger.debug("shell_expansion: %r is longer than any name can be", component)
            return
        if self.errors is None:
            raise exc
        self.errors.append(exc)
