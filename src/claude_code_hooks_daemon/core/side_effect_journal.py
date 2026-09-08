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
from collections.abc import Callable, MutableMapping
from typing import TypeVar

K = TypeVar("K")
V = TypeVar("V")


class SideEffectJournal:
    """Records how to undo each mutation a handler is about to make."""

    __slots__ = ("_undo",)

    def __init__(self) -> None:
        self._undo: list[Callable[[], None]] = []

    @property
    def pending(self) -> int:
        """Number of snapshots taken since the last commit/rollback."""
        return len(self._undo)

    def snapshot(self, mapping: MutableMapping[K, V], key: K) -> None:
        """Record ``mapping[key]``'s current state so it can be restored.

        Call BEFORE mutating the entry (overwrite, in-place change, delete
        or insert). Restoring an absent key deletes whatever was inserted.
        """
        if key not in mapping:

            def _remove() -> None:
                mapping.pop(key, None)

            self._undo.append(_remove)
            return

        restored = copy.copy(mapping[key])

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
