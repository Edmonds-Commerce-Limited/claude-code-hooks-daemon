"""Tests for core.bounded_dispatch (Plan 00466 N34).

N25 (Plan 00466) closed the case where the CLIENT's own socket timeout let a
slow handler bypass every guard behind it, by checking a per-event deadline
BETWEEN handlers. That check cannot catch a handler slow within its OWN
``matches()``/``handle()`` call -- the exact shape ``secret_file_guard``
takes on multi-MB input (measured at 48.958s on 4 MB, past both the 20s
chain deadline and the 30s client timeout). ``BoundedDispatcher`` closes
that gap: the CALLER's wait on a handler's own work is what is bounded,
via ``Future.result(timeout=...)``, not the handler's code itself (which
Python threads cannot forcibly interrupt).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.bounded_dispatch import (
    DISPATCH_MAX_INFLIGHT,
    BoundedDispatcher,
    DispatchSaturated,
    DispatchTimeout,
    configure_default_dispatcher,
    get_default_dispatcher,
    reset_default_dispatcher_for_tests,
)
from tests.dispatch_timeouts import DispatchTestTimeout


class TestBoundedDispatcherCompletesWithinBudget:
    """The common case: the call finishes before its timeout."""

    def test_returns_the_callables_own_result(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=4)
        try:
            outcome = dispatcher.run(lambda: 42, timeout=DispatchTestTimeout.NORMAL, label="fast")
        finally:
            dispatcher.shutdown()
        assert outcome == 42

    def test_propagates_an_exception_raised_inside_the_callable(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=4)

        def _boom() -> None:
            raise ValueError("boom")

        try:
            raised = None
            try:
                dispatcher.run(_boom, timeout=DispatchTestTimeout.NORMAL, label="raiser")
            except ValueError as exc:
                raised = exc
        finally:
            dispatcher.shutdown()
        assert raised is not None
        assert str(raised) == "boom"


class TestBoundedDispatcherTimesOut:
    """A callable that outruns its budget is abandoned, not waited on."""

    def test_returns_dispatch_timeout_without_waiting_for_completion(self) -> None:
        """Proved by order, not by a stopwatch: the callable cannot finish
        until the test releases it, and run() has already returned by then."""
        dispatcher = BoundedDispatcher(max_inflight=4)
        release = threading.Event()
        finished = threading.Event()

        def _blocked() -> str:
            release.wait(timeout=DispatchTestTimeout.GENEROUS)
            finished.set()
            return "late"

        try:
            outcome = dispatcher.run(_blocked, timeout=DispatchTestTimeout.SHORT, label="slow")
            returned_before_completion = not finished.is_set()
        finally:
            release.set()
            dispatcher.shutdown(wait=True)

        assert isinstance(outcome, DispatchTimeout)
        assert returned_before_completion

    def test_the_stray_worker_still_runs_to_completion_in_the_background(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=4)
        release = threading.Event()
        completed = threading.Event()

        def _blocked() -> None:
            release.wait(timeout=DispatchTestTimeout.GENEROUS)
            completed.set()

        try:
            outcome = dispatcher.run(_blocked, timeout=DispatchTestTimeout.VERY_SHORT, label="slow")
            assert isinstance(outcome, DispatchTimeout)
            assert not completed.is_set()  # abandoned while still blocked
            release.set()
            assert completed.wait(timeout=DispatchTestTimeout.NORMAL)  # and it DOES finish
        finally:
            release.set()
            dispatcher.shutdown(wait=True)


class TestBoundedDispatcherSaturation:
    """A pool with no free capacity fails closed instead of queuing."""

    def test_saturated_pool_returns_dispatch_saturated_immediately(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=1, slot_wait_seconds=0.0)
        occupied = threading.Event()
        release = threading.Event()

        def _occupy() -> None:
            occupied.set()
            release.wait(timeout=DispatchTestTimeout.GENEROUS)

        filler_thread: threading.Thread | None = None
        try:
            # Fill the one slot with a call that will not finish until we
            # release it.
            filler_thread = threading.Thread(
                target=lambda: dispatcher.run(
                    _occupy, timeout=DispatchTestTimeout.GENEROUS, label="filler"
                )
            )
            filler_thread.start()
            assert occupied.wait(timeout=DispatchTestTimeout.NORMAL)

            ran = threading.Event()

            def _second() -> str:
                ran.set()
                return "unreachable"

            outcome = dispatcher.run(_second, timeout=DispatchTestTimeout.GENEROUS, label="second")
        finally:
            release.set()
            if filler_thread is not None:
                filler_thread.join(timeout=DispatchTestTimeout.GENEROUS)
            dispatcher.shutdown(wait=True)

        assert isinstance(outcome, DispatchSaturated)
        # Refused, not queued: it never ran, even once the slot was freed.
        assert not ran.is_set()


class TestBoundedDispatcherReleasesAbandonedSlot:
    """Plan 00466 N40 M2: a timed-out call's SEMAPHORE PERMIT is released the
    moment the caller gives up waiting on it, not when the straggler
    eventually finishes -- otherwise enough abandoned stragglers deny every
    future dispatch permanently (the review's own 16-straggler reproducer),
    with no way out short of a manual restart.
    """

    def test_a_new_dispatch_can_proceed_immediately_after_a_timeout(self) -> None:
        # `max_stragglers` set explicitly and higher than `max_inflight`, so
        # this test isolates the PERMIT release from the separate straggler
        # cap (covered by `TestBoundedDispatcherBoundsStragglers` below).
        dispatcher = BoundedDispatcher(max_inflight=1, max_stragglers=4)
        started = threading.Event()
        release = threading.Event()

        def _stuck() -> None:
            started.set()
            release.wait(timeout=DispatchTestTimeout.GENEROUS)

        try:
            outcome = dispatcher.run(_stuck, timeout=DispatchTestTimeout.SHORT, label="stuck")
            assert isinstance(outcome, DispatchTimeout)
            assert started.wait(timeout=DispatchTestTimeout.NORMAL)

            # The one and only inflight slot is "occupied" by `_stuck`, which
            # is STILL RUNNING -- but the permit was released at the timeout,
            # so a fresh call is not saturated.
            second_outcome = dispatcher.run(
                lambda: "ok", timeout=DispatchTestTimeout.NORMAL, label="second"
            )
        finally:
            release.set()
            dispatcher.shutdown(wait=True)

        assert second_outcome == "ok"

    def test_straggler_does_not_release_the_slot_twice(self) -> None:
        """The straggler's own eventual completion must not over-release the
        semaphore a second time (that would let capacity silently grow past
        `max_inflight`, or raise on a `BoundedSemaphore`)."""
        dispatcher = BoundedDispatcher(max_inflight=1)
        release = threading.Event()

        def _blocked() -> None:
            release.wait(timeout=DispatchTestTimeout.GENEROUS)

        try:
            outcome = dispatcher.run(_blocked, timeout=DispatchTestTimeout.VERY_SHORT, label="slow")
            assert isinstance(outcome, DispatchTimeout)
            release.set()
            # The worker's `finally` (the second release attempt) has run once
            # it leaves the straggler set.
            while dispatcher.straggler_health().count:
                time.sleep(DispatchTestTimeout.INSTANT)

            # Two more dispatches must both succeed -- if the straggler's own
            # completion had released a SECOND permit, `max_inflight=1` would
            # let two concurrent calls both acquire, silently doubling
            # capacity instead of raising.
            first = dispatcher.run(lambda: "a", timeout=DispatchTestTimeout.NORMAL, label="a")
            second = dispatcher.run(lambda: "b", timeout=DispatchTestTimeout.NORMAL, label="b")
        finally:
            dispatcher.shutdown(wait=True)

        assert first == "a"
        assert second == "b"


class TestBoundedDispatcherWorkerFinishingAtItsDeadline:
    """A worker that finishes after the caller's timeout fires but before the
    caller records it must not leave a straggler entry for a dead thread."""

    def test_no_straggler_entry_when_the_worker_finishes_before_it_is_recorded(self) -> None:
        dispatcher: BoundedDispatcher[str] = BoundedDispatcher(max_inflight=2, max_stragglers=4)
        release = threading.Event()
        worker: list[threading.Thread] = []

        def _fn() -> str:
            worker.append(threading.current_thread())
            release.wait(timeout=DispatchTestTimeout.GENEROUS)
            return "late"

        original_result = Future.result

        def _result(self: Future[str], timeout: float | None = None) -> str:
            try:
                return original_result(self, timeout)
            except FutureTimeoutError:
                # The timeout fired; now let the worker finish COMPLETELY (its
                # `finally` included) before the caller records the straggler.
                release.set()
                worker[0].join(timeout=DispatchTestTimeout.NORMAL)
                raise

        try:
            with patch.object(Future, "result", _result):
                outcome = dispatcher.run(_fn, timeout=DispatchTestTimeout.SHORT, label="edge")
        finally:
            release.set()
            dispatcher.shutdown(wait=True)

        assert isinstance(outcome, DispatchTimeout)
        assert dispatcher.straggler_health().count == 0


class TestBoundedDispatcherStragglerHealth:
    """Plan 00466 N40 M2: stragglers are tracked (count + oldest age) so the
    daemon can report DEGRADED health and eventually self-restart."""

    def test_no_stragglers_reports_zero_health(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=4)
        try:
            health = dispatcher.straggler_health()
        finally:
            dispatcher.shutdown(wait=True)
        assert health.count == 0
        assert health.oldest_age_seconds == 0.0

    def test_a_timed_out_call_is_counted_until_it_finishes(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=4)
        release = threading.Event()

        def _stuck() -> None:
            release.wait(timeout=DispatchTestTimeout.GENEROUS)

        try:
            outcome = dispatcher.run(_stuck, timeout=DispatchTestTimeout.VERY_SHORT, label="stuck")
            assert isinstance(outcome, DispatchTimeout)

            health = dispatcher.straggler_health()
            assert health.count == 1
            assert health.oldest_age_seconds > 0.0

            release.set()
            # The worker's `finally` removes it; no wall-clock bound on when,
            # since release.wait() returning guarantees it gets there.
            while dispatcher.straggler_health().count:
                time.sleep(DispatchTestTimeout.INSTANT)
            assert dispatcher.straggler_health().count == 0
        finally:
            release.set()
            dispatcher.shutdown(wait=True)

    def test_multiple_stragglers_report_the_oldest_age(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=4)
        release = threading.Event()

        def _stuck() -> None:
            release.wait(timeout=DispatchTestTimeout.GENEROUS)

        try:
            dispatcher.run(_stuck, timeout=DispatchTestTimeout.VERY_SHORT, label="first")
            time.sleep(0.1)
            dispatcher.run(_stuck, timeout=DispatchTestTimeout.VERY_SHORT, label="second")
            time.sleep(0.02)

            health = dispatcher.straggler_health()
            assert health.count == 2
            # The FIRST straggler is older than the second by roughly the
            # 0.1s gap between the two `run()` calls above.
            assert health.oldest_age_seconds > 0.08
        finally:
            release.set()
            dispatcher.shutdown(wait=True)


class TestBoundedDispatcherBoundsStragglers:
    """Plan 00466 N40 M2: releasing the semaphore permit on timeout (above)
    reopened a gap -- an unbounded number of abandoned stragglers could pile
    up, each still consuming a thread and (for a CPU-bound one) real CPU,
    even though `max_inflight` no longer limits them. A SEPARATE cap on the
    number of live stragglers closes it: once reached, a NEW dispatch is
    refused outright, independent of ordinary inflight capacity.
    """

    def test_new_dispatch_refused_once_straggler_cap_reached_even_with_free_inflight_capacity(
        self,
    ) -> None:
        dispatcher = BoundedDispatcher(max_inflight=4, max_stragglers=1)
        release = threading.Event()

        def _stuck() -> None:
            release.wait(timeout=DispatchTestTimeout.GENEROUS)

        try:
            outcome = dispatcher.run(_stuck, timeout=DispatchTestTimeout.VERY_SHORT, label="stuck")
            assert isinstance(outcome, DispatchTimeout)
            time.sleep(0.05)
            assert dispatcher.straggler_health().count == 1

            # `max_inflight=4` has plenty of free capacity -- the straggler
            # cap must refuse this on its own.
            second_outcome = dispatcher.run(
                lambda: "unreachable", timeout=DispatchTestTimeout.NORMAL, label="second"
            )
        finally:
            release.set()
            dispatcher.shutdown(wait=True)

        assert isinstance(second_outcome, DispatchSaturated)

    def test_health_says_when_the_cap_is_reached(self) -> None:
        """Plan 00466 N40 review 2 mA3: at the cap every new dispatch is
        refused, which the daemon's watchdog treats as grounds to restart now."""
        dispatcher = BoundedDispatcher(max_inflight=4, max_stragglers=2)
        release = threading.Event()

        def _stuck() -> None:
            release.wait(timeout=DispatchTestTimeout.GENEROUS)

        try:
            assert dispatcher.straggler_health().at_capacity is False
            # run() records a straggler before it returns DispatchTimeout, so
            # the count is exact the moment each call comes back.
            dispatcher.run(_stuck, timeout=DispatchTestTimeout.VERY_SHORT, label="first")
            health = dispatcher.straggler_health()
            assert (health.count, health.at_capacity) == (1, False)
            dispatcher.run(_stuck, timeout=DispatchTestTimeout.VERY_SHORT, label="second")
            health = dispatcher.straggler_health()
            assert (health.count, health.at_capacity) == (2, True)
        finally:
            release.set()
            dispatcher.shutdown(wait=True)

    def test_max_stragglers_defaults_to_max_inflight(self) -> None:
        """No explicit `max_stragglers` reuses `max_inflight` (Single Source
        of Truth: one dial governs both, unless a caller opts to split
        them)."""
        dispatcher = BoundedDispatcher(max_inflight=2)
        release = threading.Event()

        def _stuck() -> None:
            release.wait(timeout=DispatchTestTimeout.GENEROUS)

        try:
            dispatcher.run(_stuck, timeout=DispatchTestTimeout.VERY_SHORT, label="first")
            time.sleep(0.02)
            outcome = dispatcher.run(_stuck, timeout=DispatchTestTimeout.VERY_SHORT, label="second")
            assert isinstance(outcome, DispatchTimeout)
            time.sleep(0.02)
            assert dispatcher.straggler_health().count == 2

            # A third dispatch is refused: 2 stragglers already == max_inflight (2).
            third = dispatcher.run(
                lambda: "unreachable", timeout=DispatchTestTimeout.NORMAL, label="third"
            )
        finally:
            release.set()
            dispatcher.shutdown(wait=True)

        assert isinstance(third, DispatchSaturated)


class TestBoundedDispatcherHandlesBaseException:
    """Plan 00466 N40 M2 (review m3): the worker only caught ``Exception``,
    so a ``BaseException`` raised inside the callable (``SystemExit``,
    ``KeyboardInterrupt``) never resolved the future -- the caller then
    waited out its FULL timeout for a verdict that was never coming,
    instead of failing fast."""

    def test_a_base_exception_resolves_the_future_instead_of_hanging(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=4)

        def _raises_system_exit() -> None:
            raise SystemExit(1)

        try:
            raised = None
            outcome: object = None
            try:
                outcome = dispatcher.run(
                    _raises_system_exit, timeout=DispatchTestTimeout.GENEROUS, label="quitter"
                )
            except SystemExit as exc:
                raised = exc
        finally:
            dispatcher.shutdown(wait=True)

        # An unresolved future would have waited out the timeout and come back
        # as DispatchTimeout; the exception itself proves it was resolved.
        assert raised is not None
        assert outcome is None

    def test_the_permit_is_still_released_after_a_base_exception(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=1)

        def _raises_keyboard_interrupt() -> None:
            raise KeyboardInterrupt

        try:
            with contextlib.suppress(KeyboardInterrupt):
                dispatcher.run(
                    _raises_keyboard_interrupt,
                    timeout=DispatchTestTimeout.GENEROUS,
                    label="ctrl-c",
                )

            # If the permit leaked, this second call would saturate instead.
            outcome = dispatcher.run(
                lambda: "ok", timeout=DispatchTestTimeout.NORMAL, label="second"
            )
        finally:
            dispatcher.shutdown(wait=True)

        assert outcome == "ok"


@contextlib.contextmanager
def _every_slot_held(dispatcher: BoundedDispatcher[object]) -> Iterator[threading.Event]:
    """Fill every ``max_inflight`` slot of ``dispatcher`` with a blocked call.

    Yields the event that releases them; it is set again on exit, so the
    holders always finish before the dispatcher is shut down.
    """
    release = threading.Event()
    holders: list[threading.Thread] = []
    started = threading.Semaphore(0)

    def _hold() -> None:
        started.release()
        release.wait(timeout=DispatchTestTimeout.GENEROUS)

    try:
        for index in range(dispatcher.max_inflight):
            holder = threading.Thread(
                target=dispatcher.run,
                args=(_hold,),
                kwargs={"timeout": DispatchTestTimeout.GENEROUS, "label": f"holder-{index}"},
            )
            holder.start()
            holders.append(holder)
            assert started.acquire(timeout=DispatchTestTimeout.NORMAL)
        yield release
    finally:
        release.set()
        for holder in holders:
            holder.join(timeout=DispatchTestTimeout.GENEROUS)


class TestBoundedDispatcherWaitsForASlot:
    """Plan 00533 (issue #124): a full pool waits a short, bounded time for a
    slot before refusing, so a burst one call over the limit is served."""

    def test_a_slot_freed_during_the_wait_is_taken(self) -> None:
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=1, slot_wait_seconds=DispatchTestTimeout.GENEROUS
        )
        try:
            with _every_slot_held(dispatcher) as release:
                # Freed only after run() below has found the pool full.
                timer = threading.Timer(DispatchTestTimeout.SHORT, release.set)
                timer.start()
                outcome = dispatcher.run(
                    lambda: "served", timeout=DispatchTestTimeout.GENEROUS, label="waiter"
                )
                timer.join()
        finally:
            dispatcher.shutdown(wait=True)
        assert outcome == "served"

    def test_the_wait_is_bounded_and_then_refused(self) -> None:
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=1, slot_wait_seconds=DispatchTestTimeout.SHORT
        )
        try:
            with _every_slot_held(dispatcher):
                started = time.monotonic()
                outcome = dispatcher.run(
                    lambda: "unreachable", timeout=DispatchTestTimeout.GENEROUS, label="waiter"
                )
                waited = time.monotonic() - started
        finally:
            dispatcher.shutdown(wait=True)
        assert isinstance(outcome, DispatchSaturated)
        assert DispatchTestTimeout.SHORT <= waited < DispatchTestTimeout.GENEROUS

    def test_the_wait_never_outlasts_the_calls_own_timeout(self) -> None:
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=1, slot_wait_seconds=DispatchTestTimeout.OUTER_BOUND
        )
        try:
            with _every_slot_held(dispatcher):
                started = time.monotonic()
                outcome = dispatcher.run(
                    lambda: "unreachable", timeout=DispatchTestTimeout.SHORT, label="waiter"
                )
                waited = time.monotonic() - started
        finally:
            dispatcher.shutdown(wait=True)
        assert isinstance(outcome, DispatchSaturated)
        assert waited < DispatchTestTimeout.GENEROUS

    def test_time_spent_waiting_is_taken_from_the_calls_timeout(self) -> None:
        """A call that waited most of its budget for a slot does not then get
        the whole budget again to run in."""
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=1, slot_wait_seconds=DispatchTestTimeout.GENEROUS
        )
        never = threading.Event()
        try:
            with _every_slot_held(dispatcher) as release:
                timer = threading.Timer(DispatchTestTimeout.NORMAL / 2, release.set)
                timer.start()
                started = time.monotonic()
                outcome = dispatcher.run(
                    lambda: never.wait(timeout=DispatchTestTimeout.GENEROUS),
                    timeout=DispatchTestTimeout.NORMAL,
                    label="waiter",
                )
                elapsed = time.monotonic() - started
                timer.join()
        finally:
            never.set()
            dispatcher.shutdown(wait=True)
        assert isinstance(outcome, DispatchTimeout)
        assert elapsed < DispatchTestTimeout.NORMAL * 1.5

    def test_the_defaults_are_the_shipped_ones(self) -> None:
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher()
        assert dispatcher.max_inflight == DISPATCH_MAX_INFLIGHT == 16
        assert dispatcher.slot_wait_seconds == Timeout.DISPATCH_SLOT_WAIT_SECONDS
        assert dispatcher.max_exempt_inflight == Timeout.DISPATCH_EXEMPT_MAX_INFLIGHT == 2

    def test_a_slot_won_with_no_time_left_to_run_in_is_refused(self) -> None:
        """A slot freed at the very end of the wait leaves the call too little
        of its budget to be judged in. Running it anyway reports a dispatch
        timeout for a call that never had a chance; it is refused instead,
        and the slot goes straight back."""
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=1, slot_wait_seconds=DispatchTestTimeout.GENEROUS
        )
        slot = _LastMomentSlot()
        ran = threading.Event()
        try:
            with patch.object(dispatcher, "_semaphore", slot):
                outcome = dispatcher.run(
                    ran.set, timeout=DispatchTestTimeout.SHORT, label="last-moment"
                )
        finally:
            dispatcher.shutdown(wait=True)
        assert isinstance(outcome, DispatchSaturated)
        assert not ran.is_set()
        assert slot.released == 1


