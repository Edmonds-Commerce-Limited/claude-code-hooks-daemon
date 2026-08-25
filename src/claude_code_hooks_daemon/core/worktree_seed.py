"""Worktree seed configuration — vocabulary and parsing (Plan 00267 Phase 2).

A fresh git worktree is a clean checkout, so the git-ignored local files that
make the main checkout work are simply absent from it. A project declares which
paths to seed, and how, under the ``worktree_create`` handler's ``seed`` option:

.. code-block:: yaml

    options:
      seed:
        default_mode: symlink        # symlink | copy
        entries:
          - .env.local               # uses default_mode
          - path: .secrets
            mode: copy               # explicit override

This module owns only the **vocabulary and the parse**. It performs no I/O and
knows nothing about worktrees, mirroring :mod:`core.worktree_naming`, so the
seeding executor and the config-suggestion scanner can both depend on the same
entry type without importing a handler.

**Why parsing is defensive here.** Handler options are applied to an instance by
an unvalidated ``setattr`` (``handlers/registry.py``), so whatever a project
wrote in YAML arrives exactly as typed. A predecessor of this feature stored a
bare string and iterated it *per character* — ``".env.local"`` became ``'.'``,
``'e'``, ``'n'``, … — matching nothing and seeding nothing, with no error
raised. The parse below is the boundary that makes such a mistake loud rather
than invisible.

**Shape versus content.** This module rejects *shape* errors — a mistyped
config the daemon cannot interpret — by warning and skipping, never raising, so
one bad line cannot take worktree creation down. *Content* errors (a
well-formed entry naming a path that is absent or unsafe) are the executor's
concern and DO fail fast, because silently seeding nothing is precisely the
failure this feature exists to prevent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

logger = logging.getLogger(__name__)

# The two ways a path can be placed into a fresh worktree.
SEED_MODE_SYMLINK: Final = "symlink"
SEED_MODE_COPY: Final = "copy"

VALID_SEED_MODES: Final[tuple[str, ...]] = (SEED_MODE_SYMLINK, SEED_MODE_COPY)

# Symlink is the default because it keeps the main checkout the single source of
# truth: edit the canonical file once and every worktree sees it, with no stale
# duplicate to reconcile. The tradeoff is real and documented — a write from
# INSIDE a worktree flows back through the link — which is exactly why a project
# can choose ``copy`` per entry for anything its agents may overwrite.
DEFAULT_SEED_MODE: Final = SEED_MODE_SYMLINK

# Recognised keys, so a typo is reported instead of silently ignored.
_KEY_DEFAULT_MODE: Final = "default_mode"
_KEY_ENTRIES: Final = "entries"
_KEY_PATH: Final = "path"
_KEY_MODE: Final = "mode"

_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset({_KEY_DEFAULT_MODE, _KEY_ENTRIES})
_ENTRY_KEYS: Final[frozenset[str]] = frozenset({_KEY_PATH, _KEY_MODE})

_LOG_PREFIX: Final = "worktree seed"


@dataclass(frozen=True)
class SeedEntry:
    """One validated path to place into a fresh worktree.

    Attributes:
        path: Repository-root-relative path to seed. Safety (absolute paths,
            parent traversal, existence) is deliberately NOT checked here —
            that is a content concern the executor fails fast on, with the repo
            root in hand. This type only guarantees a non-empty path string.
        mode: One of :data:`VALID_SEED_MODES`.

    Raises:
        ValueError: if a field fails validation. This is FAIL FAST defence for
            the TRUSTED construction path; external config that fails
            validation is instead skipped with a logged warning by
            :func:`parse_seed_config`, never raised.
    """

    path: str
    mode: str

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("SeedEntry.path must be a non-empty string")
        if self.mode not in VALID_SEED_MODES:
            raise ValueError(f"SeedEntry.mode must be one of {VALID_SEED_MODES}; got {self.mode!r}")


def _resolve_default_mode(raw: dict[str, Any]) -> str:
    """Return the configured default mode, falling back on anything unusable."""
    configured = raw.get(_KEY_DEFAULT_MODE, DEFAULT_SEED_MODE)
    if configured in VALID_SEED_MODES:
        return str(configured)
    logger.warning(
        "%s: %s must be one of %s; got %r — using %r",
        _LOG_PREFIX,
        _KEY_DEFAULT_MODE,
        VALID_SEED_MODES,
        configured,
        DEFAULT_SEED_MODE,
    )
    return DEFAULT_SEED_MODE


def _parse_entry(entry: Any, index: int, default_mode: str) -> SeedEntry | None:
    """Parse one ``entries[index]`` value, or return ``None`` if unusable."""
    if isinstance(entry, str):
        path, mode = entry.strip(), default_mode
    elif isinstance(entry, dict):
        unknown = set(entry) - _ENTRY_KEYS
        if unknown:
            logger.warning(
                "%s: entries[%d] has unrecognised key(s) %s; skipped",
                _LOG_PREFIX,
                index,
                sorted(unknown),
            )
            return None
        path = str(entry.get(_KEY_PATH, "") or "").strip()
        mode = str(entry.get(_KEY_MODE, default_mode))
    else:
        logger.warning(
            "%s: entries[%d] must be a path string or a mapping; got %s — skipped",
            _LOG_PREFIX,
            index,
            type(entry).__name__,
        )
        return None

    if not path:
        logger.warning("%s: entries[%d] has no %s; skipped", _LOG_PREFIX, index, _KEY_PATH)
        return None
    if mode not in VALID_SEED_MODES:
        logger.warning(
            "%s: entries[%d] (%s) has %s %r, expected one of %s; skipped",
            _LOG_PREFIX,
            index,
            path,
            _KEY_MODE,
            mode,
            VALID_SEED_MODES,
        )
        return None

    return SeedEntry(path=path, mode=mode)


def parse_seed_config(raw: Any) -> list[SeedEntry]:
    """Parse a raw ``options.seed`` value into validated :class:`SeedEntry`\\ s.

    Degrades gracefully: every rejection is logged and skipped so that one bad
    line cannot disable seeding wholesale, and a surviving good entry is still
    returned alongside a rejected neighbour.

    Args:
        raw: The value as it arrived from YAML — any type, unvalidated.

    Returns:
        The validated entries, in configured order. Empty when unconfigured,
        and empty (with a warning) when the value is not a mapping.
    """
    if not raw:
        return []

    if not isinstance(raw, dict):
        # Catches the two shapes a project is most likely to write by mistake:
        # a bare path string, and a bare list of paths. Neither may be iterated
        # — a string would yield one entry per CHARACTER.
        logger.warning(
            "%s: 'seed' must be a mapping with %r/%r; got %s — ignoring",
            _LOG_PREFIX,
            _KEY_DEFAULT_MODE,
            _KEY_ENTRIES,
            type(raw).__name__,
        )
        return []

    unknown = set(raw) - _TOP_LEVEL_KEYS
    if unknown:
        logger.warning(
            "%s: unrecognised key(s) %s under 'seed'; ignored",
            _LOG_PREFIX,
            sorted(unknown),
        )

    entries = raw.get(_KEY_ENTRIES)
    if not entries:
        return []
    if not isinstance(entries, list):
        logger.warning(
            "%s: %r must be a list; got %s — ignoring",
            _LOG_PREFIX,
            _KEY_ENTRIES,
            type(entries).__name__,
        )
        return []

    default_mode = _resolve_default_mode(raw)
    parsed: list[SeedEntry] = []
    for index, entry in enumerate(entries):
        seed_entry = _parse_entry(entry, index, default_mode)
        if seed_entry is not None:
            parsed.append(seed_entry)
    return parsed
