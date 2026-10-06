"""Secret word list loading, matching, and redaction — the ONE place the
``sensitive_content`` handler's secret list is ever read (Plan 00201).

No-echo threat model: a deny ``reason`` is shown to the user, written to the
session transcript, and may be pasted into a bug report. So a secret term
must never appear verbatim in a deny reason, a daemon log line, or a
payload-capture file — only an INDEX into the gitignored (hence
meaningless-without-it) word list may ever be surfaced.
This module is imported by the ``sensitive_content`` handler (for matching)
and by every low-level leak vector (``daemon/payload_capture.py``,
``core/router.py``'s debug log, ``core/front_controller.py``'s error log) so
there is exactly one code path that ever reads the raw terms — DRY, and it
cannot drift.

KNOWN GAP, recorded deliberately (Plan 00233): these vectors are all
DAEMON-OWNED outputs. Claude Code's own session transcripts are not redacted
by anything — a term pasted into a conversation persists there verbatim. The
enumeration above was drawn by listing code sites the daemon writes to, not
by reasoning about which artefacts on disk hold secrets, so a clean scan of
daemon outputs is not evidence that a term is absent from the machine.

Two independent caches, two different lifetimes:

- Term list per PATH is cached by (mtime, size) — editing
  ``block-words.secret`` without restarting the daemon is picked up.
- The CONFIGURED path itself is cached for the life of the process. Config
  changes in this daemon are only ever picked up on restart (see
  ``daemon/payload_capture.py``'s own docstring), so re-deriving it on every
  event — this module backs a hot path, ``core/router.py``'s per-PreToolUse
  debug log — would be a real cost for no benefit. ``reset_active_path_cache``
  exists purely so unit tests are not coupled to that process lifetime.
"""

from __future__ import annotations

import logging
import re
import stat
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

DEFAULT_SECRET_WORD_LIST_PATH: Final[str] = ".claude/block-words.secret"
REDACTED_PLACEHOLDER: Final[str] = "[REDACTED]"
# Stands in for a payload a sink could not redact because the word list is
# unreadable: with no terms to match, the only safe output is none of it.
WITHHELD_PLACEHOLDER: Final[str] = "[WITHHELD: secret word list unreadable]"

_COMMENT_PREFIX: Final[str] = "#"

# Venv-slug spelling of a path-shaped secret term (see ``_slug_variant``):
# the leading separator is dropped and inner separators become underscores.
_PATH_SEPARATOR: Final[str] = "/"
_SLUG_SEPARATOR: Final[str] = "_"
# Prose and hostnames hyphenate a name; code identifiers, module names and
# filenames underscore the SAME name. Both spellings must be caught.
_HYPHEN: Final[str] = "-"
# A single-segment path would reduce to a bare word ('/home' -> 'home') and
# match innocent text, so a slug variant needs at least two segments.
_MIN_SLUG_SEGMENTS: Final[int] = 2

# Path -> (mtime, term tuple). A missing file is cached as mtime -1.0 so a
# repeated lookup for an absent file does not repeatedly hit the filesystem.
_TERMS_CACHE: dict[Path, tuple[float, tuple[str, ...]]] = {}
_MISSING_FILE_MTIME: Final[float] = -1.0

# Process-lifetime cache for the CONFIGURED path (see module docstring).
_ACTIVE_PATH_RESOLVED: bool = False
_ACTIVE_PATH: Path | None = None


class SecretWordListUnreadableError(OSError):
    """The secret word list EXISTS but cannot be read as a list of terms.

    An absent list is the documented opt-out and stays inert. A list the
    project did create but the daemon cannot read is a different fact: treating
    it as "no terms" would silently disable every guard and redaction sink that
    depends on it. Subclasses ``OSError`` so best-effort sinks that already
    catch ``OSError`` skip their write rather than emit unredacted output. The
    message names the path and the failure kind only, never any content.
    """


