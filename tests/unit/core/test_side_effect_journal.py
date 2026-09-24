"""Tests for ``SideEffectJournal`` (Plan 00242, Phase 2).

A rate limiter or state writer mutates handler-owned state inside
``handle()``, before the chain's final decision is known. The journal lets it
do so honestly — record the undo for every key it touches — and then either
keep the mutation (the tool call went ahead) or roll it back (the tool call
was denied, so the cooldown was never really spent).
"""

from dataclasses import dataclass

from claude_code_hooks_daemon.core.side_effect_journal import SideEffectJournal
from tests.thread_contention import WORKERS, hammer


@dataclass
class _State:
    fired_at: float
    calls: int = 0


class TestRollback:
    def test_restores_a_value_that_was_overwritten(self) -> None:
        store = {"k": 1}
        journal = SideEffectJournal()
        journal.snapshot(store, "k")
        store["k"] = 2

        journal.rollback()

        assert store == {"k": 1}

    def test_removes_a_key_that_did_not_exist(self) -> None:
        store: dict[str, int] = {}
        journal = SideEffectJournal()
        journal.snapshot(store, "k")
        store["k"] = 2

        journal.rollback()

        assert store == {}

    def test_restores_a_mutable_value_that_was_mutated_in_place(self) -> None:
        state = _State(fired_at=1.0, calls=0)
        store = {"k": state}
        journal = SideEffectJournal()
        journal.snapshot(store, "k")
        store["k"].calls += 1

        journal.rollback()

        assert store["k"].calls == 0

    def test_restores_a_key_that_was_deleted(self) -> None:
        store = {"k": 1}
        journal = SideEffectJournal()
        journal.snapshot(store, "k")
        del store["k"]

        journal.rollback()

        assert store == {"k": 1}

    def test_rollback_is_idempotent_and_clears_the_journal(self) -> None:
        store = {"k": 1}
        journal = SideEffectJournal()
        journal.snapshot(store, "k")
        store["k"] = 2
        journal.rollback()
        store["k"] = 3

        journal.rollback()

        assert store == {"k": 3}
        assert journal.pending == 0


class TestCommit:
    def test_commit_keeps_the_mutation_and_clears_the_journal(self) -> None:
        store = {"k": 1}
        journal = SideEffectJournal()
        journal.snapshot(store, "k")
        store["k"] = 2

        journal.commit()

        assert store == {"k": 2}
        assert journal.pending == 0
        journal.rollback()
        assert store == {"k": 2}

    def test_pending_counts_snapshots(self) -> None:
        journal = SideEffectJournal()
        journal.snapshot({}, "a")
        journal.snapshot({}, "b")
        assert journal.pending == 2

    def test_a_fresh_snapshot_after_commit_only_covers_the_new_mutation(self) -> None:
        store = {"k": 1}
        journal = SideEffectJournal()
        journal.snapshot(store, "k")
        store["k"] = 2
        journal.commit()
        journal.snapshot(store, "k")
        store["k"] = 3

        journal.rollback()

        assert store == {"k": 2}


class TestConcurrentCalls:
    """One journal per handler singleton, one dispatch per worker thread.

    ``server.py`` dispatches on a thread pool, and a dispatch runs its
    handler's ``handle()`` and ``commit_side_effects()`` on the SAME thread, so
    the undo records of one call must belong to that call's thread alone.
    Sharing one list across threads lets call A's ``commit()`` discard call B's
    undo records, lets A's ``rollback()`` undo B's mutations, and lets two
    rollbacks race on ``while undo: undo.pop()`` into ``IndexError``.
    """

    def test_each_thread_commits_and_rolls_back_only_its_own_mutations(self) -> None:
        journal = SideEffectJournal()
        stores: list[dict[str, int]] = [{"k": -1} for _ in range(WORKERS)]
        leaks: list[tuple[int, int, int]] = []

        def call(worker: int, index: int) -> None:
            store = stores[worker]
            before = store["k"]
            journal.snapshot(store, "k")
            store["k"] = index
            if index % 2:
                journal.rollback()
                expected = before
            else:
                journal.commit()
                expected = index
            if store["k"] != expected:
                leaks.append((worker, index, store["k"]))

        errors = hammer(call)

        assert not errors, f"concurrent calls raised: {errors[:3]}"
        assert not leaks, f"another thread's commit or rollback leaked in: {leaks[:3]}"
