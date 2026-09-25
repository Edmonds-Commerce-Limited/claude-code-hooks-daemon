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

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config

#: Stat signature of a path that does not exist. Distinct from any real
#: ``(st_mtime_ns, st_size)``, so a file appearing later misses the cache.
_ABSENT: Final[tuple[int, int]] = (-1, -1)

#: Exceptions ``Config.load_or_default`` can raise on a file that exists but
#: fails to parse or validate -- the same set every caller of
#: :func:`load_config_cached` already catches (``recovery_cron_advisor``,
#: ``plan_status_snapshot``, ``cron_stop_enforcer``,
#: ``failsafe_cron_session_advisor``, ``cron_subagent_stop_enforcer``,
#: ``remote_docs_routing``). Caching a MEMBER of this set, keyed by the same
#: ``(st_mtime_ns, st_size)`` signature as a successful parse, is what makes a
#: config broken by an edit after startup cost one re-parse per change rather
#: than one per event (Ledger 00466 RV7-M1 item 3) -- a caller's own ``except``
#: still decides how to degrade; this module only avoids re-parsing the same
#: broken bytes on every call in between.
_CACHEABLE_LOAD_FAILURES: Final[tuple[type[Exception], ...]] = (
    ValidationError,
    OSError,
    ValueError,
    RuntimeError,
)

_LOCK: Final[threading.Lock] = threading.Lock()
_CACHE: dict[Path, tuple[tuple[int, int], Config | Exception]] = {}


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
    A raised failure is cached under the SAME signature as a successful parse
    would be (RV7-M1 item 3): while the file's ``(st_mtime_ns, st_size)``
    stays unchanged, a second call re-raises the cached exception instead of
    re-parsing the same broken bytes, so a syntactically broken config costs
    one parse per edit rather than one per hook event.
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
            if isinstance(result, Exception):
                raise result
            return result

        try:
            config = Config.load_or_default(resolved)
        except _CACHEABLE_LOAD_FAILURES as exc:
            _CACHE[resolved] = (signature, exc)
            raise
        _CACHE[resolved] = (signature, config)
        return config


def reset_config_cache() -> None:
    """Drop every entry. For tests, and for a deliberate in-process reload."""
    with _LOCK:
        _CACHE.clear()
