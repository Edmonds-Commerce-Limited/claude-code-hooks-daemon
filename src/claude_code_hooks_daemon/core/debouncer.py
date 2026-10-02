"""Keyed debouncer: a first-class daemon facility for "act once things go quiet".

A handler that wants to react to a *burst* of events once, after the burst has
settled (for example "a plan was edited five times in ten seconds, run the
fact check once"), triggers the debouncer with a key. Every trigger for the
same key restarts that key's quiet period; the callback fires ONCE, after the
period passes with no further trigger.

Usage::

    from claude_code_hooks_daemon.core.debouncer import DebounceFire, get_debouncer

    def _check(fire: DebounceFire) -> None:
        ...  # fire.key, fire.payload, fire.trigger_count, ...

    get_debouncer().trigger(plan_dir, quiet_seconds=5.0, callback=_check, payload=path)

Threading model (daemon/server.py runs handlers through
``loop.run_in_executor(None, controller.dispatch, ...)`` on executor threads,
and ``core/bounded_dispatch.py`` runs each handler call on its own plain
daemon thread):

- ``trigger`` is called from those handler threads. It takes one short lock,
  records the trigger and returns; it never runs a callback and never waits,
  so it cannot delay a hook response.
- ONE scheduler thread (``threading.Thread(daemon=True)``, started lazily by
  the first trigger) sleeps until the earliest deadline and hands each due
  key to the runner.
- The default runner starts one plain daemon thread per fire, so a slow
  callback delays neither the scheduler nor any other key. This mirrors
  ``bounded_dispatch``, which deliberately avoids ``ThreadPoolExecutor``
  (its non-daemon workers block interpreter exit). Concurrent fires are
  bounded by ``max_pending``, because a key must be pending to fire.
- The asyncio event loop is never involved: the daemon's work already happens
  on threads, and a loop timer would need the loop to hop back to a thread
  for every callback anyway.

Guarantees:

- A callback that raises is logged with its key and never kills the
  scheduler or any other callback.
- Memory is bounded by ``max_pending`` distinct pending keys. A trigger for a
  NEW key arriving at the cap fires the key with the soonest deadline
  EARLY (``DebounceFire.forced`` is True) rather than dropping it: losing a
  pending trigger loses work silently, while firing early only shortens one
  quiet period. Re-triggering an existing key never evicts.
- ``shutdown`` DROPS every pending key without firing it and rejects later
  triggers. Pending state is in memory only and does not survive a restart:
  the next event for that key re-triggers it, and flushing on shutdown would
  run callbacks against a daemon that is tearing down. A callback already
  running when shutdown is called is left to finish (its thread is a daemon
  thread, so it cannot block process exit).
- The latest trigger wins: its callback, quiet period and payload replace the
  earlier ones for that key; the fire reports how many triggers coalesced and
  when the first and last arrived.
"""

import heapq
import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_MAX_PENDING = 256
_SCHEDULER_JOIN_SECONDS = 2.0


@dataclass(frozen=True)
class DebounceFire:
    """What a callback receives when its key's quiet period has passed.

    Attributes:
        key: The debounce key.
        payload: The payload from the LAST trigger (None if it gave none).
        trigger_count: How many triggers were coalesced into this fire.
        first_trigger_at: Clock reading of the first coalesced trigger.
        last_trigger_at: Clock reading of the last coalesced trigger.
        forced: True when the pending-key cap fired this key before its
            quiet period had fully passed.
    """

    key: str
    payload: object | None
    trigger_count: int
    first_trigger_at: float
    last_trigger_at: float
    forced: bool = False


@dataclass
class _Pending:
    callback: Callable[[DebounceFire], None]
    payload: object | None
    trigger_count: int
    first_trigger_at: float
    last_trigger_at: float
    deadline: float


def _thread_runner(job: Callable[[], None]) -> None:
    """Default runner: one plain daemon thread per fire."""
    threading.Thread(target=job, name="debounce-callback", daemon=True).start()