def resolve_secret_word_list_path(configured_path: str | None, project_root: Path) -> Path:
    """Resolve the secret word list path.

    Mirrors ``daemon/payload_capture.resolve_capture_dir``'s shape: an
    explicit configured value is repository-relative and joined to
    ``project_root``; ``None``/empty falls back to the built-in default path.

    Config carries zero absolute paths (Plan 00303): an absolute or
    home-relative ``configured_path`` is logged and treated as unset, never
    raised -- this module's contract is fail-open/advisory, matching
    ``payload_capture``'s degrade-not-raise handling of the same shape. The
    same degrade is also surfaced where a human sees it (``describe_secret_
    word_list_degradation``, called by ``hooks-daemon check`` -- Plan 00305
    Task 1.3), since a missing default word list is inert by design and a
    `logger.warning` alone is easy to miss on a repo that never provisioned
    one.
    """
    from claude_code_hooks_daemon.utils.repo_relative_path import (
        normalise_repo_relative_path,
    )

    raw = configured_path or DEFAULT_SECRET_WORD_LIST_PATH
    try:
        relative = normalise_repo_relative_path(raw, "secret_word_list_path")
    except ValueError as exc:
        logger.warning("Ignoring secret_word_list_path: %s", exc)
        relative = DEFAULT_SECRET_WORD_LIST_PATH
    return project_root / relative


def describe_secret_word_list_degradation(configured_path: str | None) -> str | None:
    """Describe the silent absolute/home-relative-path degrade, for a human-visible report.

    ``resolve_secret_word_list_path`` treats an absolute or home-relative
    ``configured_path`` as unset and falls back to
    :data:`DEFAULT_SECRET_WORD_LIST_PATH` -- correct per the zero-absolute-
    paths ruling (Plan 00303), but the only evidence was a `logger.warning`
    a human is unlikely to ever read. This is the pure, side-effect-free
    detector behind that visibility: it never raises and never touches the
    filesystem, so ``hooks-daemon check`` (and any other degraded-mode
    report) can call it per configured project root with no extra cost.

    Args:
        configured_path: The raw ``secret_word_list_path`` option value, or
            ``None``/empty when nothing was configured.

    Returns:
        A human-readable advisory naming the ignored value and the default
        it was replaced by, or ``None`` when nothing was configured or the
        configured value is a plain repository-relative path (no degrade).
    """
    if not configured_path:
        return None

    from claude_code_hooks_daemon.utils.repo_relative_path import (
        normalise_repo_relative_path,
    )

    try:
        normalise_repo_relative_path(configured_path, "secret_word_list_path")
    except ValueError:
        return (
            f"secret_word_list_path {configured_path!r} is not repository-relative "
            f"and was IGNORED -- secret-term blocking falls back to the default "
            f"{DEFAULT_SECRET_WORD_LIST_PATH!r}, which likely does not exist on this repo. "
            f"Move the word list under the repository (or use the {{REPO_ROOT}} token) "
            f"to restore enforcement."
        )
    return None


def _unreadable(path: Path, reason: str) -> SecretWordListUnreadableError:
    return SecretWordListUnreadableError(
        f"secret word list exists but cannot be read: {path} ({reason})"
    )


def load_secret_terms(path: Path) -> tuple[str, ...]:
    """Load terms from ``path``: one per line, ``#`` comments, blanks ignored.

    Order is preserved (never sorted/deduplicated) so a 1-based index into
    the returned tuple is stable and meaningful in a deny message. An ABSENT
    file is a documented no-match: the feature must stay inert until a project
    opts in by creating the file.

    Anything else at ``path`` counts as opting in, so it must be a readable
    regular file: a dangling symlink, a directory, a FIFO or a read error is
    never an empty term set.

    Raises:
        SecretWordListUnreadableError: ``path`` exists but cannot be read.
    """
    try:
        mode = path.stat().st_mode
    except (FileNotFoundError, NotADirectoryError):
        if path.is_symlink():
            raise _unreadable(path, "dangling symlink") from None
        return ()
    except OSError as exc:
        raise _unreadable(path, exc.strerror or type(exc).__name__) from exc
    if not stat.S_ISREG(mode):
        raise _unreadable(path, "not a regular file")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise _unreadable(path, exc.strerror or type(exc).__name__) from exc

    terms: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(_COMMENT_PREFIX):
            continue
        terms.append(line)
    return tuple(terms)


