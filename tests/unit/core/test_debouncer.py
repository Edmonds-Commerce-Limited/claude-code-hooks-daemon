"""Tests for the keyed debouncer (Plan 00480 Task 3.1)."""

import threading
import time
from collections.abc import Callable, Iterator

import pytest

from claude_code_hooks_daemon.core.debouncer import (
    DebounceFire,
    Debouncer,
    get_debouncer,
    reset_debouncer,
    shutdown_debouncer,
)


class FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _inline(job: Callable[[], None]) -> None:
    job()


def _make(clock: FakeClock, max_pending: int = 8) -> tuple[Debouncer, list[DebounceFire]]:
    """A deterministic debouncer: fake clock, no scheduler thread, inline callbacks."""
    fires: list[DebounceFire] = []
    debouncer = Debouncer(
        clock=clock, max_pending=max_pending, runner=_inline, start_scheduler=False
    )
    return debouncer, fires


class TestQuietPeriod:
    def test_fires_once_after_quiet_period(self) -> None:
        clock = FakeClock()
        d, fires = _make(clock)
        assert d.trigger("a", quiet_seconds=5.0, callback=fires.append) is True
        clock.advance(4.9)
        assert d.run_due() == 0
        assert fires == []
        clock.advance(0.2)
        assert d.run_due() == 1
        assert len(fires) == 1
        assert d.run_due() == 0
        assert d.pending() == {}

    def test_each_trigger_resets_the_timer(self) -> None:
        clock = FakeClock()
        d, fires = _make(clock)
        d.trigger("a", quiet_seconds=5.0, callback=fires.append)
        clock.advance(4.0)
        d.trigger("a", quiet_seconds=5.0, callback=fires.append)
        clock.advance(4.0)
        assert d.run_due() == 0
        clock.advance(1.5)
        assert d.run_due() == 1
        assert len(fires) == 1

    def test_keys_are_independent(self) -> None:
        clock = FakeClock()
        d, fires = _make(clock)
        d.trigger("a", quiet_seconds=1.0, callback=fires.append)
        d.trigger("b", quiet_seconds=10.0, callback=fires.append)
        clock.advance(2.0)
        assert d.run_due() == 1
        assert [f.key for f in fires] == ["a"]
        assert set(d.pending()) == {"b"}

    def test_fire_carries_latest_payload_count_and_times(self) -> None:
        clock = FakeClock()
        d, fires = _make(clock)
        d.trigger("a", quiet_seconds=5.0, callback=fires.append, payload="one")
        first = clock.now
        clock.advance(1.0)
        d.trigger("a", quiet_seconds=5.0, callback=fires.append, payload="two")
        clock.advance(1.0)
        d.trigger("a", quiet_seconds=5.0, callback=fires.append, payload="three")
        last = clock.now
        clock.advance(6.0)
        d.run_due()
        (fire,) = fires
        assert fire.payload == "three"
        assert fire.trigger_count == 3
        assert fire.first_trigger_at == first
        assert fire.last_trigger_at == last
        assert fire.forced is False

    def test_latest_trigger_supplies_callback_and_period(self) -> None:
        clock = FakeClock()
        d, _ = _make(clock)
        early: list[DebounceFire] = []
        late: list[DebounceFire] = []
        d.trigger("a", quiet_seconds=5.0, callback=early.append)
        d.trigger("a", quiet_seconds=1.0, callback=late.append)
        clock.advance(1.5)
        d.run_due()
        assert early == []
        assert len(late) == 1

    def test_retrigger_after_fire_starts_fresh_count(self) -> None:
        clock = FakeClock()
        d, fires = _make(clock)
        d.trigger("a", quiet_seconds=1.0, callback=fires.append)
        clock.advance(2.0)
        d.run_due()
        d.trigger("a", quiet_seconds=1.0, callback=fires.append)
        clock.advance(2.0)
        d.run_due()
        assert [f.trigger_count for f in fires] == [1, 1]


class TestValidation:
    @pytest.mark.parametrize("bad", [0.0, -1.0, float("inf"), float("nan")])
    def test_rejects_bad_quiet_seconds(self, bad: float) -> None:
        d, fires = _make(FakeClock())
        with pytest.raises(ValueError, match="quiet_seconds"):
            d.trigger("a", quiet_seconds=bad, callback=fires.append)

    def test_rejects_empty_key(self) -> None:
        d, fires = _make(FakeClock())
        with pytest.raises(ValueError, match="key"):
            d.trigger("", quiet_seconds=1.0, callback=fires.append)

    def test_rejects_bad_max_pending(self) -> None:
        with pytest.raises(ValueError, match="max_pending"):
            Debouncer(max_pending=0, start_scheduler=False)


class TestPendingAndCancel:
    def test_pending_reports_seconds_remaining(self) -> None:
        clock = FakeClock()
        d, fires = _make(clock)
        d.trigger("a", quiet_seconds=5.0, callback=fires.append)
        clock.advance(2.0)
        assert d.pending() == {"a": pytest.approx(3.0)}

    def test_cancel_drops_pending_key(self) -> None:
        clock = FakeClock()
        d, fires = _make(clock)
        d.trigger("a", quiet_seconds=1.0, callback=fires.append)
        assert d.cancel("a") is True
        assert d.cancel("a") is False
        clock.advance(5.0)
        assert d.run_due() == 0
        assert fires == []


