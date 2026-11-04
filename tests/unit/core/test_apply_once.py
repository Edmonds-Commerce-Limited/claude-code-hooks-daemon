"""Tests for ApplyOnce and the shared lazy language filter."""

import threading
from typing import Any

import pytest

from claude_code_hooks_daemon.core.apply_once import ApplyOnce, LazyLanguageFilterMixin
from claude_code_hooks_daemon.handlers.pre_tool_use.error_hiding_blocker import (
    ErrorHidingBlockerHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


class TestApplyOnce:
    def test_runs_once(self) -> None:
        gate = ApplyOnce()
        calls: list[int] = []
        gate.run(lambda: calls.append(1))
        gate.run(lambda: calls.append(2))
        assert calls == [1]
        assert gate.done is True

    def test_failure_leaves_gate_open_for_retry(self) -> None:
        gate = ApplyOnce()

        def boom() -> None:
            raise RuntimeError("x")

        with pytest.raises(RuntimeError):
            gate.run(boom)
        assert gate.done is False
        gate.run(lambda: None)
        assert gate.done is True

    def test_concurrent_caller_waits_for_the_apply_to_finish(self) -> None:
        gate = ApplyOnce()
        started = threading.Event()
        release = threading.Event()
        finished: list[bool] = []

        def slow() -> None:
            started.set()
            release.wait(5)
            finished.append(True)

        first = threading.Thread(target=lambda: gate.run(slow))
        first.start()
        assert started.wait(5)

        observed: list[bool] = []

        def second_caller() -> None:
            gate.run(lambda: finished.append(False))
            observed.append(bool(finished) and finished[0])

        second = threading.Thread(target=second_caller)
        second.start()
        second.join(0.2)
        assert second.is_alive(), "second caller must block until the apply completes"
        release.set()
        first.join(5)
        second.join(5)
        assert finished == [True]
        assert observed == [True]

    def test_reentrant_call_does_not_deadlock(self) -> None:
        gate = ApplyOnce()
        gate.run(lambda: gate.run(lambda: None))
        assert gate.done is True


class _Recorder(LazyLanguageFilterMixin):
    def __init__(self, registry: Any) -> None:
        self._registry = registry
        self._languages = ["Python"]
        self._project_languages = None
        self._language_gate = ApplyOnce()


class _SlowRegistry:
    """Registry whose filter yields mid-way, like a concurrent first request."""

    def __init__(self) -> None:
        self._strategies = {"Python": 1, "Go": 2}
        self.mid_filter = threading.Event()
        self.proceed = threading.Event()

    def filter_by_languages(self, names: list[str]) -> None:
        self.mid_filter.set()
        self.proceed.wait(5)
        for lang in [k for k in self._strategies if k not in names]:
            del self._strategies[lang]


class TestLazyLanguageFilterMixin:
    def test_no_unfiltered_window_and_no_key_error(self) -> None:
        registry = _SlowRegistry()
        handler = _Recorder(registry)
        errors: list[BaseException] = []
        seen_after: list[dict[str, int]] = []

        def call() -> None:
            try:
                handler._apply_language_filter()
                seen_after.append(dict(registry._strategies))
            except BaseException as exc:  # recorded and asserted below
                errors.append(exc)

        t1 = threading.Thread(target=call)
        t1.start()
        assert registry.mid_filter.wait(5)
        t2 = threading.Thread(target=call)
        t2.start()
        t2.join(0.2)
        assert t2.is_alive(), "second request must not proceed on an unfiltered registry"
        registry.proceed.set()
        t1.join(5)
        t2.join(5)
        assert errors == []
        assert seen_after == [{"Python": 1}, {"Python": 1}]


@pytest.mark.parametrize("cls", [PipeBlockerHandler, ErrorHidingBlockerHandler])
def test_real_handlers_use_the_shared_gate(cls: Any) -> None:
    handler = cls()
    assert isinstance(handler, LazyLanguageFilterMixin)
    assert handler._language_gate.done is False
    handler._apply_language_filter()
    assert handler._language_gate.done is True
