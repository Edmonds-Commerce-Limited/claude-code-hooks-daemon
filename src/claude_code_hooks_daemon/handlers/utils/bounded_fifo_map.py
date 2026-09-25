"""A bounded, insertion-ordered map whose every operation is atomic (Plan 00449).

Handlers are daemon-lifetime singletons and dispatch is threaded: ``server.py``
runs ``controller.dispatch`` through ``loop.run_in_executor(None, ...)``, whose
default executor is a ``ThreadPoolExecutor``. A handler that bounds a map by
hand does it in two steps —

    if len(m) >= cap:
        del m[next(iter(m))]

— and two threads reaching a full map select the same victim, so the second
delete raises ``KeyError``; ``next(iter(m))`` raises ``RuntimeError`` if
another thread resizes the map mid-iteration. This map selects and evicts in
one critical section, on every insert path.

``SessionAdviceCounter`` is the sibling for the one shape that is a per-session
rate limit. Everything else — sets of paths, latches, dataclass state,
journalled bookkeeping — uses this. The ``unlocked-select-then-evict`` semgrep
rule (``scripts/qa/semgrep/unlocked-eviction.yaml``) reports a hand-rolled copy.
"""

from __future__ import annotations

import threading
from collections.abc import Hashable, Iterator, MutableMapping
from typing import TYPE_CHECKING, Generic, TypeVar, overload

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.side_effect_journal import SideEffectJournal

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")
D = TypeVar("D")

_MISSING = object()


class BoundedFifoMap(MutableMapping[K, V], Generic[K, V]):
    """A ``dict`` capped at ``max_entries`` that evicts its OLDEST entry.

    Every insert path — item assignment, :meth:`put`, :meth:`get_or_insert`,
    :meth:`insert_if_absent` — adds a NEW key to a full map by first evicting
    the oldest-inserted entry (FIFO). Overwriting a key already present evicts
    nothing and keeps its position. FIFO rather than LIFO matters: evicting the
    newest makes the last slot a revolving door, so whichever key arrived just
    after the cap was reached is dropped again on every subsequent insert.

    Iteration walks a snapshot taken under the lock, so a reader never sees
    ``RuntimeError: dictionary changed size during iteration``.

    Args:
        max_entries: The cap. Must be at least 1.
    """

    def __init__(self, *, max_entries: int) -> None:
        if max_entries < 1:
            raise ValueError(f"max_entries must be >= 1, got {max_entries}")
        self._max_entries = max_entries
        self._data: dict[K, V] = {}
        # Re-entrant because a journalled insert calls SideEffectJournal.snapshot,
        # which reads this map back through the public API while the lock is held.
        self._lock = threading.RLock()

    # ── Reads ────────────────────────────────────────────────────────────────

    def __getitem__(self, key: K) -> V:
        with self._lock:
            return self._data[key]

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._data

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __iter__(self) -> Iterator[K]:
        with self._lock:
            keys = list(self._data)
        return iter(keys)

    @overload
    def get(self, key: K, /) -> V | None: ...

    @overload
    def get(self, key: K, default: V | D, /) -> V | D: ...

    def get(self, key: K, default: object = None, /) -> object:
        with self._lock:
            return self._data.get(key, default)

    # ── Inserts (bounded) ────────────────────────────────────────────────────

    def __setitem__(self, key: K, value: V) -> None:
        self.put(key, value)

    def put(self, key: K, value: V, *, journal: SideEffectJournal | None = None) -> None:
        """Store ``value``, evicting the oldest entry if ``key`` is new and the map full.

        With a ``journal``, the victim and then ``key`` are snapshotted before
        either is touched. That order is what makes a rollback exact: undoing
        newest-first removes ``key`` BEFORE restoring the victim, so the
        restoration lands in a map with room and evicts nothing else.
        """
        with self._lock:
            self._insert(key, value, journal)

    def get_or_insert(self, key: K, default: V) -> V:
        """Return the value for ``key``, inserting ``default`` (bounded) if absent.

        The atomic form of ``setdefault``. The inherited ``setdefault`` is a
        read and then a write, so two callers racing on one new key can each
        insert their own default and one of them keeps a value the map dropped.
        """
        with self._lock:
            if key in self._data:
                return self._data[key]
            self._insert(key, default, None)
            return default

    def insert_if_absent(
        self, key: K, value: V, *, journal: SideEffectJournal | None = None
    ) -> bool:
        """Insert ``value`` (bounded) only if ``key`` is absent; True if it was.

        The check and the insert are one step, so exactly one of any number of
        concurrent callers claims a key — the "first time only" shape.
        """
        with self._lock:
            if key in self._data:
                return False
            self._insert(key, value, journal)
            return True

    def _insert(self, key: K, value: V, journal: SideEffectJournal | None) -> None:
        """Bounded insert.

        Callers already hold the lock; taking it again (it is re-entrant) keeps
        the select-then-evict visibly inside it, which is what the semgrep rule
        checks.
        """
        with self._lock:
            if key not in self._data and len(self._data) >= self._max_entries:
                victim = next(iter(self._data))
                if journal is not None:
                    journal.snapshot(self, victim)
                del self._data[victim]
            if journal is not None:
                journal.snapshot(self, key)
            self._data[key] = value

    # ── Removals ─────────────────────────────────────────────────────────────

    def __delitem__(self, key: K) -> None:
        with self._lock:
            del self._data[key]

    @overload
    def pop(self, key: K, /) -> V: ...

    @overload
    def pop(self, key: K, default: V | D, /) -> V | D: ...

    def pop(self, key: K, default: object = _MISSING, /) -> object:
        with self._lock:
            if default is _MISSING:
                return self._data.pop(key)
            return self._data.pop(key, default)

    def popitem(self) -> tuple[K, V]:
        """Remove and return the OLDEST entry (FIFO, unlike ``dict.popitem``)."""
        with self._lock:
            if not self._data:
                raise KeyError("popitem(): map is empty")
            key = next(iter(self._data))
            return key, self._data.pop(key)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
