"""Secret word list loading, matching, and redaction — the ONE place the
``sensitive_content`` handler's secret list is ever read (Plan 00201).

No-echo threat model: a deny ``reason`` is shown to the user, written to the
session transcript, and may be pasted into a bug report. So a secret term
must never appear verbatim in a deny reason, a daemon log line, a
payload-capture file, or a transcript archive — only an INDEX into the
gitignored (hence meaningless-without-it) word list may ever be surfaced.
This module is imported by the ``sensitive_content`` handler (for matching)
and by every low-level leak vector (``daemon/payload_capture.py``,
``core/router.py``'s debug log, ``core/front_controller.py``'s error log,
``handlers/pre_compact/transcript_archiver.py``) so there is exactly one
code path that ever reads the raw terms — DRY, and it cannot drift.

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
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

DEFAULT_SECRET_WORD_LIST_PATH: Final[str] = ".claude/block-words.secret"
REDACTED_PLACEHOLDER: Final[str] = "[REDACTED]"

_COMMENT_PREFIX: Final[str] = "#"

# Path -> (mtime, term tuple). A missing file is cached as mtime -1.0 so a
# repeated lookup for an absent file does not repeatedly hit the filesystem.
_TERMS_CACHE: dict[Path, tuple[float, tuple[str, ...]]] = {}
_MISSING_FILE_MTIME: Final[float] = -1.0

# Process-lifetime cache for the CONFIGURED path (see module docstring).
_ACTIVE_PATH_RESOLVED: bool = False
_ACTIVE_PATH: Path | None = None


def resolve_secret_word_list_path(configured_path: str | None, project_root: Path) -> Path:
    """Resolve the secret word list path.

    Mirrors ``daemon/payload_capture.resolve_capture_dir``'s shape: an
    explicit configured value wins (absolute paths used verbatim, relative
    ones joined to ``project_root``); ``None``/empty falls back to
    :data:`DEFAULT_SECRET_WORD_LIST_PATH`.
    """
    raw = configured_path or DEFAULT_SECRET_WORD_LIST_PATH
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    return project_root / candidate


def load_secret_terms(path: Path) -> tuple[str, ...]:
    """Load terms from ``path``: one per line, ``#`` comments, blanks ignored.

    Order is preserved (never sorted/deduplicated) so a 1-based index into
    the returned tuple is stable and meaningful in a deny message. A missing
    or unreadable file is a documented no-match, not an error — the feature
    must stay inert until a project opts in by creating the file.
    """
    if not path.is_file():
        return ()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.debug("Could not read secret word list %s: %s", path, exc)
        return ()

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
    """
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = _MISSING_FILE_MTIME

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
    ``resolve_project_root``). Never raises: any failure to resolve degrades
    to ``None`` (feature inert), matching the sanctioned fail-open contract
    already used by ``context_sidecar``/``compaction_signal``/
    ``payload_capture`` for daemon-adjacent, best-effort I/O.
    """
    global _ACTIVE_PATH_RESOLVED, _ACTIVE_PATH
    if _ACTIVE_PATH_RESOLVED:
        return _ACTIVE_PATH

    _ACTIVE_PATH_RESOLVED = True
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    if not getattr(ProjectContext, "_initialized", False):
        _ACTIVE_PATH = None
        return None

    try:
        from claude_code_hooks_daemon.config.models import Config

        project_root = ProjectContext.project_root()
        config = Config.load_or_default(ProjectContext.config_path())
        handler_cfg = config.handlers.pre_tool_use.get("sensitive_content", {})
        options = handler_cfg.get("options", {}) if isinstance(handler_cfg, dict) else {}
        configured = options.get("secret_word_list_path") if isinstance(options, dict) else None
        _ACTIVE_PATH = resolve_secret_word_list_path(configured, project_root)
    except (OSError, RuntimeError) as exc:
        logger.debug("Could not resolve secret word list path: %s", exc)
        _ACTIVE_PATH = None
    return _ACTIVE_PATH


def reset_active_path_cache() -> None:
    """Clear the process-lifetime resolved-path cache. Test-only escape hatch."""
    global _ACTIVE_PATH_RESOLVED, _ACTIVE_PATH
    _ACTIVE_PATH_RESOLVED = False
    _ACTIVE_PATH = None


def get_active_secret_terms() -> tuple[str, ...]:
    """Terms from the currently configured secret word list.

    The one entry point every leak-vector site (payload capture, router
    debug log, front-controller error log, transcript archiver) calls.
    Empty tuple whenever the feature is inert (no file, no config, no
    initialised project) — never raises.
    """
    path = _resolve_active_path()
    if path is None:
        return ()
    return get_cached_secret_terms(path)


def find_first_match_index(text: str, terms: tuple[str, ...]) -> int | None:
    """1-based index of the first ``terms`` entry found in ``text``, or ``None``.

    Case-insensitive LITERAL substring containment — a term that is itself a
    regex metacharacter string (e.g. ``a.b*c``) matches only that exact
    substring, never as a pattern.
    """
    if not terms:
        return None
    lowered = text.lower()
    for index, term in enumerate(terms, start=1):
        if term and term.lower() in lowered:
            return index
    return None


def _redact_term(text: str, term: str) -> str:
    """Replace every case-insensitive LITERAL occurrence of ``term`` in ``text``."""
    pattern = re.compile(re.escape(term), re.IGNORECASE)
    return pattern.sub(REDACTED_PLACEHOLDER, text)


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