def get_cached_secret_terms(path: Path) -> tuple[str, ...]:
    """Return ``path``'s terms, cached until its mtime changes.

    A missing file is cached too (as :data:`_MISSING_FILE_MTIME`) so repeated
    lookups for an absent file are a dict lookup, not a repeated ``stat()``.
    An unreadable list is never cached: the error propagates on every call, so
    it cannot be remembered as "no terms".

    Raises:
        SecretWordListUnreadableError: ``path`` exists but cannot be read.
    """
    try:
        mtime = path.stat().st_mtime
    except (FileNotFoundError, NotADirectoryError):
        mtime = _MISSING_FILE_MTIME
    except OSError:
        return load_secret_terms(path)

    if mtime == _MISSING_FILE_MTIME and path.is_symlink():
        return load_secret_terms(path)

    cached = _TERMS_CACHE.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    terms = load_secret_terms(path) if mtime != _MISSING_FILE_MTIME else ()
    _TERMS_CACHE[path] = (mtime, terms)
    return terms


def reset_terms_cache() -> None:
    """Clear the per-path terms cache. Test-only escape hatch."""
    _TERMS_CACHE.clear()


def _resolve_active_path() -> Path | None:
    """Resolve the configured secret word list path, once per process.

    Imports ``ProjectContext``/``Config`` lazily to avoid a util-\\>core
    import cycle at module load (mirrors ``utils/path_exclusion.py``'s
    ``resolve_project_root``). Never raises. An unusable CONFIG falls back to
    the raw-YAML or shipped default word list path (Plan 00466 N43), so a typo
    never disables redaction; only an unknown project root degrades to ``None``
    (feature inert), matching the sanctioned fail-open contract
    already used by ``context_sidecar``/``compaction_signal``/
    ``payload_capture`` for daemon-adjacent, best-effort I/O.

    ``ValueError`` is part of that promise and not an afterthought: it is what
    an UNUSABLE CONFIG raises. ``Config.load`` raises it for an unsupported
    suffix, and pydantic's ``ValidationError`` subclasses it, so a config
    holding one key this schema does not know -- a legacy spelling, or a newer
    daemon's -- arrives here as a ``ValueError``. Catching only ``OSError`` and
    ``RuntimeError`` let that escape a boundary every leak-vector site calls on
    a live path, so a config the daemon merely could not READ took down the
    event being routed (Plan 00405 N9).

    Every such failure is logged at WARNING: going inert means no terms are
    matched, so the fail-open contract trades a crash for a quietly weakened
    guard, and that trade should be visible to whoever can fix the config.
    """
    global _ACTIVE_PATH_RESOLVED, _ACTIVE_PATH
    if _ACTIVE_PATH_RESOLVED:
        return _ACTIVE_PATH

    _ACTIVE_PATH_RESOLVED = True
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    if not getattr(ProjectContext, "_initialized", False):
        _ACTIVE_PATH = None
        return None

    project_root: Path | None = None
    config_path: Path | None = None
    try:
        project_root = ProjectContext.project_root()
        config_path = ProjectContext.config_path()
    except (OSError, RuntimeError, ValueError) as exc:
        log_and_continue(
            logger,
            exc,
            reason="secret redaction is INERT because the project root is unknown: no terms will be matched or redacted, and there is no config to read the word list path from; the daemon must still serve hooks",
        )
        project_root = None
    if project_root is None or config_path is None:
        _ACTIVE_PATH = None
        return _ACTIVE_PATH

    try:
        from claude_code_hooks_daemon.config.models import Config, handler_options

        config = Config.load_or_default(config_path)
        options = handler_options(config.handlers.pre_tool_use.get("sensitive_content"))
        configured = options.get("secret_word_list_path")
    except (OSError, RuntimeError, ValueError) as exc:
        # A missing config loads the defaults without raising, so every one of
        # these means the config IS there and cannot be used. A config typo is
        # ordinary, and a typo must never switch redaction off (Plan 00466
        # N43): fall toward redaction, using the path the raw YAML names or the
        # shipped default. Logged at WARNING because it is security-relevant.
        configured = _configured_path_from_raw_yaml(config_path)
        logger.warning(
            "Secret redaction: project config unusable (%s). Redacting with the "
            "default word list path (or the one the raw config names) until it validates.",
            exc,
        )
    _ACTIVE_PATH = resolve_secret_word_list_path(configured, project_root)
    return _ACTIVE_PATH