class _LastMomentSlot:
    """A semaphore whose only slot frees up exactly as the wait for it ends."""

    def __init__(self) -> None:
        self.released = 0

    def acquire(self, blocking: bool = True, timeout: float | None = None) -> bool:
        if not blocking:
            return False
        if timeout is not None:
            time.sleep(timeout)
        return True

    def release(self) -> None:
        self.released += 1


class TestBoundedDispatcherCapacityExemptCalls:
    """Plan 00533 (issue #124): the daemon's own recovery command must be
    judged even when every slot is taken, or nothing can recover the pool."""

    def test_an_exempt_call_runs_while_the_pool_is_full(self) -> None:
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=1, slot_wait_seconds=0.0
        )
        try:
            with _every_slot_held(dispatcher):
                outcome = dispatcher.run(
                    lambda: "judged",
                    timeout=DispatchTestTimeout.GENEROUS,
                    label="recovery",
                    capacity_exempt=True,
                )
        finally:
            dispatcher.shutdown(wait=True)
        assert outcome == "judged"

    def test_an_exempt_call_runs_while_the_straggler_cap_is_reached(self) -> None:
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=2, max_stragglers=1, slot_wait_seconds=0.0
        )
        release = threading.Event()
        try:
            stuck = dispatcher.run(
                lambda: release.wait(timeout=DispatchTestTimeout.GENEROUS),
                timeout=DispatchTestTimeout.VERY_SHORT,
                label="straggler",
            )
            assert isinstance(stuck, DispatchTimeout)
            outcome = dispatcher.run(
                lambda: "judged",
                timeout=DispatchTestTimeout.GENEROUS,
                label="recovery",
                capacity_exempt=True,
            )
        finally:
            release.set()
            dispatcher.shutdown(wait=True)
        assert outcome == "judged"

    def test_an_exempt_call_that_times_out_releases_no_permit_it_never_took(self) -> None:
        """A BoundedSemaphore raises on over-release, so a release here would
        surface as an exception from the timed-out call."""
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=1, slot_wait_seconds=0.0
        )
        release = threading.Event()
        try:
            outcome = dispatcher.run(
                lambda: release.wait(timeout=DispatchTestTimeout.GENEROUS),
                timeout=DispatchTestTimeout.VERY_SHORT,
                label="recovery",
                capacity_exempt=True,
            )
            release.set()
            dispatcher.shutdown(wait=True)
            # The single ordinary slot is still exactly one slot.
            after = dispatcher.run(lambda: "ok", timeout=DispatchTestTimeout.NORMAL, label="next")
        finally:
            release.set()
            dispatcher.shutdown(wait=True)
        assert isinstance(outcome, DispatchTimeout)
        assert after == "ok"

    def test_exempt_calls_have_a_small_bounded_pool_of_their_own(self) -> None:
        """status and logs are exempt and routinely run, so against a wedged
        handler each would be another straggler: they cannot pile up past
        their own cap, which never touches the ordinary pool."""
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=1, slot_wait_seconds=0.0
        )
        release = threading.Event()
        started = threading.Semaphore(0)

        def _hold() -> None:
            started.release()
            release.wait(timeout=DispatchTestTimeout.GENEROUS)

        holders = [
            threading.Thread(
                target=dispatcher.run,
                args=(_hold,),
                kwargs={
                    "timeout": DispatchTestTimeout.GENEROUS,
                    "label": f"exempt-{index}",
                    "capacity_exempt": True,
                },
            )
            for index in range(dispatcher.max_exempt_inflight)
        ]
        try:
            for holder in holders:
                holder.start()
                assert started.acquire(timeout=DispatchTestTimeout.NORMAL)
            over_cap = dispatcher.run(
                lambda: "unreachable",
                timeout=DispatchTestTimeout.GENEROUS,
                label="one-too-many",
                capacity_exempt=True,
            )
            ordinary = dispatcher.run(
                lambda: "ok", timeout=DispatchTestTimeout.NORMAL, label="ordinary"
            )
        finally:
            release.set()
            for holder in holders:
                holder.join(timeout=DispatchTestTimeout.GENEROUS)
            dispatcher.shutdown(wait=True)
        assert isinstance(over_cap, DispatchSaturated)
        assert ordinary == "ok"

    def test_an_exempt_straggler_keeps_its_exempt_slot_until_it_finishes(self) -> None:
        """Releasing it on timeout, as an ordinary call does, would let
        stragglers of a wedged handler accumulate without limit again."""
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=1, max_exempt_inflight=1, slot_wait_seconds=0.0
        )
        release = threading.Event()
        try:
            stuck = dispatcher.run(
                lambda: release.wait(timeout=DispatchTestTimeout.GENEROUS),
                timeout=DispatchTestTimeout.VERY_SHORT,
                label="exempt-straggler",
                capacity_exempt=True,
            )
            while_stuck = dispatcher.run(
                lambda: "unreachable",
                timeout=DispatchTestTimeout.NORMAL,
                label="exempt",
                capacity_exempt=True,
            )
            release.set()
            dispatcher.shutdown(wait=True)
            after = dispatcher.run(
                lambda: "judged",
                timeout=DispatchTestTimeout.NORMAL,
                label="exempt",
                capacity_exempt=True,
            )
        finally:
            release.set()
            dispatcher.shutdown(wait=True)
        assert isinstance(stuck, DispatchTimeout)
        assert isinstance(while_stuck, DispatchSaturated)
        assert after == "judged"

    def test_an_exempt_straggler_does_not_use_up_the_ordinary_straggler_cap(self) -> None:
        """Its own exempt slot bounds it, so a wedged recovery command must
        not refuse ordinary chains by filling the ordinary straggler cap."""
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=2, max_stragglers=1, slot_wait_seconds=0.0
        )
        release = threading.Event()
        try:
            stuck = dispatcher.run(
                lambda: release.wait(timeout=DispatchTestTimeout.GENEROUS),
                timeout=DispatchTestTimeout.VERY_SHORT,
                label="exempt-straggler",
                capacity_exempt=True,
            )
            health = dispatcher.straggler_health()
            ordinary = dispatcher.run(
                lambda: "ok", timeout=DispatchTestTimeout.NORMAL, label="ordinary"
            )
        finally:
            release.set()
            dispatcher.shutdown(wait=True)
        assert isinstance(stuck, DispatchTimeout)
        assert health.at_capacity is False
        assert ordinary == "ok"


