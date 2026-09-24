"""Bounded, externally-enforced per-call dispatch (Plan 00466 N34).

``HandlerChain.execute``'s own chain deadline (Plan 00466 N25) is checked
ONCE per handler, BEFORE it runs -- it bounds the gap BETWEEN handlers, not
a handler's own execution. A handler slow enough within its own
``matches()``/``handle()`` reproduces exactly the bypass N25 exists to
close: ``secret_file_guard`` measured at 48.958s on 4 MB input, past both
the 20s chain deadline and the 30s client socket timeout, entirely inside
one handler's own call.

Python cannot forcibly interrupt a running thread, so the strongest
available guarantee is bounding the CALLER's wait, not the callee's code:
``BoundedDispatcher.run`` starts a callable on its own DAEMON thread and
waits on it with ``Future.result(timeout=...)``. On expiry the callable
keeps running in the background (a "stray worker") and is logged again, at
WARNING, whenever it does eventually finish -- it is abandoned by the
caller, never killed.

Deliberately NOT ``concurrent.futures.ThreadPoolExecutor``: its worker
threads are non-daemon and it registers an ``atexit`` hook
(``concurrent.futures.thread._python_exit``) that JOINS every one of them
before the interpreter is allowed to exit -- so one abandoned straggler
would hang the whole daemon PROCESS's shutdown for as long as that straggler
keeps running, exactly the failure this module exists to prevent one
handler from causing. A plain ``threading.Thread(daemon=True)`` per call is
never waited on at interpreter exit. Concurrency is still bounded, by a
semaphore rather than a pool: a call beyond ``max_inflight`` is refused
outright (``DispatchSaturated``) rather than queued -- an unbounded queue is
exactly the "pile up threads" failure a flood of overruns must not cause.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Final, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Sized well above the daemon's expected concurrency -- one chain execution
# dispatches its handlers SEQUENTIALLY, one in flight at a time, so this is
# headroom for several concurrent client connections, not a per-request
# budget. Ordinary traffic never approaches it; a flood of genuinely stuck
# handlers hits a hard ceiling instead of spawning threads without limit.
DISPATCH_MAX_INFLIGHT: Final[int] = 16


@dataclass(frozen=True, slots=True)
class DispatchTimeout:
    """Sentinel: the call did not complete within its budget.

    Attributes:
        waited: Seconds actually spent waiting (approximately ``timeout``,
            modulo scheduling overhead) -- for logging, not decision-making.
    """

    waited: float


@dataclass(frozen=True, slots=True)
class DispatchSaturated:
    """Sentinel: the pool had no free capacity to even start the call."""


class BoundedDispatcher(Generic[T]):
    """Runs callables on a small, bounded, shared thread pool.

    A callable that raises propagates the SAME exception back to
    :meth:`run`'s caller (``Future.result`` re-raises it) -- callers that
    already handle an exception from a direct, synchronous call handle one
    from here identically; only the timeout/saturation cases are new.
    """

    __slots__ = ("_max_inflight", "_semaphore", "_threads", "_threads_lock")

    def __init__(self, max_inflight: int = DISPATCH_MAX_INFLIGHT) -> None:
        """Create a dispatcher.

        Args:
            max_inflight: Upper bound on calls running at once, on this
                dispatcher. A submission beyond it is refused outright
                (:class:`DispatchSaturated`), never queued.
        """
        self._max_inflight = max_inflight
        self._semaphore = threading.BoundedSemaphore(max_inflight)
        # Only the CURRENTLY in-flight threads -- a finishing thread removes
        # itself (see `_run_and_release`), so this never grows past
        # `max_inflight` however many calls this dispatcher serves over its
        # lifetime. Needed only so `shutdown(wait=True)` has something to
        # join; the daemon's own process-lifetime dispatcher never calls it.
        self._threads: set[threading.Thread] = set()
        self._threads_lock = threading.Lock()

    def run(
        self, fn: Callable[[], T], *, timeout: float, label: str
    ) -> T | DispatchTimeout | DispatchSaturated:
        """Run ``fn`` on its own daemon thread, waiting up to ``timeout``
        seconds for it.

        Args:
            fn: A zero-argument callable. Run on a fresh daemon thread,
                never on the calling thread.
            timeout: Seconds to wait before giving up on ``fn`` and
                returning :class:`DispatchTimeout`. ``fn`` is NOT
                interrupted -- it keeps running on its own thread, which
                (being a daemon thread) will not block process shutdown
                even if it never finishes.
            label: Identifies ``fn`` in the WARNING logged on overrun or
                saturation. Carries no behaviour.

        Returns:
            ``fn``'s own return value on success; :class:`DispatchSaturated`
            when the pool had no free capacity to even start the call
            (fails CLOSED, the same "no verdict" case a timeout is); or
            :class:`DispatchTimeout` when ``fn`` did not finish in time.

        Raises:
            Exception: Whatever ``fn`` itself raised, when it raised before
                ``timeout`` elapsed -- propagated exactly as a direct,
                synchronous call to ``fn()`` would have raised it.
        """
        if not self._semaphore.acquire(blocking=False):
            logger.warning(
                "Bounded dispatch pool saturated (max_inflight exhausted) -- "
                "%s could not even be started; treating as not judged in time",
                label,
            )
            return DispatchSaturated()

        start = time.perf_counter()
        future: Future[T] = Future()

        def _run_and_release() -> None:
            try:
                result = fn()
            except Exception as exc:
                # Captured on the FUTURE, not swallowed: re-raised from
                # future.result() on the calling thread below, exactly as a
                # direct, synchronous call to fn() would have raised it.
                future.set_exception(exc)
            else:
                future.set_result(result)
            finally:
                self._semaphore.release()
                with self._threads_lock:
                    self._threads.discard(threading.current_thread())

        thread = threading.Thread(
            target=_run_and_release, name=f"handler-dispatch:{label}", daemon=True
        )
        with self._threads_lock:
            self._threads.add(thread)
        thread.start()

        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            logger.warning(
                "%s exceeded its %.2fs dispatch budget -- treating as not "
                "judged in time; it keeps running in the background",
                label,
                timeout,
            )
            future.add_done_callback(self._log_late_completion(label, start))
            return DispatchTimeout(waited=time.perf_counter() - start)

    @staticmethod
    def _log_late_completion(label: str, start: float) -> Callable[[Future[T]], None]:
        """A ``Future`` done-callback that logs how the stray worker finished.

        Runs on the WORKER thread that finally completed ``fn`` -- never on
        the thread that timed out waiting for it (that thread has long since
        moved on). Only observability: the outcome was already decided at
        the timeout.
        """

        def _callback(done: Future[T]) -> None:
            elapsed = time.perf_counter() - start
            exc = done.exception()
            if exc is not None:
                logger.warning(
                    "%s finished %.2fs after its dispatch budget expired, "
                    "with an exception: %s: %s",
                    label,
                    elapsed,
                    type(exc).__name__,
                    exc,
                )
            else:
                logger.warning(
                    "%s finished %.2fs after its dispatch budget expired",
                    label,
                    elapsed,
                )

        return _callback

    def shutdown(self, wait: bool = False) -> None:
        """Join every currently in-flight call, when asked to.

        There is no pool to release -- each call runs on its own daemon
        thread, which never blocks process shutdown on its own. This exists
        only so tests can wait for a straggler to actually finish before
        tearing down (e.g. before asserting on state it mutates).

        Args:
            wait: When True, block until every currently in-flight call
                (including any straggler still running past its own
                timeout) has finished. False (the default) returns
                immediately -- the daemon's own process-lifetime dispatcher
                always uses this default.
        """
        if not wait:
            return
        with self._threads_lock:
            threads = list(self._threads)
        for thread in threads:
            thread.join()


# Process-lifetime singleton (Plan 00466 N34), mirroring the process-lifetime
# caches elsewhere in this codebase (e.g.
# ``secret_file_matching.resolve_configured_patterns``): a thread pool is
# exactly the kind of resource that must not be rebuilt per call, and
# ``HandlerChain`` has no natural single owner to hold one instead.
_default_dispatcher: BoundedDispatcher[object] | None = None
_default_dispatcher_lock = threading.Lock()


def get_default_dispatcher() -> BoundedDispatcher[object]:
    """The shared dispatcher ``HandlerChain`` uses for every bounded call.

    Lazily constructed on first use and reused for the life of the daemon
    process.
    """
    global _default_dispatcher
    if _default_dispatcher is None:
        with _default_dispatcher_lock:
            if _default_dispatcher is None:
                _default_dispatcher = BoundedDispatcher()
    return _default_dispatcher


def reset_default_dispatcher_for_tests() -> None:
    """Replace the shared dispatcher with a fresh one. Test-only escape hatch.

    Releases the old pool's threads without waiting for any straggler still
    running past its own timeout -- callers that need to observe a
    straggler finish should hold their own :class:`BoundedDispatcher`
    instance instead of going through the singleton.
    """
    global _default_dispatcher
    old = _default_dispatcher
    _default_dispatcher = None
    if old is not None:
        old.shutdown(wait=False)