class Debouncer:
    """Thread-safe keyed debouncer. See the module docstring for the contract."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_pending: int = DEFAULT_MAX_PENDING,
        runner: Callable[[Callable[[], None]], None] = _thread_runner,
        start_scheduler: bool = True,
    ) -> None:
        """Create a debouncer.

        Args:
            clock: Monotonic seconds source; inject a fake for deterministic tests.
            max_pending: Cap on distinct pending keys (must be at least 1).
            runner: Executes one fire's job; the default uses a daemon thread.
                Tests inject a synchronous runner.
            start_scheduler: When False no scheduler thread is started and the
                caller drives firing with :meth:`run_due` (tests).

        Raises:
            ValueError: If ``max_pending`` is below 1.
        """
        if max_pending < 1:
            raise ValueError(f"max_pending must be at least 1, got {max_pending}")
        self._clock = clock
        self._max_pending = max_pending
        self._runner = runner
        self._start_scheduler = start_scheduler
        self._cond = threading.Condition()
        self._pending: dict[str, _Pending] = {}
        self._shutdown = False
        self._scheduler: threading.Thread | None = None

    def trigger(
        self,
        key: str,
        *,
        quiet_seconds: float,
        callback: Callable[[DebounceFire], None],
        payload: object | None = None,
    ) -> bool:
        """Record an event for ``key`` and (re)start its quiet period.

        Never runs a callback on the calling thread and never blocks beyond a
        short lock.

        Args:
            key: Non-empty identity of the thing being debounced.
            quiet_seconds: Finite, positive quiet period before the callback fires.
            callback: Called once with a :class:`DebounceFire`; replaces any
                callback from an earlier trigger of the same key.
            payload: Replaces any earlier payload for the key.

        Returns:
            True if the trigger was recorded, False if the debouncer has been
            shut down (the trigger is dropped).

        Raises:
            ValueError: If ``key`` is empty or ``quiet_seconds`` is not a
                finite positive number.
        """
        if not key:
            raise ValueError("debounce key must not be empty")
        if not math.isfinite(quiet_seconds) or quiet_seconds <= 0:
            raise ValueError(f"quiet_seconds must be finite and positive, got {quiet_seconds}")

        forced_job: Callable[[], None] | None = None
        with self._cond:
            if self._shutdown:
                logger.debug("Debouncer is shut down; dropping trigger for %r", key)
                return False
            now = self._clock()
            existing = self._pending.get(key)
            if existing is None:
                if len(self._pending) >= self._max_pending:
                    forced_job = self._evict_soonest_locked()
                self._pending[key] = _Pending(callback, payload, 1, now, now, now + quiet_seconds)
            else:
                existing.callback = callback
                existing.payload = payload
                existing.trigger_count += 1
                existing.last_trigger_at = now
                existing.deadline = now + quiet_seconds
            self._ensure_scheduler_locked()
            self._cond.notify_all()
        if forced_job is not None:
            self._runner(forced_job)
        return True

    def cancel(self, key: str) -> bool:
        """Drop the pending trigger for ``key`` without firing it.

        Returns:
            True if a pending trigger existed.
        """
        with self._cond:
            removed = self._pending.pop(key, None) is not None
            self._cond.notify_all()
        return removed

    def pending(self) -> dict[str, float]:
        """Introspect: seconds remaining until each pending key fires (floored at 0)."""
        with self._cond:
            now = self._clock()
            return {k: max(0.0, p.deadline - now) for k, p in self._pending.items()}

    def run_due(self) -> int:
        """Fire every key whose quiet period has passed.

        The scheduler thread calls this; tests call it directly with a fake
        clock and ``start_scheduler=False``.

        Returns:
            The number of keys fired.
        """
        with self._cond:
            now = self._clock()
            due = [k for k, p in self._pending.items() if p.deadline <= now]
            ordered = heapq.nsmallest(len(due), due, key=lambda k: self._pending[k].deadline)
            jobs = [self._make_job_locked(k, forced=False) for k in ordered]
        for job in jobs:
            self._runner(job)
        return len(jobs)

    def shutdown(self) -> None:
        """Drop every pending key without firing, stop the scheduler, reject new triggers."""
        with self._cond:
            self._shutdown = True
            self._pending.clear()
            self._cond.notify_all()
            scheduler = self._scheduler
        if scheduler is not None and scheduler is not threading.current_thread():
            scheduler.join(timeout=_SCHEDULER_JOIN_SECONDS)

    def _evict_soonest_locked(self) -> Callable[[], None]:
        """Pop the soonest-deadline key as a forced-fire job. Caller holds the lock."""
        victim = min(self._pending, key=lambda k: self._pending[k].deadline)
        return self._make_job_locked(victim, forced=True)

    def _make_job_locked(self, key: str, *, forced: bool) -> Callable[[], None]:
        """Remove ``key`` from pending and return the job that fires it."""
        entry = self._pending.pop(key)
        fire = DebounceFire(
            key=key,
            payload=entry.payload,
            trigger_count=entry.trigger_count,
            first_trigger_at=entry.first_trigger_at,
            last_trigger_at=entry.last_trigger_at,
            forced=forced,
        )
        callback = entry.callback

        def job() -> None:
            try:
                callback(fire)
            except Exception:
                logger.exception("Debounce callback for key %r raised", key)

        return job

    def _ensure_scheduler_locked(self) -> None:
        if not self._start_scheduler or self._scheduler is not None:
            return
        thread = threading.Thread(target=self._scheduler_loop, name="debouncer", daemon=True)
        self._scheduler = thread
        thread.start()

    def _scheduler_loop(self) -> None:
        while True:
            with self._cond:
                while not self._shutdown:
                    if not self._pending:
                        self._cond.wait()
                        continue
                    wait_for = min(p.deadline for p in self._pending.values()) - self._clock()
                    if wait_for <= 0:
                        break
                    self._cond.wait(timeout=wait_for)
                if self._shutdown:
                    return
            self.run_due()


_debouncer: Debouncer | None = None
_singleton_lock = threading.Lock()


def get_debouncer() -> Debouncer:
    """Get the daemon-wide Debouncer, creating it on first use."""
    global _debouncer
    with _singleton_lock:
        if _debouncer is None:
            _debouncer = Debouncer()
        return _debouncer


def shutdown_debouncer() -> None:
    """Shut the daemon-wide debouncer down (daemon shutdown). No-op if never used.

    The instance is kept so a straggling handler's later trigger is rejected
    rather than silently starting a new scheduler in a dying daemon.
    """
    with _singleton_lock:
        current = _debouncer
    if current is not None:
        current.shutdown()


def reset_debouncer() -> None:
    """Shut down and discard the daemon-wide debouncer (tests only)."""
    global _debouncer
    with _singleton_lock:
        current = _debouncer
        _debouncer = None
    if current is not None:
        current.shutdown()
