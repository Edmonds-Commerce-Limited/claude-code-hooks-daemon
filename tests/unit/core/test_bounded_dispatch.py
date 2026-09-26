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
import threading
import time

from claude_code_hooks_daemon.core.bounded_dispatch import (
    BoundedDispatcher,
    DispatchSaturated,
    DispatchTimeout,
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
        dispatcher = BoundedDispatcher(max_inflight=1)
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
