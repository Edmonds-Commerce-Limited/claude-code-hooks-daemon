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
    for alternative in match.group(1).split(","):
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
