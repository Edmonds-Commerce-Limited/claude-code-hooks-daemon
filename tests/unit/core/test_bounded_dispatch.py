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

import threading
import time

from claude_code_hooks_daemon.core.bounded_dispatch import (
    BoundedDispatcher,
    DispatchSaturated,
    DispatchTimeout,
)


class TestBoundedDispatcherCompletesWithinBudget:
    """The common case: the call finishes before its timeout."""

    def test_returns_the_callables_own_result(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=4)
        try:
            outcome = dispatcher.run(lambda: 42, timeout=1.0, label="fast")
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
                dispatcher.run(_boom, timeout=1.0, label="raiser")
            except ValueError as exc:
                raised = exc
        finally:
            dispatcher.shutdown()
        assert raised is not None
        assert str(raised) == "boom"


class TestBoundedDispatcherTimesOut:
    """A callable that outruns its budget is abandoned, not waited on."""

    def test_returns_dispatch_timeout_without_waiting_for_completion(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=4)
        started = threading.Event()

        def _slow() -> str:
            started.set()
            time.sleep(0.3)
            return "late"

        try:
            start = time.perf_counter()
            outcome = dispatcher.run(_slow, timeout=0.05, label="slow")
            elapsed = time.perf_counter() - start
        finally:
            # The straggler is still sleeping; give it time to finish before
            # the pool is torn down, so this test does not leak a thread
            # into the next one.
            started.wait(timeout=1.0)
            time.sleep(0.3)
            dispatcher.shutdown(wait=True)

        assert isinstance(outcome, DispatchTimeout)
        # Bounded by the TIMEOUT, not by `_slow`'s own 0.3s sleep.
        assert elapsed < 0.2

    def test_the_stray_worker_still_runs_to_completion_in_the_background(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=4)
        completed = threading.Event()

        def _slow() -> None:
            time.sleep(0.1)
            completed.set()

        try:
            outcome = dispatcher.run(_slow, timeout=0.02, label="slow")
            assert isinstance(outcome, DispatchTimeout)
            assert not completed.is_set()  # not yet -- still bounded above
            assert completed.wait(timeout=1.0)  # but it DOES finish eventually
        finally:
            dispatcher.shutdown(wait=True)


class TestBoundedDispatcherSaturation:
    """A pool with no free capacity fails closed instead of queuing."""

    def test_saturated_pool_returns_dispatch_saturated_immediately(self) -> None:
        dispatcher = BoundedDispatcher(max_inflight=1)
        occupied = threading.Event()
        release = threading.Event()

        def _occupy() -> None:
            occupied.set()
            release.wait(timeout=5.0)

        filler_thread: threading.Thread | None = None
        try:
            # Fill the one slot with a call that will not finish until we
            # release it.
            filler_thread = threading.Thread(
                target=lambda: dispatcher.run(_occupy, timeout=5.0, label="filler")
            )
            filler_thread.start()
            assert occupied.wait(timeout=1.0)

            start = time.perf_counter()
            outcome = dispatcher.run(lambda: "unreachable", timeout=5.0, label="second")
            elapsed = time.perf_counter() - start
        finally:
            release.set()
            if filler_thread is not None:
                filler_thread.join(timeout=5.0)
            dispatcher.shutdown(wait=True)

        assert isinstance(outcome, DispatchSaturated)
        # Refused immediately -- it never waited anywhere near the 5s timeout.
        assert elapsed < 0.5