class TestBoundedMemory:
    def test_overflow_fires_soonest_deadline_early_and_flags_it(self) -> None:
        clock = FakeClock()
        d, fires = _make(clock, max_pending=2)
        d.trigger("a", quiet_seconds=1.0, callback=fires.append, payload="A")
        d.trigger("b", quiet_seconds=9.0, callback=fires.append, payload="B")
        d.trigger("c", quiet_seconds=9.0, callback=fires.append, payload="C")
        assert [f.key for f in fires] == ["a"]
        assert fires[0].forced is True
        assert set(d.pending()) == {"b", "c"}

    def test_retriggering_existing_key_never_evicts(self) -> None:
        clock = FakeClock()
        d, fires = _make(clock, max_pending=2)
        d.trigger("a", quiet_seconds=1.0, callback=fires.append)
        d.trigger("b", quiet_seconds=1.0, callback=fires.append)
        d.trigger("a", quiet_seconds=1.0, callback=fires.append)
        assert fires == []
        assert len(d.pending()) == 2


class TestCallbackFailure:
    def test_raising_callback_is_logged_and_does_not_stop_others(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        clock = FakeClock()
        d, fires = _make(clock)

        def boom(_: DebounceFire) -> None:
            raise RuntimeError("kaboom")

        d.trigger("a", quiet_seconds=1.0, callback=boom)
        d.trigger("b", quiet_seconds=1.0, callback=fires.append)
        clock.advance(2.0)
        with caplog.at_level("ERROR"):
            assert d.run_due() == 2
        assert [f.key for f in fires] == ["b"]
        assert "kaboom" in caplog.text
        assert "'a'" in caplog.text


class TestShutdown:
    def test_shutdown_drops_pending_without_firing(self) -> None:
        clock = FakeClock()
        d, fires = _make(clock)
        d.trigger("a", quiet_seconds=1.0, callback=fires.append)
        d.shutdown()
        clock.advance(5.0)
        assert d.run_due() == 0
        assert fires == []
        assert d.pending() == {}

    def test_trigger_after_shutdown_is_rejected(self) -> None:
        d, fires = _make(FakeClock())
        d.shutdown()
        assert d.trigger("a", quiet_seconds=1.0, callback=fires.append) is False
        assert d.pending() == {}

    def test_shutdown_is_idempotent(self) -> None:
        d, _ = _make(FakeClock())
        d.shutdown()
        d.shutdown()


class TestRealScheduler:
    """Threaded behaviour with the real clock and tiny periods."""

    def test_fires_off_the_calling_thread_after_quiet_period(self) -> None:
        d = Debouncer()
        done = threading.Event()
        seen: list[int] = []

        def cb(fire: DebounceFire) -> None:
            seen.append(threading.get_ident())
            assert fire.trigger_count == 3
            done.set()

        try:
            for _ in range(3):
                d.trigger("k", quiet_seconds=0.15, callback=cb)
                time.sleep(0.03)
            assert not done.is_set()
            assert done.wait(2.0)
            assert seen[0] != threading.get_ident()
            assert len(seen) == 1
        finally:
            d.shutdown()

    def test_slow_callback_does_not_delay_other_keys(self) -> None:
        d = Debouncer()
        release = threading.Event()
        quick = threading.Event()

        def slow(_: DebounceFire) -> None:
            release.wait(5.0)

        try:
            d.trigger("slow", quiet_seconds=0.02, callback=slow)
            d.trigger("quick", quiet_seconds=0.1, callback=lambda _f: quick.set())
            assert quick.wait(2.0)
        finally:
            release.set()
            d.shutdown()

    def test_shutdown_stops_scheduler_and_drops_pending(self) -> None:
        d = Debouncer()
        fired = threading.Event()
        d.trigger("k", quiet_seconds=0.1, callback=lambda _f: fired.set())
        d.shutdown()
        assert not fired.wait(0.4)


class TestSingleton:
    @pytest.fixture(autouse=True)
    def _clean(self) -> Iterator[None]:
        reset_debouncer()
        yield
        reset_debouncer()

    def test_get_debouncer_returns_one_instance(self) -> None:
        assert get_debouncer() is get_debouncer()

    def test_shutdown_debouncer_keeps_instance_but_rejects_triggers(self) -> None:
        first = get_debouncer()
        shutdown_debouncer()
        assert get_debouncer() is first
        assert first.trigger("a", quiet_seconds=1.0, callback=lambda _f: None) is False

    def test_reset_debouncer_shuts_down_and_clears(self) -> None:
        first = get_debouncer()
        reset_debouncer()
        assert get_debouncer() is not first

    def test_shutdown_without_instance_is_noop(self) -> None:
        shutdown_debouncer()
