"""Shared glob-based path exclusion for content-scanning blocking handlers.

Client projects — especially QA/linting libraries whose job is to contain
deliberately-"bad" code samples — need to exempt paths from the content
blockers (`security_antipattern`, `qa_suppression`, `error_hiding_blocker`).
This module provides one glob matcher those handlers share, so exclusion
behaves identically everywhere.

Glob semantics are a pragmatic gitignore-style subset (stdlib-only, no runtime
dependency):

- ``*``  matches any run of characters within a single path segment.
- ``?``  matches exactly one character within a single path segment.
- ``**`` matches any number of path segments (including zero), e.g.
  ``samples/**/*.py`` matches both ``samples/x.py`` and ``samples/a/b/x.py``.
- A leading ``/`` anchors the pattern to the project root; without it the
  pattern may match at any directory depth.

Patterns are matched against the project-relative path (when ``project_root``
is given and the file lives under it) and against the raw path, so a handler
may pass either an absolute or a relative ``file_path``.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple, Protocol

from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.utils.vendor_paths import VENDOR_DIRS_TOKEN, is_vendored_path


class VendoredPathJudge(Protocol):
    """Structural view of the one method this module needs from a layout.

    A ``Protocol`` rather than an import: ``ProjectLayout`` lives in ``core``
    and this module is deliberately stdlib-only (see the module docstring),
    so importing the facade would couple every exclusion caller to ``core``.
    ``ProjectLayout`` satisfies this structurally, with nothing to declare.
    """

    def is_vendored_path(self, rel_path: str) -> bool: ...


def _resolves_vendor_token(file_path: str, layout: VendoredPathJudge | None) -> bool:
    """Whether ``file_path`` is vendored, for a ``{vendor-dirs}`` entry.

    With no layout available the effective vendor set is the built-in one,
    which is the same fallback :func:`vendored_exclude_globs` already makes
    for a ``None`` ``vendor_dirs`` -- consistent rather than a special case.
    """
    if layout is not None:
        return layout.is_vendored_path(file_path)
    return is_vendored_path(file_path, CORE_VENDORED_BUILD_DIR_NAMES)


# Plan 00466 n24 security review, B2: this used to translate a glob into a
# regex string and match it with `compiled.fullmatch(candidate)`. Against an
# adversarial `file_path` built from many short segments (`"a/" * n`), the
# backtracking regex engine went quadratic-or-worse AND held the GIL for the
# whole call -- no other thread could run meanwhile, so nothing bounding the
# call (not even a timed wait) could observe or interrupt it. Measured: 1.9s
# at 4000 segments, unbounded growth from there; a single Write with a ~90KB
# `file_path` froze the daemon outright. Replaced with a hand-written matcher
# below: each pattern is tokenized once (cached), and matching is a single
# left-to-right sweep per token over a "reachable position" boolean array --
# provably O(len(text) * token_count), no backtracking possible.


class _Token(NamedTuple):
    """One piece of a tokenized glob pattern.

    ``kind`` is one of ``PREFIX`` (the unanchored ``(?:.*/)?`` prefix,
    always first and only ever present once), ``LITSTR`` (a run of literal
    characters, using ``literal``), ``QMARK`` (``?``), ``STAR`` (a
    single-segment ``*``), ``SEGSTAR`` (a mid-pattern ``**/``), or
    ``ANYALL`` (a trailing/bare ``**``).
    """

    kind: str
    literal: str = ""


# Tokenized-pattern cache: the same handful of client globs are matched on
# every Write/Edit, so tokenizing once per pattern is worth it -- mirrors the
# old `_REGEX_CACHE`'s intent, just caching tokens instead of a compiled regex.
_TOKEN_CACHE: dict[str, list[_Token]] = {}


def _tokenize_glob(pattern: str) -> list[_Token]:
    """Tokenize a gitignore-style glob for the linear matcher below.

    A leading ``/`` anchors to the (relative) path start; otherwise a
    ``PREFIX`` token (the ``(?:.*/)?`` prefix) lets the pattern match at any
    directory depth. Consecutive literal characters (including ``/``) are
    merged into one ``LITSTR`` token so a long literal run (e.g.
    ``node_modules``) costs one sweep, not one per character.
    """
    anchored = pattern.startswith("/")
    body = pattern[1:] if anchored else pattern

    tokens: list[_Token] = []
    if not anchored:
        tokens.append(_Token("PREFIX"))

    literal_buf: list[str] = []

    def flush_literal() -> None:
        if literal_buf:
            tokens.append(_Token("LITSTR", "".join(literal_buf)))
            literal_buf.clear()

    i = 0
    n = len(body)
    while i < n:
        char = body[i]
        if char == "*":
            if i + 1 < n and body[i + 1] == "*":
                # '**' — any number of path segments.
                i += 2
                flush_literal()
                if i < n and body[i] == "/":
                    # '**/' consumes the slash so it can match zero segments.
                    i += 1
                    tokens.append(_Token("SEGSTAR"))
                else:
                    tokens.append(_Token("ANYALL"))
                continue
            flush_literal()
            tokens.append(_Token("STAR"))
        elif char == "?":
            flush_literal()
            tokens.append(_Token("QMARK"))
        else:
            literal_buf.append(char)
        i += 1
    flush_literal()
    return tokens


def _tokens_for(pattern: str) -> list[_Token]:
    """Return the cached token list for ``pattern``."""
    tokens = _TOKEN_CACHE.get(pattern)
    if tokens is None:
        tokens = _tokenize_glob(pattern)
        _TOKEN_CACHE[pattern] = tokens
    return tokens


def _apply_prefix(text: str) -> list[bool]:
    """Reachability after the unanchored ``(?:.*/)?`` prefix.

    Always the first token, applied to the fixed initial state
    ``{0: True}`` (nothing else can be reachable before the first token
    runs), so it is computed directly from ``text`` rather than taking a
    ``reachable`` argument. ``.`` does not match ``\\n`` (regex default,
    no ``DOTALL``), and since this is a single optional occurrence — not a
    starred/repeated group — a ``\\n`` anywhere permanently ends the run: no
    later ``/`` can complete it.

    Every ``/`` up to that point (if any) lands a reachable position, so this
    walks ``/`` occurrences with ``str.find`` (a C-level scan) rather than a
    Python-level loop over every character — the same total work, done far
    faster in practice.
    """
    n = len(text)
    new_reachable = [False] * (n + 1)
    new_reachable[0] = True
    newline_at = text.find("\n")
    limit = newline_at if newline_at != -1 else n
    pos = text.find("/", 0, limit)
    while pos != -1:
        new_reachable[pos + 1] = True
        pos = text.find("/", pos + 1, limit)
    return new_reachable


def _apply_literal(reachable: list[bool], text: str, literal: str) -> list[bool]:
    """Reachability after consuming an exact literal run.

    Exact string comparison, not regex — so no escaping is needed and no
    character in ``literal`` gets special meaning.

    Drives the scan from ``str.find`` (a C-level substring search) rather
    than checking every position for ``reachable[j]`` first: a literal like
    ``node_modules`` is typically ABSENT from the candidate text entirely,
    and ``find`` returning "not found" costs one fast C-level scan rather
    than up to ``len(text)`` Python-level slice comparisons.
    """
    n = len(text)
    ln = len(literal)
    new_reachable = [False] * (n + 1)
    limit = n - ln
    if limit < 0:
        return new_reachable
    pos = text.find(literal)
    while pos != -1 and pos <= limit:
        if reachable[pos]:
            new_reachable[pos + ln] = True
        pos = text.find(literal, pos + 1)
    return new_reachable


def _apply_qmark(reachable: list[bool], text: str) -> list[bool]:
    """Reachability after consuming exactly one non-``/`` character (``?``)."""
    n = len(text)
    new_reachable = [False] * (n + 1)
    for j in range(n):
        if reachable[j] and text[j] != "/":
            new_reachable[j + 1] = True
    return new_reachable


def _apply_star(reachable: list[bool], text: str, *, exclude_char: str) -> list[bool]:
    """Reachability after a zero-or-more wildcard that cannot cross ``exclude_char``.

    Shared by ``STAR`` (``[^/]*``, ``exclude_char="/"``) and ``ANYALL``
    (``.*``, ``exclude_char="\\n"`` — regex ``.`` excludes only newline).

    ``text`` splits into runs bounded by ``exclude_char`` occurrences; within
    a run, reachability can only ever *start* at the first ``True`` input
    position and then holds for the rest of the run (once reachable, a
    zero-or-more wildcard can always choose to consume one more character
    up to the boundary). So each run needs only: locate its first ``True``
    input position and, if one exists, fill from there to the run's end in
    one C-level slice-assignment — cheaper than a Python-level loop over
    every character.
    """
    n = len(text)
    new_reachable = [False] * (n + 1)
    lo = 0
    pos = text.find(exclude_char)
    while True:
        hi = pos if pos != -1 else n  # run is [lo, hi], inclusive of the boundary index itself
        run = reachable[lo : hi + 1]
        if True in run:
            first_true = lo + run.index(True)
            new_reachable[first_true : hi + 1] = [True] * (hi + 1 - first_true)
        if pos == -1:
            break
        lo = pos + 1
        pos = text.find(exclude_char, lo)
    return new_reachable


def _apply_segstar(reachable: list[bool], text: str) -> list[bool]:
    """Reachability after ``(?:[^/]+/)*`` — zero or more COMPLETE segments.

    Each repeat needs at least one non-``/`` character before its ``/``; a
    naive ``.*``-style linearization would wrongly let ``**/secret`` match
    a bare ``xsecret`` (treating "x" as an admissible empty-ish prefix), so
    this tracks two flags across a single sweep instead:

    - ``armed``: a segment MAY start at the current position, but has not
      yet consumed a character (set by a reachable input position, or by
      just landing right after a completed segment's ``/``).
    - ``open``: a segment has consumed at least one non-``/`` character and
      is eligible to complete the moment a ``/`` is seen.

    A ``/`` only completes (and records a new reachable position) when
    ``open`` is True; an ``armed``-but-not-``open`` position hitting a
    ``/`` immediately is a zero-length segment attempt and is discarded
    (``armed`` resets, nothing recorded) — this is what keeps ``**/`` from
    matching across an empty segment.
    """
    n = len(text)
    new_reachable = list(reachable)  # zero repeats: every input position stays reachable.
    armed = False
    open_ = False
    for j in range(n):
        if reachable[j]:
            armed = True
        if text[j] == "/":
            if open_:
                new_reachable[j + 1] = True
                open_ = False
                armed = True
            else:
                armed = False
        else:
            if armed or open_:
                open_ = True
                armed = False
    return new_reachable


def _glob_fullmatch(
    pattern: str, text: str, *, step_cache: dict[tuple[object, ...], list[bool]] | None = None
) -> bool:
    """Whether ``text`` fully matches ``pattern``, in this module's glob dialect.

    Linear in ``len(text)``: each token in the (cached) tokenized pattern is
    applied in one left-to-right sweep over a "reachable position" array,
    with no backtracking possible.

    ``step_cache`` is an optional cross-pattern memo, scoped to one
    :func:`path_matches_globs` call: every ``_apply_*`` step is a pure
    function of ``(token, input reachable, text)``, and a realistic exclude
    list is mostly ``**/<name>/**`` patterns that all share the identical
    ``PREFIX``/``SEGSTAR`` prefix and diverge only at the literal name —
    (error_hiding_blocker's own defaults are 14 such patterns). Without this,
    every pattern repeats that shared prefix's O(len(text)) work from
    scratch. Keyed by ``id()`` of the input reachable array rather than its
    value: safe only because the cache and the arrays it references share
    this call's lifetime, so no id can be reused by an unrelated object
    while the cache is live.
    """
    tokens = _tokens_for(pattern)
    n = len(text)
    reachable = [False] * (n + 1)
    reachable[0] = True
    for token in tokens:
        cached = None
        cache_key: tuple[object, ...] | None = None
        if step_cache is not None:
            cache_key = (
                ("PREFIX", id(text)) if token.kind == "PREFIX" else (token, id(reachable), id(text))
            )
            cached = step_cache.get(cache_key)
        if cached is not None:
            reachable = cached
        else:
            if token.kind == "PREFIX":
                reachable = _apply_prefix(text)
            elif token.kind == "LITSTR":
                reachable = _apply_literal(reachable, text, token.literal)
            elif token.kind == "QMARK":
                reachable = _apply_qmark(reachable, text)
            elif token.kind == "STAR":
                reachable = _apply_star(reachable, text, exclude_char="/")
            elif token.kind == "ANYALL":
                reachable = _apply_star(reachable, text, exclude_char="\n")
            else:  # SEGSTAR
                reachable = _apply_segstar(reachable, text)
            if step_cache is not None and cache_key is not None:
                step_cache[cache_key] = reachable
        if True not in reachable:
            return False
    return reachable[n]


def _candidate_paths(file_path: str, project_root: str | os.PathLike[str] | None) -> list[str]:
    """Return the path strings a pattern is matched against.

    Always includes the raw path with any leading slash stripped; also includes
    the project-relative path when ``project_root`` is given and the file lives
    under it (so leading-``/`` anchored patterns resolve against the root).
    """
    raw = file_path.replace("\\", "/")
    candidates = [raw.lstrip("/")]
    if project_root is not None:
        root = str(project_root).replace("\\", "/")
        rel = os.path.relpath(raw, root).replace("\\", "/")
        if rel != ".." and not rel.startswith("../"):
            candidates.insert(0, rel)
    return candidates


def vendored_exclude_globs(vendor_dirs: Iterable[str] | None = None) -> tuple[str, ...]:
    """Vendored/build directory NAMES as ``**/<name>/**`` exclusion globs.

    Three content blockers (``comment_size``, ``comment_changelog``,
    ``error_hiding_blocker``) each built this identical tuple at module
    scope from :data:`CORE_VENDORED_BUILD_DIR_NAMES`. Computing it at import
    time froze it to the BUILT-IN names, so a project's declared
    ``layout.vendor_dirs`` could never reach their defaults (Plan 00331) —
    the same defect that made the config inert in docs QA.

    Takes plain strings rather than a ``ProjectLayout`` on purpose: this
    module is deliberately stdlib-only (see the module docstring), and
    importing the facade here would couple every exclusion caller to
    ``core``.

    Args:
        vendor_dirs: The project's EFFECTIVE vendored directory names,
            ordinarily ``ProjectLayout.vendor_dirs``. ``None`` means "no
            layout available" and keeps the canonical set. An explicitly
            EMPTY iterable is distinct from ``None``: it is ``mode: replace``
            with nothing declared, and must exclude nothing rather than
            silently restoring the built-ins.

    Returns:
        Sorted glob patterns. Sorted because a frozenset has no order, and
        an unstable pattern tuple would make the same config produce
        different (if equivalent) exclusion lists between runs.
    """
    names = CORE_VENDORED_BUILD_DIR_NAMES if vendor_dirs is None else vendor_dirs
    return tuple(f"**/{name}/**" for name in sorted(names))


def merge_exclude_patterns(*groups: Sequence[str] | None) -> list[str]:
    """Union the given pattern groups into one ordered, de-duplicated list.

    Exclusion is additive: a handler's effective excludes are the union of its
    built-in defaults, the project-level ``daemon.exclude_paths`` default, and
    its own per-handler ``exclude_paths`` option — none overrides the others.
    Empty/None groups and empty patterns are skipped; first-seen order is kept.
    """
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not group:
            continue
        for pattern in group:
            if pattern and pattern not in seen:
                seen.add(pattern)
                merged.append(pattern)
    return merged


def resolve_project_root() -> str | None:
    """Best-effort absolute project root for anchored-glob matching.

    Returns None when ProjectContext is not initialised (e.g. unit tests), in
    which case only unanchored patterns match (against the raw path). Imported
    lazily to avoid a util→core import cycle at module load.
    """
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    if not getattr(ProjectContext, "_initialized", False):
        return None
    return str(ProjectContext.project_root())


def resolve_lookup_root(
    project_root_override: Path | None, workspace_root: Path | str | None
) -> Path:
    """The directory a handler's own on-disk lookup is rooted at.

    Plan 00460 review finding m5: this exact three-step precedence (a test
    override, then a registry ``workspace_root`` option, then
    :func:`resolve_project_root` with a cwd fallback) was duplicated
    line-for-line across several handlers that each needed "the project
    root, but hermetically overridable in a test". Centralised here, next
    to :func:`resolve_project_root`, as the one definition of that
    precedence; ``subagent_tool_resolution`` re-exports it so its existing
    callers (``dispatch_declaration``, ``subagent_report_size_blocker``)
    need no import change.

    An injected TEST override wins, then the registry's ``workspace_root``
    option, then :func:`resolve_project_root` (None when ``ProjectContext``
    is not initialised, e.g. a bare unit test), falling back to the process
    cwd so this always returns a concrete path.
    """
    if project_root_override is not None:
        return project_root_override
    if workspace_root is not None:
        return Path(workspace_root)
    resolved = resolve_project_root()
    return Path(resolved) if resolved is not None else Path.cwd()


def path_matches_globs(
    file_path: str,
    patterns: Sequence[str] | None,
    *,
    project_root: str | os.PathLike[str] | None = None,
    layout: VendoredPathJudge | None = None,
) -> bool:
    """Return True if ``file_path`` matches any glob in ``patterns``.

    The glob dialect is this module's, documented at the top. Exclusion is only
    the most common *use* of the answer, not the answer itself — a project may
    also want to select paths in order to treat them SPECIALLY rather than to
    skip them, which is what ``tdd_enforcement``'s ``test_path_map`` does
    (Plan 00251). Sharing this matcher keeps one glob dialect across the whole
    config surface, so a project learns the syntax once.

    Args:
        file_path: Absolute or relative path being considered.
        patterns: Glob patterns. ``None`` or empty never matches.
        project_root: Optional project root; enables project-relative and
            leading-``/`` anchored matching.
        layout: Anything answering ``is_vendored_path`` (ordinarily a
            ``ProjectLayout``), used to resolve a
            :data:`~utils.vendor_paths.VENDOR_DIRS_TOKEN` entry. Omitting it
            falls back to the built-in vendored set.

    Returns:
        True if any pattern matches any candidate form of the path.
    """
    return (
        first_matching_glob(file_path, patterns, project_root=project_root, layout=layout)
        is not None
    )


def first_matching_glob(
    file_path: str,
    patterns: Sequence[str] | None,
    *,
    project_root: str | os.PathLike[str] | None = None,
    layout: VendoredPathJudge | None = None,
) -> str | None:
    """The first pattern, in order, that ``file_path`` matches; else ``None``.

    :func:`path_matches_globs` for a caller that must also say WHICH pattern
    matched. Asking that question one pattern at a time re-derives the
    candidate paths (an ``os.path.relpath`` each) and discards the shared
    step cache on every call -- for ``secret_file_guard``, which asks per
    token of a Bash command, that repetition was most of its cost.

    Args:
        file_path: Absolute or relative path being considered.
        patterns: Glob patterns, tried in order. ``None`` or empty never matches.
        project_root: As for :func:`path_matches_globs`.
        layout: As for :func:`path_matches_globs`.

    Returns:
        The first matching pattern, or ``None``.
    """
    if not patterns:
        return None
    candidates = _candidate_paths(file_path, project_root)
    # A realistic exclude list is mostly `**/<name>/**` patterns that share
    # an identical prefix and diverge only at the literal name -- see
    # `_glob_fullmatch`'s docstring. This cache lets that shared work be
    # computed once per candidate instead of once per pattern.
    step_cache: dict[tuple[object, ...], list[bool]] = {}
    for pattern in patterns:
        if not pattern:
            continue
        if pattern == VENDOR_DIRS_TOKEN:
            # A predicate reference, not a glob: see VENDOR_DIRS_TOKEN.
            #
            # Judged on the FIRST candidate only, not `any` of them.
            # `_candidate_paths` puts the project-relative form first when a
            # root is known, and that is the form `vendor_exceptions` is
            # written against. Asking `any` would let the raw absolute form
            # answer "vendored" while the exception -- which can only match
            # the relative form -- never gets a say, making a declared
            # carve-out silently unreachable.
            if _resolves_vendor_token(candidates[0], layout):
                return pattern
            continue
        if any(
            _glob_fullmatch(pattern, candidate, step_cache=step_cache) for candidate in candidates
        ):
            return pattern
    return None


def is_path_excluded(
    file_path: str,
    patterns: Sequence[str] | None,
    *,
    project_root: str | os.PathLike[str] | None = None,
    layout: VendoredPathJudge | None = None,
) -> bool:
    """Return True if ``file_path`` matches any exclusion glob in ``patterns``.

    A thin naming layer over :func:`path_matches_globs`: identical behaviour,
    but the name states what the caller MEANS by a match. Kept as the entry point
    for the exclusion callers so their code reads as exclusion rather than as
    pattern-matching.

    Args:
        file_path: Absolute or relative path of the file being written/edited.
        patterns: Glob patterns to exclude. ``None`` or empty never excludes.
        project_root: Optional project root; enables project-relative and
            leading-``/`` anchored matching.

    Returns:
        True if any pattern matches any candidate form of the path.
    """
    return path_matches_globs(file_path, patterns, project_root=project_root, layout=layout)


def handler_excludes_path(
    file_path: str,
    *,
    handler_patterns: Sequence[str] | None,
    project_patterns: Sequence[str] | None,
    defaults: Sequence[str] | None = None,
    layout: VendoredPathJudge | None = None,
) -> bool:
    """Whether a handler should skip ``file_path`` given all three exclude sources.

    This is the handler-facing decision, defined ONCE. It was previously copied
    into several handlers as a private ``_is_excluded`` — byte-identical in most,
    with ``error_hiding_blocker`` differing only by prepending its own defaults
    and dropping the short-circuit — which is what turned "paste another copy"
    into "extract the one that exists" (Plan 00251). The exact number of
    current callers is deliberately NOT stated here: it drifts every time a
    handler adopts this function without this docstring being updated in the
    same change (Plan 00288 DESIGN §1c). Grep for callers of
    ``handler_excludes_path`` for the current count.

    The three sources are ADDITIVE and none overrides another: built-in
    ``defaults``, the project-wide ``daemon.exclude_paths``, and the handler's own
    ``exclude_paths`` option.

    Args:
        file_path: Path of the file being written or edited.
        handler_patterns: The handler's own ``exclude_paths`` option.
        project_patterns: Project-wide ``daemon.exclude_paths``, injected by the
            registry after construction.
        defaults: The handler's built-in exclusions, if it has any.
        layout: The handler's injected ``_project_layout``, used to resolve a
            :data:`~utils.vendor_paths.VENDOR_DIRS_TOKEN` entry in any of the
            three sources. A project writes ``{vendor-dirs}`` instead of
            restating the vendored directory names by hand, which is what
            made those names a distributed source of truth.

    Returns:
        True when any source matches, so the handler should not act on this path.
    """
    patterns = merge_exclude_patterns(defaults, project_patterns, handler_patterns)
    # Short-circuit on "nothing configured anywhere". `is_path_excluded` would
    # also return False, but only after `resolve_project_root()` has imported
    # ProjectContext — pointless work on the common path where no project
    # configures exclusions.
    if not patterns:
        return False
    return is_path_excluded(file_path, patterns, project_root=resolve_project_root(), layout=layout)
