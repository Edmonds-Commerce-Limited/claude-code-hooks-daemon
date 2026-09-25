"""Undo journal for handler state mutated before the chain has decided.

Plan 00242, Phase 2. A rate limiter or state writer (``command_hints``'
per-hint TTL, ``recovery_cron_advisor``'s per-plan advice counters) mutates
handler-owned state inside ``handle()``, which runs BEFORE the chain's final
decision is known. If the tool call is then denied by another handler, the
cooldown was spent on a call that never ran and the next real call is
silenced. The journal keeps ``handle()`` simple — mutate as before, but
``snapshot()`` every key first — and lets ``Handler.commit_side_effects()``
either ``commit()`` (the call went ahead) or ``rollback()`` (it was denied).

A snapshot copies the value shallowly (``copy.copy``), which is enough for
the flat dataclass / scalar values these maps hold; a value holding nested
mutable state would need a deeper copy, so keep journalled state flat.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, MutableMapping
from enum import Enum
from typing import TypeVar

K = TypeVar("K")
V = TypeVar("V")


class _Absent(Enum):
    """Sentinel for "no such key", distinct from any value a map can hold."""

    KEY = "absent"


class SideEffectJournal:
    """Records how to undo each mutation a handler is about to make.

    The undo records are PER THREAD (Plan 00449). The journal lives on a
    handler singleton, ``server.py`` dispatches on a thread pool, and one
    dispatch runs ``handle()`` and ``commit_side_effects()`` on the same
    thread — so a thread's records are exactly one call's records. One shared
    list let a concurrent call's ``commit()`` discard this call's undo
    records, its ``rollback()`` undo this call's mutations, and two rollbacks
    race into ``IndexError`` on ``while undo: undo.pop()``.
    """

    __slots__ = ("_local",)

    def __init__(self) -> None:
        self._local = threading.local()

    @property
    def _undo(self) -> list[Callable[[], None]]:
        """This thread's undo records, created on first use."""
        undo: list[Callable[[], None]] | None = getattr(self._local, "undo", None)
        if undo is None:
            undo = []
            self._local.undo = undo
        return undo

    @property
    def pending(self) -> int:
        """Number of snapshots this thread took since its last commit/rollback."""
        return len(self._undo)

    def snapshot(self, mapping: MutableMapping[K, V], key: K) -> None:
        """Record ``mapping[key]``'s current state so it can be restored.

        Call BEFORE mutating the entry (overwrite, in-place change, delete
        or insert). Restoring an absent key deletes whatever was inserted.

        The key is read ONCE: ``key in mapping`` followed by ``mapping[key]``
        would raise if another thread evicted the key in between.
        """
        current = mapping.get(key, _Absent.KEY)
        if current is _Absent.KEY:

            def _remove() -> None:
                mapping.pop(key, None)

            self._undo.append(_remove)
            return

        restored = copy.copy(current)

        def _restore() -> None:
            mapping[key] = restored

        self._undo.append(_restore)

    def commit(self) -> None:
        """Keep every mutation; forget the undo records."""
        self._undo.clear()

    def rollback(self) -> None:
        """Undo every mutation since the last commit/rollback, newest first."""
        while self._undo:
            self._undo.pop()()
