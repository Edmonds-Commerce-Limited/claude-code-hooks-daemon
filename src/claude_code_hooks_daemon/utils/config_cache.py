"""A parsed-config cache for handlers that run on every hook event.

``Config.load_or_default`` reads the YAML, parses it and runs the whole
pydantic model over it — 76 ms median on this repository's own config. A
handler whose ``matches()`` calls it pays that on every event of its type,
which for a Stop handler is every turn end.

The cache is keyed on the resolved path plus the file's ``(st_mtime_ns,
st_size)``, so an operator who edits their config sees the change on the next
event rather than on the next daemon restart — the daemon may have been up for
days, and a config that quietly stops taking effect is a worse bug than a slow
one. A file that does not exist caches as the defaults under a sentinel key, so
appearing later is also picked up.

Only DETERMINISTIC parse/validation failures are cached (``ValueError`` --
``ValidationError`` is itself a ``ValueError`` subclass, and the YAML-syntax
path in ``Config.load`` already converts ``yaml.YAMLError`` to one too). A
cached failure is stored as a plain record (:class:`_CachedFailure`), never
the raised exception object, and a hit raises a FRESH
:class:`CachedConfigLoadError` every time (Ledger 00466 RV8-M1) — re-raising
the SAME instance repeatedly prepends every call's frames to its one shared
``__traceback__`` forever, which is a daemon-lifetime memory leak and, under
the threaded dispatch this module already accounts for, splices unrelated
threads' frames into one chain.

``OSError`` (``EMFILE``, ``EACCES``, a momentary ``EIO``, and so on) is NEVER
cached (RV8-M2). The cache key identifies the file's CONTENT; an ``OSError``
is a property of the READ, not the content, so caching it under that
signature would make a config that is perfectly valid keep reading as broken
until an edit changes the signature — and a permission fix alone never does
that. Every caller already retries on the next event by simply calling this
function again.

The lock is not defensive decoration. The daemon dispatches through
``await loop.run_in_executor(None, ...)`` in ``daemon/server.py``, whose default
executor is a ``ThreadPoolExecutor``, and this cache is a module-level
singleton for the daemon's lifetime — the same shape whose unlocked eviction
Plan 00437 measured producing ``KeyError``s once the GIL's switch interval was
driven low enough to interleave.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.config.models import Config

#: Stat signature of a path that does not exist. Distinct from any real
#: ``(st_mtime_ns, st_size)``, so a file appearing later misses the cache.
_ABSENT: Final[tuple[int, int]] = (-1, -1)

#: Exceptions ``Config.load_or_default`` can raise that are a DETERMINISTIC
#: function of the file's bytes -- the same input always fails the same way,
#: which is what makes caching them by content signature safe. Both derive
#: from ``ValueError`` (``ValidationError`` is a ``ValueError`` subclass;
#: ``Config.load``'s own ``yaml.YAMLError`` path already converts to one), so
#: a single entry covers both. Deliberately excludes ``OSError`` (RV8-M2: a
#: property of the READ, not the content -- see the module docstring) and
#: ``RuntimeError`` (nothing in ``Config.load``/``load_or_default`` documents
#: raising one; the only ``RuntimeError`` in this codebase's config path is
#: ``_check_wired_event_field_coverage``, which runs at IMPORT time, never
#: from a per-call load). Every caller of :func:`load_config_cached`
#: (``recovery_cron_advisor``, ``plan_status_snapshot``, ``cron_stop_enforcer``,
#: ``failsafe_cron_session_advisor``, ``cron_subagent_stop_enforcer``,
#: ``remote_docs_routing``) already catches ``ValueError``, so narrowing the
#: cacheable set to it changes nothing about what a caller sees -- only
#: whether a broken config is re-parsed once per event or once per edit
#: (Ledger 00466 RV7-M1 item 3).
_CACHEABLE_LOAD_FAILURES: Final[tuple[type[Exception], ...]] = (ValueError,)

_LOCK: Final[threading.Lock] = threading.Lock()


class CachedConfigLoadError(ValueError):
    """Raised on a cache hit for a config that previously failed to load.

    A FRESH instance every time (RV8-M1) -- the cache never re-raises the
    original exception object, so no traceback ever grows across calls or
    threads. Subclasses ``ValueError``, which is what every existing
    :func:`load_config_cached` caller's ``except`` clause already tests for.
    """

    def __init__(self, original_type: type[Exception], message: str) -> None:
        super().__init__(f"{original_type.__name__}: {message}")
        #: The exception type that failed the ORIGINAL parse, for a caller
        #: that wants to distinguish causes without depending on message text.
        self.original_type = original_type


class _CachedFailure:
    """A cached record of a deterministic load failure -- never the raised
    exception object itself (RV8-M1). Immutable: nothing mutates a cache
    entry in place."""

    __slots__ = ("message", "original_type")

    def __init__(self, original_type: type[Exception], message: str) -> None:
        self.original_type = original_type
        self.message = message


_CACHE: dict[Path, tuple[tuple[int, int], Config | _CachedFailure]] = {}


def _signature(path: Path) -> tuple[int, int]:
    """``(st_mtime_ns, st_size)`` for ``path``, or :data:`_ABSENT`.

    ``OSError`` covers the unreadable and the vanished alike: both mean "we
    cannot vouch for a cached parse", which is the same answer as absent.
    """
    try:
        stat = path.stat()
    except OSError:
        return _ABSENT
    return (stat.st_mtime_ns, stat.st_size)


def load_config_cached(path: str | Path) -> Config:
    """The parsed config at ``path``, re-reading only when the file changed.

    Raises whatever ``Config.load_or_default`` raises — callers that need to
    degrade on an invalid config keep their own ``except``, because "this
    config is broken" is a decision about the handler, not about the cache.
    A DETERMINISTIC parse/validation failure (``ValueError``, which
    ``ValidationError`` derives from) is cached under the SAME signature as a
    successful parse would be (RV7-M1 item 3): while the file's
    ``(st_mtime_ns, st_size)`` stays unchanged, a second call raises a FRESH
    :class:`CachedConfigLoadError` instead of re-parsing the same broken
    bytes, so a syntactically broken config costs one parse per edit rather
    than one per hook event. An ``OSError`` is never cached (RV8-M2) and
    propagates uncached on every call until the read succeeds.
    """
    resolved = Path(path).resolve()
    signature = _signature(resolved)

    # The parse happens UNDER the lock, deliberately. Releasing it around the
    # expensive part lets every concurrent first-caller parse the same file
    # independently — measured at 16 separate parses for 16 threads, which is
    # the cost this module exists to remove. Holding it serialises only a MISS,
    # and a caller waiting on someone else's parse waits no longer than the
    # parse it would otherwise have done itself.
    #
    # A plain Lock, not an RLock: nothing reachable from ``load_or_default``
    # calls back into here, and making re-entry silently work would hide it if
    # something ever did.
    with _LOCK:
        cached = _CACHE.get(resolved)
        if cached is not None and cached[0] == signature:
            result = cached[1]
            if isinstance(result, _CachedFailure):
                raise CachedConfigLoadError(result.original_type, result.message)
            return result

        try:
            config = Config.load_or_default(resolved)
        except _CACHEABLE_LOAD_FAILURES as exc:
            _CACHE[resolved] = (signature, _CachedFailure(type(exc), str(exc)))
            raise
        _CACHE[resolved] = (signature, config)
        return config


def reset_config_cache() -> None:
    """Drop every entry. For tests, and for a deliberate in-process reload."""
    with _LOCK:
        _CACHE.clear()