def _configured_path_from_raw_yaml(config_path: Path) -> str | None:
    """``secret_word_list_path`` read straight from the YAML, or ``None``.

    For a config that fails validation: the rest of the file is untrusted, but
    this one option can still be recovered so a project that moved its word
    list keeps it redacted. Never raises; anything unusable yields ``None``
    (the shipped default path).
    """
    import yaml

    node: object = None
    try:
        node = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        log_and_continue(
            logger,
            exc,
            reason="the raw config could not be read either, so no configured word list path is found and the default path applies; redaction still covers that default",
        )
        node = None
    for key in ("handlers", "pre_tool_use", "sensitive_content", "options"):
        node = node.get(key) if isinstance(node, dict) else None
    value = node.get("secret_word_list_path") if isinstance(node, dict) else None
    return value if isinstance(value, str) else None


def reset_active_path_cache() -> None:
    """Clear the process-lifetime resolved-path cache. Test-only escape hatch."""
    global _ACTIVE_PATH_RESOLVED, _ACTIVE_PATH
    _ACTIVE_PATH_RESOLVED = False
    _ACTIVE_PATH = None


def project_secret_terms(project_root: Path, config_path: Path) -> tuple[str, ...]:
    """Terms of the word list ``config_path`` names, for a process with no ``ProjectContext``.

    A standalone script (``scripts/debug_info.py``) never initialises the
    context, so :func:`get_active_secret_terms` answers ``()`` for it, which
    reads as "no terms" rather than "not resolved". This resolves the same
    list from the project's own config instead. The option is read from the raw
    YAML, so a config the schema rejects still yields its word list path (the
    N43 rule), and a missing config falls back to the shipped default path.

    Raises:
        SecretWordListUnreadableError: the list exists but cannot be read.
        ImportError: PyYAML is not installed in this interpreter.
    """
    configured = _configured_path_from_raw_yaml(config_path)
    return get_cached_secret_terms(resolve_secret_word_list_path(configured, project_root))


def get_active_secret_terms() -> tuple[str, ...]:
    """Terms from the currently configured secret word list.

    The one entry point every leak-vector site (payload capture, router
    debug log, front-controller error log, transcript archiver) calls.
    Empty tuple whenever the feature is inert (no file, no config, no
    initialised project).

    Raises:
        SecretWordListUnreadableError: the configured list exists but cannot
            be read. Callers either fail closed or use
            :func:`redact_structure_active`.
    """
    path = _resolve_active_path()
    if path is None:
        return ()
    return get_cached_secret_terms(path)


def _slug_variant(term: str) -> str | None:
    """The venv-slug spelling of a path-shaped ``term``, or ``None``.

    The venv fingerprinter renders a project root as a directory-name slug:
    the leading ``/`` is dropped and inner ``/`` become ``_``, so a project at
    ``/home/someone/project`` produces ``home_someone_project-py311-<hash>``.
    A secret term written in path form therefore never substring-matches its
    own on-disk slug, and that blind spot is real rather than theoretical - a
    tracked document carried the slug spelling of a listed path while the
    whole-tree scanner reported the repository clean.

    Only paths with at least TWO non-empty segments get a variant. A single
    segment would reduce ``/home`` to ``home``, which matches 'homepage' and
    every other innocent word - a false positive that would train people to
    ignore the guard.
    """
    if _PATH_SEPARATOR not in term:
        return None
    segments = [segment for segment in term.split(_PATH_SEPARATOR) if segment]
    if len(segments) < _MIN_SLUG_SEGMENTS:
        return None
    return _SLUG_SEPARATOR.join(segments)


def _separator_spellings(value: str) -> tuple[str, ...]:
    """``value`` with ``-`` and ``_`` treated as interchangeable.

    Swapping separators cannot broaden a match: the result is the same length
    and the same shape, so this adds spellings without adding false
    positives. ``some.host`` still does not match ``some-host``.
    """
    spellings = [value]
    for candidate in (
        value.replace(_HYPHEN, _SLUG_SEPARATOR),
        value.replace(_SLUG_SEPARATOR, _HYPHEN),
    ):
        if candidate not in spellings:
            spellings.append(candidate)
    return tuple(spellings)


