"""The daemon publishes the events-dir location when it binds the event sockets (Plan 00609).

Generated forwarders cannot carry the AF_UNIX-overflow fallback events dir, so
``start()`` writes it to ``events<suffix>.location`` for them to read back. A
file left behind by a stopped daemon is harmless: a forwarder trusts it only
when it names its own untracked dir, and the socket it points at is gone.
"""

import asyncio
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from tests.daemon._start_wait import wait_for_daemon_started
from tests.unit.daemon.test_event_socket_listeners import _EchoHandler, _make_config

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.daemon.paths import (
    event_socket_dir_is_fallback,
    events_dir_location_file,
    get_event_socket_dir_from_untracked,
)
from claude_code_hooks_daemon.daemon.server import HooksDaemon


@pytest.fixture
def front_controller() -> FrontController:
    controller = FrontController(event_name="PreToolUse")
    controller.register(_EchoHandler())
    return controller


@pytest.fixture
def runtime_root(monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """A private short runtime dir, so the fallback events dir stays out of /run/user."""
    with tempfile.TemporaryDirectory(prefix="rt-") as tmp:
        monkeypatch.setenv("XDG_RUNTIME_DIR", tmp)
        yield Path(tmp)


def _deep_untracked() -> Path:
    """An untracked dir whose legacy socket fits but whose events dir overflows."""
    base = Path(tempfile.mkdtemp())
    filler_len = max(1, 75 - len(str(base)) - len("/untracked") - 1)
    deep = base / ("x" * filler_len) / "untracked"
    deep.mkdir(parents=True)
    assert event_socket_dir_is_fallback(deep)
    return deep


async def _start(daemon: HooksDaemon) -> asyncio.Task[None]:
    task = asyncio.create_task(daemon.start())
    await wait_for_daemon_started(daemon, task, timeout=Timeout.SOCKET_CONNECT)
    return task


class TestStartPublishesTheLocation:
    @pytest.mark.anyio
    async def test_an_overflowing_layout_publishes_untracked_dir_then_events_dir(
        self, front_controller: FrontController, runtime_root: Path
    ) -> None:
        untracked = _deep_untracked()
        daemon = HooksDaemon(
            config=_make_config(untracked, relay_enabled=True), controller=front_controller
        )
        task = await _start(daemon)
        try:
            events_dir = get_event_socket_dir_from_untracked(untracked)
            assert events_dir.is_relative_to(runtime_root)
            assert events_dir_location_file(untracked).read_text() == f"{untracked}\n{events_dir}\n"
        finally:
            await daemon.shutdown()
            await task

    @pytest.mark.anyio
    async def test_a_natural_layout_publishes_nothing(
        self, front_controller: FrontController, runtime_root: Path
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="nl-") as short:
            untracked = Path(short)
            assert not event_socket_dir_is_fallback(untracked)
            daemon = HooksDaemon(
                config=_make_config(untracked, relay_enabled=True), controller=front_controller
            )
            task = await _start(daemon)
            try:
                assert not events_dir_location_file(untracked).exists()
            finally:
                await daemon.shutdown()
                await task

    @pytest.mark.anyio
    async def test_a_disabled_transport_publishes_nothing(
        self, front_controller: FrontController, runtime_root: Path
    ) -> None:
        untracked = _deep_untracked()
        daemon = HooksDaemon(config=_make_config(untracked), controller=front_controller)
        task = await _start(daemon)
        try:
            assert not events_dir_location_file(untracked).exists()
        finally:
            await daemon.shutdown()
            await task


class TestAStoppedDaemonLeavesAHarmlessFile:
    @pytest.mark.anyio
    async def test_the_file_outlives_shutdown_but_its_events_dir_does_not(
        self, front_controller: FrontController, runtime_root: Path
    ) -> None:
        untracked = _deep_untracked()
        daemon = HooksDaemon(
            config=_make_config(untracked, relay_enabled=True), controller=front_controller
        )
        task = await _start(daemon)
        events_dir = get_event_socket_dir_from_untracked(untracked)
        await daemon.shutdown()
        await task

        location = events_dir_location_file(untracked)
        assert location.read_text() == f"{untracked}\n{events_dir}\n"
        # Nothing for a forwarder to connect to: its socket test fails and it falls through.
        assert not events_dir.exists()

    @pytest.mark.anyio
    async def test_a_restart_rewrites_the_file(
        self, front_controller: FrontController, runtime_root: Path
    ) -> None:
        untracked = _deep_untracked()
        location = events_dir_location_file(untracked)
        location.write_text("/elsewhere/untracked\n/run/user/9/old-events\n")

        daemon = HooksDaemon(
            config=_make_config(untracked, relay_enabled=True), controller=front_controller
        )
        task = await _start(daemon)
        try:
            events_dir = get_event_socket_dir_from_untracked(untracked)
            assert location.read_text() == f"{untracked}\n{events_dir}\n"
        finally:
            await daemon.shutdown()
            await task
