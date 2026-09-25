"""Tests for the shared `wait_for_daemon_started` test helper.

Plan 00466 N39 review1 MEDIUM-1: every converted `started_event` wait site
raced against a fixed 5s timeout, so a start that failed BEFORE reaching
`started_event.set()` surfaced only an opaque `TimeoutError` after the full
wait, with the real exception left unretrieved on the server task. This
helper races the event against the task itself so the real exception
propagates immediately.
"""

import asyncio

import pytest

from claude_code_hooks_daemon.constants import Timeout
from tests.daemon._start_wait import wait_for_daemon_started


class _FakeDaemon:
    """Minimal stand-in exposing only the `started_event` attribute the
    helper reads."""

    def __init__(self) -> None:
        self.started_event = asyncio.Event()


class TestWaitForDaemonStarted:
    @pytest.mark.anyio
    async def test_returns_once_started_event_is_set(self) -> None:
        daemon = _FakeDaemon()

        async def _start() -> None:
            await asyncio.sleep(0.01)
            daemon.started_event.set()
            await asyncio.sleep(3600)  # pretend to keep serving

        task = asyncio.create_task(_start())
        try:
            await wait_for_daemon_started(daemon, task, timeout=Timeout.SOCKET_CONNECT)
            assert daemon.started_event.is_set()
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.anyio
    async def test_surfaces_the_real_exception_from_a_failed_start(self) -> None:
        daemon = _FakeDaemon()

        async def _start() -> None:
            await asyncio.sleep(0.01)
            raise OSError("bind boom")

        task = asyncio.create_task(_start())

        with pytest.raises(OSError, match="bind boom"):
            await wait_for_daemon_started(daemon, task, timeout=Timeout.SOCKET_CONNECT)

    @pytest.mark.anyio
    async def test_raises_timeout_error_when_neither_event_nor_task_settle(self) -> None:
        daemon = _FakeDaemon()

        async def _start() -> None:
            await asyncio.sleep(3600)

        task = asyncio.create_task(_start())
        try:
            with pytest.raises(TimeoutError):
                await wait_for_daemon_started(
                    daemon, task, timeout=Timeout.DAEMON_PID_POLL_INTERVAL_SEC
                )
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.anyio
    async def test_a_started_event_set_just_before_task_completion_wins(self) -> None:
        """A clean start that finishes serving (task never completes) is the
        common case; this asserts the started_event branch is preferred when
        the event is set first, even if the task completes shortly after."""
        daemon = _FakeDaemon()

        async def _start() -> None:
            daemon.started_event.set()
            await asyncio.sleep(0.01)

        task = asyncio.create_task(_start())
        await wait_for_daemon_started(daemon, task, timeout=Timeout.SOCKET_CONNECT)
        assert daemon.started_event.is_set()
        await task