class _FakeClock:
    """A monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestBoundedDispatcherWarnsOnSustainedSaturation:
    """Plan 00533 (issue #124): six minutes of refusals left no single line
    saying how long the pool had been full. One rate-limited WARNING does."""

    _SUSTAINED = "Dispatch pool saturated for"

    def _refuse(self, dispatcher: BoundedDispatcher[object]) -> None:
        outcome = dispatcher.run(lambda: None, timeout=DispatchTestTimeout.NORMAL, label="refused")
        assert isinstance(outcome, DispatchSaturated)

    def _sustained(self, caplog: pytest.LogCaptureFixture) -> list[str]:
        return [r.getMessage() for r in caplog.records if self._SUSTAINED in r.getMessage()]

    def _refuse_every_second(
        self, dispatcher: BoundedDispatcher[object], clock: _FakeClock, seconds: int
    ) -> None:
        """Advance the clock a second at a time, one refusal at each step."""
        for _ in range(seconds):
            clock.now += 1
            self._refuse(dispatcher)

    def test_it_warns_once_saturation_outlasts_the_threshold_and_then_at_an_interval(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        clock = _FakeClock()
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=1, slot_wait_seconds=0.0, clock=clock
        )
        after = int(Timeout.DISPATCH_SATURATION_WARN_AFTER_SECONDS)
        interval = int(Timeout.DISPATCH_SATURATION_WARN_INTERVAL_SECONDS)
        caplog.set_level(logging.WARNING, logger="claude_code_hooks_daemon.core.bounded_dispatch")
        try:
            with _every_slot_held(dispatcher):
                self._refuse(dispatcher)
                self._refuse_every_second(dispatcher, clock, after - 1)
                assert self._sustained(caplog) == []
                self._refuse_every_second(dispatcher, clock, 1)
                assert len(self._sustained(caplog)) == 1
                self._refuse_every_second(dispatcher, clock, interval - 1)
                assert len(self._sustained(caplog)) == 1
                self._refuse_every_second(dispatcher, clock, 1)
                assert len(self._sustained(caplog)) == 2
        finally:
            dispatcher.shutdown(wait=True)
        first, second = self._sustained(caplog)
        # One refusal at the start, then one a second until the threshold.
        assert f"for {after}s: {after + 1} call(s) refused in the last {after}s" in first
        assert f": {interval} call(s) refused in the last {interval}s" in second

    def test_a_slot_won_between_refusals_does_not_end_the_episode(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Under real overload slots churn and some callers win one inside
        the wait, while the rest keep being refused. That is still one
        sustained episode, not many short ones that never reach the
        threshold."""
        clock = _FakeClock()
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=1, slot_wait_seconds=0.0, clock=clock
        )
        caplog.set_level(logging.WARNING, logger="claude_code_hooks_daemon.core.bounded_dispatch")
        try:
            for _ in range(int(Timeout.DISPATCH_SATURATION_WARN_AFTER_SECONDS) + 1):
                with _every_slot_held(dispatcher):
                    self._refuse(dispatcher)
                assert dispatcher.run(lambda: "ok", timeout=DispatchTestTimeout.NORMAL, label="ok")
                clock.now += 1
        finally:
            dispatcher.shutdown(wait=True)
        assert len(self._sustained(caplog)) == 1

    def test_a_quiet_period_with_no_refusal_ends_the_episode(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        clock = _FakeClock()
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=1, slot_wait_seconds=0.0, clock=clock
        )
        after = int(Timeout.DISPATCH_SATURATION_WARN_AFTER_SECONDS)
        caplog.set_level(logging.WARNING, logger="claude_code_hooks_daemon.core.bounded_dispatch")
        try:
            with _every_slot_held(dispatcher):
                self._refuse(dispatcher)
                clock.now += Timeout.DISPATCH_SATURATION_QUIET_SECONDS
                self._refuse(dispatcher)
                self._refuse_every_second(dispatcher, clock, after - 1)
                assert self._sustained(caplog) == []
                self._refuse_every_second(dispatcher, clock, 1)
        finally:
            dispatcher.shutdown(wait=True)
        assert len(self._sustained(caplog)) == 1
        assert f"for {after}s" in self._sustained(caplog)[0]

    def test_straggler_cap_refusals_feed_the_same_signal(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        clock = _FakeClock()
        dispatcher: BoundedDispatcher[object] = BoundedDispatcher(
            max_inflight=2, max_stragglers=1, slot_wait_seconds=0.0, clock=clock
        )
        release = threading.Event()
        caplog.set_level(logging.WARNING, logger="claude_code_hooks_daemon.core.bounded_dispatch")
        try:
            stuck = dispatcher.run(
                lambda: release.wait(timeout=DispatchTestTimeout.GENEROUS),
                timeout=DispatchTestTimeout.VERY_SHORT,
                label="straggler",
            )
            assert isinstance(stuck, DispatchTimeout)
            self._refuse(dispatcher)
            self._refuse_every_second(
                dispatcher, clock, int(Timeout.DISPATCH_SATURATION_WARN_AFTER_SECONDS)
            )
        finally:
            release.set()
            dispatcher.shutdown(wait=True)
        assert len(self._sustained(caplog)) == 1
        assert "1 straggler(s)" in self._sustained(caplog)[0]


class TestConfigureDefaultDispatcher:
    """Plan 00533 (issue #124): ``daemon.chain.max_inflight`` and
    ``daemon.chain.slot_wait_seconds`` reach the process-wide dispatcher."""

    def test_it_replaces_the_shared_dispatcher_with_the_configured_one(self) -> None:
        try:
            configure_default_dispatcher(max_inflight=3, slot_wait_seconds=0.25)
            dispatcher = get_default_dispatcher()
            assert dispatcher.max_inflight == 3
            assert dispatcher.slot_wait_seconds == 0.25
        finally:
            reset_default_dispatcher_for_tests()
        assert get_default_dispatcher().max_inflight == DISPATCH_MAX_INFLIGHT