def _term_variants(term: str) -> tuple[str, ...]:
    """``term`` plus every alternative spelling it must also be caught by.

    Two independent axes, both of which this repository's own history proved
    necessary during its identifier rewrite:

    * path -> venv slug (``/home/someone`` -> ``home_someone``)
    * hyphen <-> underscore (``some-host`` -> ``some_host``)

    They compose: a path term's slug is also offered in both separator
    spellings. Order is stable and duplicates are dropped so the variant list
    is deterministic.
    """
    bases = [term]
    slug = _slug_variant(term)
    if slug is not None:
        bases.append(slug)

    variants: list[str] = []
    for base in bases:
        for spelling in _separator_spellings(base):
            if spelling not in variants:
                variants.append(spelling)
    return tuple(variants)


def term_matches(text: str, term: str) -> bool:
    """Is ``term`` (or any alternative spelling of it) present in ``text``?

    THE single matching predicate for the secret word list. Both enforcement
    surfaces — the ``sensitive_content`` handler at write time and the
    whole-tree QA scanner — must call this rather than reimplement the test,
    or they drift: the scanner previously hand-rolled a plain substring loop
    and so kept reporting a repository clean while the handler's own rules
    said otherwise.
    """
    if not term:
        return False
    lowered = text.lower()
    return any(variant.lower() in lowered for variant in _term_variants(term))


def find_first_match_index(text: str, terms: tuple[str, ...]) -> int | None:
    """1-based index of the first ``terms`` entry found in ``text``, or ``None``.

    Case-insensitive LITERAL substring containment — a term that is itself a
    regex metacharacter string (e.g. ``a.b*c``) matches only that exact
    substring, never as a pattern.

    A path-shaped term also matches its venv-slug spelling (see
    :func:`_slug_variant`). The returned index is always the position of the
    ORIGINAL term, so the "entry N of M" deny message stays meaningful — a
    variant never shifts N.
    """
    if not terms:
        return None
    for index, term in enumerate(terms, start=1):
        if term_matches(text, term):
            return index
    return None


def _redact_term(text: str, term: str) -> str:
    """Replace every case-insensitive LITERAL occurrence of ``term`` in ``text``.

    Alternative spellings are redacted too: detecting a leaked term but then
    writing it into a log would move the leak rather than close it.
    """
    result = text
    for variant in _term_variants(term):
        pattern = re.compile(re.escape(variant), re.IGNORECASE)
        result = pattern.sub(REDACTED_PLACEHOLDER, result)
    return result


def redact_text(text: str, terms: tuple[str, ...]) -> str:
    """Replace every occurrence of every ``terms`` entry in ``text`` with a placeholder."""
    result = text
    for term in terms:
        if term:
            result = _redact_term(result, term)
    return result


def redact_structure(obj: Any, terms: tuple[str, ...]) -> Any:
    """Recursively redact every string value in a JSON-like structure.

    Used to sanitise a full ``hook_input`` dict (or any nested dict/list of
    it) before it reaches a log line or a capture file. Non-string leaves
    (numbers, booleans, ``None``) are returned unchanged.
    """
    if isinstance(obj, str):
        return redact_text(obj, terms)
    if isinstance(obj, dict):
        return {key: redact_structure(value, terms) for key, value in obj.items()}
    if isinstance(obj, list):
        return [redact_structure(item, terms) for item in obj]
    return obj


def redact_structure_active(obj: Any) -> Any:
    """Redact ``obj`` with the active word list, or withhold it entirely.

    The one entry point for sinks that log or persist a payload. When the
    configured list is unreadable there are no terms to redact with, so the
    payload is replaced by :data:`WITHHELD_PLACEHOLDER` rather than written
    through as if nothing needed redacting.
    """
    try:
        terms = get_active_secret_terms()
    except SecretWordListUnreadableError as exc:
        logger.warning("Withholding a logged payload: %s", exc)
        return WITHHELD_PLACEHOLDER
    return redact_structure(obj, terms) if terms else obj
