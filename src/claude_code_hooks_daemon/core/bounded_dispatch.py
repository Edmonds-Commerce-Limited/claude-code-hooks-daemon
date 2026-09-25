"""Bounded, externally-enforced per-call dispatch (Plan 00466 N34).

Plan 00466 N40 M2 adds straggler accounting: a timed-out call's semaphore
permit is released the moment the CALLER gives up waiting (not when the
straggler itself eventually finishes), so an abandoned call no longer denies
every future dispatch forever. A separate ``max_stragglers`` cap then bounds
how many abandoned calls may be alive at once, since the semaphore alone no
longer does -- and :meth:`BoundedDispatcher.straggler_health` reports their
count and oldest age so the daemon can surface DEGRADED health.

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


@dataclass(frozen=True, slots=True)
class _StragglerInfo:
    """Bookkeeping for one abandoned call, kept until it actually finishes."""

    label: str
    started_at: float


@dataclass(frozen=True, slots=True)
class StragglerHealth:
    """Snapshot of currently-abandoned dispatch calls (Plan 00466 N40 M2).

    Attributes:
        count: How many calls are still running past their own timeout,
            right now.
        oldest_age_seconds: How long the OLDEST of them has been running
            since it was dispatched. 0.0 when ``count`` is 0.
    """

    count: int
    oldest_age_seconds: float


class _SinglePermit:
    """Releases a dispatcher's semaphore permit exactly once, whichever of
    two racing paths gets there first (Plan 00466 N40 M2).

    ``BoundedDispatcher.run`` and the worker thread it starts both hold a
    reference to the SAME instance: the waiting thread releases it early on
    timeout (freeing capacity for a NEW dispatch immediately, rather than
    holding the permit hostage until the abandoned call finishes on its
    own), and the worker's own ``finally`` releases it again when the call
    actually completes. Without this guard both paths would call
    ``semaphore.release()``, over-releasing a ``BoundedSemaphore`` past its
    initial value.
    """

    __slots__ = ("_lock", "_released", "_semaphore")

    def __init__(self, semaphore: threading.BoundedSemaphore) -> None:
        self._semaphore = semaphore
        self._lock = threading.Lock()
        self._released = False

    def release(self) -> None:
        """Release the underlying permit, unless already released."""
        with self._lock:
            if self._released:
                return
            self._released = True
        self._semaphore.release()


class BoundedDispatcher(Generic[T]):
    """Runs callables on fresh, per-call daemon threads, bounded by a shared
    semaphore -- NOT a thread pool (Plan 00466 N40 n1): there is no fixed
    set of worker threads reused across calls, and nothing is queued. Each
    :meth:`run` call gets its own brand-new ``threading.Thread``; the
    semaphore only caps how many may be alive and actively waited on at
    once, refusing a call outright (:class:`DispatchSaturated`) rather than
    queuing it past that cap.

    A callable that raises propagates the SAME exception back to
    :meth:`run`'s caller (``Future.result`` re-raises it) -- callers that
    already handle an exception from a direct, synchronous call handle one
    from here identically; only the timeout/saturation cases are new.
    """

    __slots__ = (
        "_max_inflight",
        "_max_stragglers",
        "_semaphore",
        "_stragglers",
        "_threads",
        "_threads_lock",
    )

    def __init__(
        self,
        max_inflight: int = DISPATCH_MAX_INFLIGHT,
        *,
        max_stragglers: int | None = None,
    ) -> None:
        """Create a dispatcher.

        Args:
            max_inflight: Upper bound on calls being ACTIVELY WAITED ON at
                once, on this dispatcher. A submission beyond it is refused
                outright (:class:`DispatchSaturated`), never queued.
            max_stragglers: Upper bound on abandoned calls (Plan 00466 N40
                M2) still running in the background at once. A timed-out
                call's ``max_inflight`` permit is released immediately (see
                :meth:`run`), so `max_inflight` alone no longer bounds how
                many stragglers can pile up -- this does. None (the
                default) reuses ``max_inflight`` itself: Single Source of
                Truth, one dial governs both unless a caller deliberately
                splits them.
        """
        self._max_inflight = max_inflight
        self._max_stragglers = max_stragglers if max_stragglers is not None else max_inflight
        self._semaphore = threading.BoundedSemaphore(max_inflight)
        # Only the CURRENTLY in-flight threads -- a finishing thread removes
        # itself (see `_run_and_release`), so this never grows past
        # `max_inflight` however many calls this dispatcher serves over its
        # lifetime. Needed only so `shutdown(wait=True)` has something to
        # join; the daemon's own process-lifetime dispatcher never calls it.
        self._threads: set[threading.Thread] = set()
        # Calls that timed out and are still running (Plan 00466 N40 M2),
        # keyed by their own worker thread -- distinct from `_threads` (every
        # currently-running call, straggler or not). Removed by whichever of
        # `run`'s timeout branch or `_run_and_release`'s `finally` runs
        # second; the FIRST already recorded it, so `dict.pop` with a
        # default handles either order without raising.
        self._stragglers: dict[threading.Thread, _StragglerInfo] = {}
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
            when the pool had no free capacity to even start the call, OR
            the straggler cap was already reached (both fail CLOSED, the
            same "no verdict" case a timeout is); or :class:`DispatchTimeout`
            when ``fn`` did not finish in time.

        Raises:
            Exception: Whatever ``fn`` itself raised, when it raised before
                ``timeout`` elapsed -- propagated exactly as a direct,
                synchronous call to ``fn()`` would have raised it.
        """
        # Checked BEFORE the semaphore (Plan 00466 N40 M2): a timed-out
        # call's permit is released immediately below, so the semaphore
        # alone would let an unbounded number of abandoned calls accumulate.
        with self._threads_lock:
            straggler_count = len(self._stragglers)
        if straggler_count >= self._max_stragglers:
            logger.warning(
                "Bounded dispatch stragglers at capacity (%d abandoned call(s)) -- "
                "%s could not even be started; treating as not judged in time",
                straggler_count,
                label,
            )
            return DispatchSaturated()

        if not self._semaphore.acquire(blocking=False):
            logger.warning(
                "Bounded dispatch pool saturated (max_inflight exhausted) -- "
                "%s could not even be started; treating as not judged in time",
                label,
            )
            return DispatchSaturated()

        start = time.perf_counter()
        future: Future[T] = Future()
        permit = _SinglePermit(self._semaphore)

        def _run_and_release() -> None:
            try:
                result = fn()
            except BaseException as exc:
                # BaseException, not Exception (Plan 00466 N40 M2, review
                # m3): SystemExit/KeyboardInterrupt raised inside fn() used
                # to fall through this handler uncaught, leaving the future
                # NEVER resolved -- the caller then waited out its full
                # dispatch timeout for a verdict that was never coming,
                # instead of failing fast. Captured on the FUTURE, not
                # swallowed: re-raised from future.result() on the calling
                # thread below, exactly as a direct, synchronous call to
                # fn() would have raised it.
                future.set_exception(exc)
            else:
                future.set_result(result)
            finally:
                # `permit.release()` is a no-op if `run`'s own timeout branch
                # already released it (Plan 00466 N40 M2) -- see
                # `_SinglePermit`.
                permit.release()
                with self._threads_lock:
                    self._threads.discard(threading.current_thread())
                    self._stragglers.pop(threading.current_thread(), None)

        thread = threading.Thread(
            target=_run_and_release, name=f"handler-dispatch:{label}", daemon=True
        )
        try:
            with self._threads_lock:
                self._threads.add(thread)
            thread.start()
        except Exception:
            # `thread.start()` (e.g. "can't start new thread") failed before
            # `_run_and_release` ever got to run -- nothing will release the
            # permit or discard the thread on our behalf, so both leak
            # unless done here (Plan 00466 N40 M2, review m3).
            permit.release()
            with self._threads_lock:
                self._threads.discard(thread)
            raise

        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            # Release the permit NOW -- the caller has given up, so holding
            # capacity hostage until the straggler eventually finishes (which
            # for a genuine infinite loop is never) is exactly how enough
            # abandoned calls used to deny every future dispatch permanently
            # (Plan 00466 N40 M2).
            permit.release()
            with self._threads_lock:
                self._stragglers[thread] = _StragglerInfo(label=label, started_at=start)
            logger.warning(
                "%s exceeded its %.2fs dispatch budget -- treating as not "
                "judged in time; it keeps running in the background",
                label,
                timeout,
            )
            future.add_done_callback(self._log_late_completion(label, start))
            return DispatchTimeout(waited=time.perf_counter() - start)

    def straggler_health(self) -> StragglerHealth:
        """Count and oldest age of calls currently running past their own
        timeout (Plan 00466 N40 M2), for the daemon's health reporting.
        """
        now = time.perf_counter()
        with self._threads_lock:
            infos = list(self._stragglers.values())
        if not infos:
            return StragglerHealth(count=0, oldest_age_seconds=0.0)
        oldest_age = max(now - info.started_at for info in infos)
        return StragglerHealth(count=len(infos), oldest_age_seconds=oldest_age)

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
# ``secret_file_matching.resolve_configured_patterns``): the semaphore that
# bounds concurrent in-flight calls (Plan 00466 N40 n1: NOT a thread pool --
# see the class docstring) is exactly the kind of resource that must not be
# rebuilt per call, and ``HandlerChain`` has no natural single owner to hold
# one instead.
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
