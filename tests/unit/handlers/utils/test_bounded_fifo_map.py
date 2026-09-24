"""The locked bounded-FIFO map behind every handler eviction site (Plan 00449).

Plan 00437 built ``SessionAdviceCounter`` for the two sites that were per-session
rate limits. The other twelve hold sets, tuples, dataclasses and journalled
state, so they share this map instead: every operation atomic, and an insert
that finds the map full evicts the OLDEST entry in the same critical section
that selected it.
"""

from __future__ import annotations

import pytest
from tests.thread_contention import hammer

from claude_code_hooks_daemon.core.side_effect_journal import SideEffectJournal
from claude_code_hooks_daemon.handlers.utils.bounded_fifo_map import BoundedFifoMap

_CAP = 4


def _full(cap: int = _CAP) -> BoundedFifoMap[str, int]:
    fifo: BoundedFifoMap[str, int] = BoundedFifoMap(max_entries=cap)
    for index in range(cap):
        fifo[f"k{index}"] = index
    return fifo


class TestConstruction:
    @pytest.mark.parametrize("cap", [0, -1])
    def test_a_cap_below_one_raises(self, cap: int) -> None:
        with pytest.raises(ValueError, match="max_entries"):
            BoundedFifoMap(max_entries=cap)

    def test_starts_empty(self) -> None:
        assert len(BoundedFifoMap[str, int](max_entries=_CAP)) == 0


class TestMappingBehaviour:
    def test_store_and_read_back(self) -> None:
        fifo: BoundedFifoMap[str, int] = BoundedFifoMap(max_entries=_CAP)
        fifo["a"] = 1
        assert fifo["a"] == 1
        assert "a" in fifo
        assert fifo.get("a") == 1
        assert fifo.get("missing") is None
        assert fifo.get("missing", 7) == 7

    def test_missing_key_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            BoundedFifoMap[str, int](max_entries=_CAP)["missing"]

    def test_iteration_is_insertion_order(self) -> None:
        assert list(_full()) == ["k0", "k1", "k2", "k3"]

    def test_delete_and_pop(self) -> None:
        fifo = _full()
        del fifo["k0"]
        assert fifo.pop("k1") == 1
        assert fifo.pop("k1", None) is None
        assert list(fifo) == ["k2", "k3"]
        with pytest.raises(KeyError):
            fifo.pop("k1")

    def test_clear(self) -> None:
        fifo = _full()
        fifo.clear()
        assert len(fifo) == 0


class TestFifoEviction:
    """Every insert path bounds the map, and always at the OLD end.

    A size assertion alone cannot tell FIFO from LIFO — ``dict.popitem()``
    evicts the NEWEST entry and keeps the size just as well — so each of these
    names which key went.
    """

    def test_item_assignment_evicts_the_oldest(self) -> None:
        fifo = _full()
        fifo["new"] = 99
        assert list(fifo) == ["k1", "k2", "k3", "new"]

    def test_overwriting_a_present_key_evicts_nothing_and_keeps_its_place(self) -> None:
        fifo = _full()
        fifo["k0"] = 100
        assert list(fifo) == ["k0", "k1", "k2", "k3"]
        assert fifo["k0"] == 100

    def test_get_or_insert_evicts_the_oldest_and_returns_the_stored_value(self) -> None:
        fifo = _full()
        assert fifo.get_or_insert("new", 5) == 5
        assert fifo.get_or_insert("new", 6) == 5
        assert list(fifo) == ["k1", "k2", "k3", "new"]

    def test_inherited_setdefault_is_bounded_too(self) -> None:
        fifo = _full()
        assert fifo.setdefault("new", 5) == 5
        assert list(fifo) == ["k1", "k2", "k3", "new"]

    def test_insert_if_absent_claims_once(self) -> None:
        fifo = _full()
        assert fifo.insert_if_absent("new", 5) is True
        assert fifo.insert_if_absent("new", 6) is False
        assert fifo["new"] == 5
        assert list(fifo) == ["k1", "k2", "k3", "new"]

    def test_popitem_takes_the_oldest(self) -> None:
        fifo = _full()
        assert fifo.popitem() == ("k0", 0)

    def test_the_map_never_exceeds_its_cap(self) -> None:
        fifo: BoundedFifoMap[str, int] = BoundedFifoMap(max_entries=_CAP)
        for index in range(40):
            fifo[f"k{index}"] = index
        assert list(fifo) == ["k36", "k37", "k38", "k39"]


class TestJournalledInsert:
    """A denied call's rollback must restore the map EXACTLY.

    The journal undoes newest-first, so it must meet the new key's removal
    BEFORE the victim's restoration. The other order restores the victim into
    a map that is still full, and the bounded insert evicts an innocent entry.
    """

    def test_rollback_restores_the_evicted_entry_and_evicts_nothing_else(self) -> None:
        fifo = _full()
        journal = SideEffectJournal()
        journal.snapshot(fifo, "new")  # how the sites snapshot before deciding

        fifo.put("new", 99, journal=journal)
        assert "k0" not in fifo

        journal.rollback()
        assert dict(fifo) == {"k0": 0, "k1": 1, "k2": 2, "k3": 3}

    def test_commit_keeps_the_eviction(self) -> None:
        fifo = _full()
        journal = SideEffectJournal()
        fifo.put("new", 99, journal=journal)
        journal.commit()
        journal.rollback()
        assert list(fifo) == ["k1", "k2", "k3", "new"]

    def test_journalled_insert_if_absent_rolls_back_exactly(self) -> None:
        fifo = _full()
        journal = SideEffectJournal()
        assert fifo.insert_if_absent("new", 99, journal=journal) is True
        journal.rollback()
        assert dict(fifo) == {"k0": 0, "k1": 1, "k2": 2, "k3": 3}


class TestConcurrentCallersNeverRaise:
    """Every mutating path, driven from many threads against a FULL map."""

    def test_item_assignment(self) -> None:
        fifo = _full(8)

        def insert(worker: int, index: int) -> None:
            fifo[f"w{worker}-{index}"] = index

        assert not hammer(insert)
        assert len(fifo) == 8

    def test_get_or_insert_and_iteration(self) -> None:
        fifo = _full(8)

        def insert_and_scan(worker: int, index: int) -> None:
            fifo.get_or_insert(f"w{worker}-{index}", index)
            list(fifo)

        assert not hammer(insert_and_scan)
        assert len(fifo) == 8

    def test_journalled_put_with_rollback(self) -> None:
        fifo = _full(8)

        def put_and_roll_back(worker: int, index: int) -> None:
            journal = SideEffectJournal()
            journal.snapshot(fifo, f"w{worker}-{index}")
            fifo.put(f"w{worker}-{index}", index, journal=journal)
            if index % 2:
                journal.rollback()

        assert not hammer(put_and_roll_back)
        assert len(fifo) <= 8
