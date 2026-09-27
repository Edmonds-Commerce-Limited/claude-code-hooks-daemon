"""Plan 00127: daemon lifecycle REUSE fix — server.py layer.

Multiple Claude Code processes sharing one (hostname, project root) share one
``daemon-{hostname}.{sock,pid}``. The legacy server unconditionally unlinked the
socket and clobbered the PID file on start, orphaning a live incumbent and
stealing its socket (Mechanism B). Decision 1 (user-confirmed): a second start
that finds a LIVE, HEALTHY same-root daemon must REUSE it (never unlink a live
socket); a genuinely STALE socket must still be cleaned up so normal
start/restart is unaffected.

These tests cover the server.py layer:
  - ``_probe_socket_live`` / ``_socket_is_live`` liveness probe semantics.
  - ``HooksDaemon.start()`` refuses to unlink a live socket (raises
    ``DaemonAlreadyRunningError``) but unlinks + binds a stale one.
  - ``HooksDaemon._write_pid_file()`` refuses to clobber a live incumbent's PID
    file but overwrites a stale one.
"""

import asyncio
import contextlib
import fcntl
import os
import shutil
import socket as socket_module
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import ANY, MagicMock, patch

import pytest

from claude_code_hooks_daemon.config.models import DaemonConfig, LogLevel
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.paths import cleanup_stale_daemon_files
from claude_code_hooks_daemon.daemon.server import (
    DaemonAlreadyRunningError,
    DaemonIdentity,
    HooksDaemon,
    LaunchLock,
    StartLockTimeout,
    StartUnderWay,
    _pid_file_points_at_live_process,
    _probe_socket_live,
    _probe_socket_liveness,
    _socket_is_live,
    _SocketLiveness,
    daemon_socket_identity,
    hold_start_lock,
    launch_lock_path,
    start_under_way,
)


class _FakeController:
    """Minimal controller satisfying the Controller protocol."""

    def process_request(
        self, request_data: dict[str, Any], *, arrival_time: float | None = None
    ) -> dict[str, Any]:
        return {"result": {"decision": "allow"}}

    def get_health(self) -> dict[str, Any]:
        return {"status": "healthy", "handlers": {}}

    def get_handlers(self) -> dict[str, list[dict[str, Any]]]:
        return {}

    def get_mode(self) -> dict[str, Any]:
        return {"mode": "default", "custom_message": None}

    def set_mode(self, mode: Any, custom_message: str | None = None) -> bool:
        return True


def _make_config(socket_path: Path, pid_file_path: Path | None = None) -> DaemonConfig:
    return DaemonConfig(
        socket_path=socket_path,
        pid_file_path=pid_file_path,
        idle_timeout_seconds=600,
        log_level=LogLevel.DEBUG,
    )


def _make_daemon(socket_path: Path, pid_file_path: Path | None = None) -> HooksDaemon:
    return HooksDaemon(
        config=_make_config(socket_path, pid_file_path),
        controller=_FakeController(),
    )


# --------------------------------------------------------------------------- #
# Timeout constant
# --------------------------------------------------------------------------- #


def test_socket_liveness_probe_timeout_constant_exists() -> None:
    """A named probe-timeout constant must exist (no magic value)."""
    assert hasattr(Timeout, "SOCKET_LIVENESS_PROBE_SEC")
    assert Timeout.SOCKET_LIVENESS_PROBE_SEC > 0


# --------------------------------------------------------------------------- #
# _probe_socket_live / _socket_is_live
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_probe_socket_live_true_when_listener_present(tmp_path: Path) -> None:
    """A real asyncio unix listener => probe returns True."""
    sock_path = tmp_path / "live.sock"

    async def _noop(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()

    server = await asyncio.start_unix_server(_noop, path=str(sock_path))
    try:
        assert await _probe_socket_live(sock_path) is True
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.anyio
async def test_probe_socket_live_false_when_refused(tmp_path: Path) -> None:
    """A socket FILE on disk with no listener => probe returns False."""
    sock_path = tmp_path / "orphan.sock"
    # Bind then close => the socket inode remains on disk but nobody listens.
    s = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    s.bind(str(sock_path))
    s.close()
    assert sock_path.exists()
    assert await _probe_socket_live(sock_path) is False


@pytest.mark.anyio
async def test_probe_socket_live_false_when_missing_file(tmp_path: Path) -> None:
    """A nonexistent path => probe returns False."""
    assert await _probe_socket_live(tmp_path / "nope.sock") is False


@pytest.mark.anyio
async def test_probe_socket_live_false_on_timeout(tmp_path: Path) -> None:
    """A listener that never accepts within the budget => NOT a definitive live.

    The boolean wrapper returns False (only a definitive LIVE => True), but the
    three-state probe must classify a timeout as INDETERMINATE — see
    ``test_probe_socket_liveness_indeterminate_on_timeout`` — so the caller does
    NOT treat it as safe-to-unlink.
    """
    sock_path = tmp_path / "wedged.sock"

    # A raw AF_UNIX listening socket with backlog that we never accept() from.
    # connect() still succeeds at the kernel level for AF_UNIX SOCK_STREAM, so
    # to force a real accept-stall we patch open_unix_connection to hang.
    async def _never_returns(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(Timeout.SOCKET_LIVENESS_PROBE_SEC * 10)

    s = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    s.bind(str(sock_path))
    s.listen(1)
    try:
        with patch(
            "claude_code_hooks_daemon.daemon.server.asyncio.open_unix_connection",
            side_effect=_never_returns,
        ):
            assert await _probe_socket_live(sock_path) is False
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# _probe_socket_liveness — three-state (Plan 00127, Finding 1)
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_probe_socket_liveness_live_when_listener_present(tmp_path: Path) -> None:
    """A real listener => LIVE."""
    sock_path = tmp_path / "live.sock"

    async def _noop(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()

    server = await asyncio.start_unix_server(_noop, path=str(sock_path))
    try:
        assert await _probe_socket_liveness(sock_path) is _SocketLiveness.LIVE
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.anyio
async def test_probe_socket_liveness_not_live_when_refused(tmp_path: Path) -> None:
    """An orphaned socket inode (ConnectionRefused) => DEFINITIVE NOT_LIVE."""
    sock_path = tmp_path / "orphan.sock"
    s = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    s.bind(str(sock_path))
    s.close()
    assert await _probe_socket_liveness(sock_path) is _SocketLiveness.NOT_LIVE


@pytest.mark.anyio
async def test_probe_socket_liveness_not_live_when_missing(tmp_path: Path) -> None:
    """A nonexistent path (FileNotFoundError) => DEFINITIVE NOT_LIVE."""
    assert await _probe_socket_liveness(tmp_path / "nope.sock") is _SocketLiveness.NOT_LIVE


@pytest.mark.anyio
async def test_probe_socket_liveness_indeterminate_on_timeout(tmp_path: Path) -> None:
    """A probe timeout (busy-but-maybe-live daemon) => INDETERMINATE, NOT not-live."""
    sock_path = tmp_path / "busy.sock"

    async def _never_returns(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(Timeout.SOCKET_LIVENESS_PROBE_SEC * 10)

    s = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    s.bind(str(sock_path))
    s.listen(1)
    try:
        with patch(
            "claude_code_hooks_daemon.daemon.server.asyncio.open_unix_connection",
            side_effect=_never_returns,
        ):
            assert await _probe_socket_liveness(sock_path) is _SocketLiveness.INDETERMINATE
    finally:
        s.close()


@pytest.mark.anyio
async def test_probe_socket_liveness_indeterminate_on_transient_oserror(tmp_path: Path) -> None:
    """A transient OSError (e.g. EMFILE in THIS process) => INDETERMINATE, NOT not-live.

    Under fd exhaustion the client socket fd cannot be created and
    open_unix_connection raises OSError BEFORE any connect against a live
    incumbent. This must NOT be read as 'stale, safe to unlink'.
    """
    sock_path = tmp_path / "live_but_emfile.sock"
    # A genuinely live listener is present...
    s = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    s.bind(str(sock_path))
    s.listen(1)
    try:

        async def _emfile(*args: Any, **kwargs: Any) -> Any:
            raise OSError(24, "Too many open files")  # EMFILE

        with patch(
            "claude_code_hooks_daemon.daemon.server.asyncio.open_unix_connection",
            side_effect=_emfile,
        ):
            assert await _probe_socket_liveness(sock_path) is _SocketLiveness.INDETERMINATE
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# _pid_file_points_at_live_process (Plan 00127, Finding 1)
# --------------------------------------------------------------------------- #


def test_pid_file_points_at_live_process_true_for_self(tmp_path: Path) -> None:
    """A PID file naming this live process => True."""
    import os

    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text(str(os.getpid()))
    assert _pid_file_points_at_live_process(pid_path) is True


def test_pid_file_points_at_live_process_false_when_missing(tmp_path: Path) -> None:
    """A missing PID file => False."""
    assert _pid_file_points_at_live_process(tmp_path / "absent.pid") is False
    assert _pid_file_points_at_live_process(None) is False


def test_pid_file_points_at_live_process_false_for_dead_pid(tmp_path: Path) -> None:
    """A PID file naming a dead process => False."""
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("999999")
    with patch(
        "claude_code_hooks_daemon.daemon.server.os.kill",
        side_effect=ProcessLookupError(),
    ):
        assert _pid_file_points_at_live_process(pid_path) is False


def test_pid_file_points_at_live_process_false_for_garbage(tmp_path: Path) -> None:
    """A malformed PID file => False (treated as no live incumbent)."""
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("not-a-pid")
    assert _pid_file_points_at_live_process(pid_path) is False


@pytest.mark.parametrize("text", ["0", "-1", "1", "007", " 12 "])
def test_pid_file_points_at_live_process_false_for_what_names_no_pid(
    tmp_path: Path, text: str
) -> None:
    """Plan 00466 round 6 (Sh-3): ``int()`` read ``0`` and ``-1`` as pids,
    and signal 0 to either succeeds against this process's own group or
    every process, so a corrupt PID file read as a live incumbent and the
    child would not clear a dead socket. Signal 0 only: nothing is sent."""
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text(text)
    assert _pid_file_points_at_live_process(pid_path) is False


def test_socket_is_live_sync_wrapper_false_when_missing(tmp_path: Path) -> None:
    """Sync wrapper usable outside an event loop; missing path => False."""
    assert _socket_is_live(tmp_path / "missing.sock") is False


def test_socket_is_live_sync_wrapper_true_when_listener(tmp_path: Path) -> None:
    """Sync wrapper returns True against a real listener (spawned in a thread)."""
    sock_path = tmp_path / "live2.sock"

    async def _run() -> None:
        async def _noop(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writer.close()

        server = await asyncio.start_unix_server(_noop, path=str(sock_path))
        try:
            # Call the sync wrapper from a worker thread (no running loop there).
            result = await asyncio.to_thread(_socket_is_live, sock_path)
            assert result is True
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# HooksDaemon.start() — live vs stale socket
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_start_does_not_unlink_live_socket(tmp_path: Path) -> None:
    """start() must NOT steal a live incumbent's socket; it raises instead."""
    sock_path = tmp_path / "incumbent.sock"

    accepted: list[bool] = []

    async def _accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.append(True)
        writer.close()

    incumbent = await asyncio.start_unix_server(_accept, path=str(sock_path))
    try:
        daemon = _make_daemon(sock_path)
        with pytest.raises(DaemonAlreadyRunningError):
            await daemon.start()

        # The original socket file must still exist and still accept connections.
        assert sock_path.exists()
        _reader, writer = await asyncio.open_unix_connection(path=str(sock_path))
        writer.close()
        await writer.wait_closed()
        assert accepted, "incumbent listener should still be answering"
    finally:
        incumbent.close()
        await incumbent.wait_closed()


@pytest.mark.anyio
async def test_start_unlinks_and_binds_stale_socket(tmp_path: Path) -> None:
    """start() must unlink a genuinely stale socket file and bind successfully."""
    sock_path = tmp_path / "stale.sock"
    # Create a stale socket inode (bind then close — no listener).
    s = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    s.bind(str(sock_path))
    s.close()
    assert sock_path.exists()

    daemon = _make_daemon(sock_path)
    # Run start() in the background; it will block on shutdown_event.wait().
    start_task = asyncio.create_task(daemon.start())
    try:
        # Wait until the new server is bound and listening.
        for _ in range(50):
            await asyncio.sleep(0.05)
            if daemon.server is not None and await _probe_socket_live(sock_path):
                break
        assert daemon.server is not None
        assert await _probe_socket_live(sock_path) is True
    finally:
        await daemon.shutdown()
        await asyncio.wait_for(start_task, timeout=Timeout.SOCKET_CONNECT)


# --------------------------------------------------------------------------- #
# _write_pid_file — live vs stale incumbent
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_write_pid_file_raises_when_incumbent_alive_and_socket_live(
    tmp_path: Path,
) -> None:
    """A live PID + live socket => _write_pid_file must NOT clobber; it raises.

    Plan 00127 Finding 4: the gate now AWAITS the real probe (the old sync
    _socket_is_live returned False inside the running loop, making this branch
    dead). We patch the async probe so the gate is exercised effectively.
    """
    sock_path = tmp_path / "pid_live.sock"
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("4242")

    daemon = _make_daemon(sock_path, pid_file_path=pid_path)

    async def _live(_path: Path) -> bool:
        return True

    with (
        patch(
            "claude_code_hooks_daemon.daemon.server.os.kill",
            return_value=None,  # os.kill(pid, 0) succeeds => alive
        ),
        patch(
            "claude_code_hooks_daemon.daemon.server._probe_socket_live",
            side_effect=_live,
        ),
    ):
        with pytest.raises(DaemonAlreadyRunningError):
            await daemon._write_pid_file()

    # PID file must be untouched (still the incumbent's PID).
    assert pid_path.read_text().strip() == "4242"


@pytest.mark.anyio
async def test_write_pid_file_overwrites_when_old_pid_dead(tmp_path: Path) -> None:
    """A stale PID (ProcessLookupError) => _write_pid_file overwrites as before."""
    sock_path = tmp_path / "pid_stale.sock"
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("999999")

    daemon = _make_daemon(sock_path, pid_file_path=pid_path)

    with patch(
        "claude_code_hooks_daemon.daemon.server.os.kill",
        side_effect=ProcessLookupError(),
    ):
        await daemon._write_pid_file()

    # PID file overwritten with our own PID.
    import os

    assert pid_path.read_text().strip() == str(os.getpid())


@pytest.mark.anyio
@pytest.mark.parametrize("text", ["0", "-1", "1", "007", "+12", "1_2"])
async def test_write_pid_file_treats_text_that_is_no_daemons_pid_as_stale(
    tmp_path: Path, text: str
) -> None:
    """Plan 00466 round 5 (P4-4): ``int()`` read ``0`` as a pid, and
    ``kill(0, 0)`` succeeds against this daemon's own process group, so with
    the socket live a corrupt file refused the start as a live incumbent.
    The shared parser never probes it."""
    import os

    sock_path = tmp_path / "pid_corrupt.sock"
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text(text)
    daemon = _make_daemon(sock_path, pid_file_path=pid_path)

    async def _live(_path: Path) -> bool:
        return True

    with (
        patch("claude_code_hooks_daemon.daemon.server.os.kill") as kill,
        patch(
            "claude_code_hooks_daemon.daemon.server._probe_socket_live",
            side_effect=_live,
        ),
    ):
        await daemon._write_pid_file()

    kill.assert_not_called()
    assert pid_path.read_text().strip() == str(os.getpid())


@pytest.mark.anyio
async def test_write_pid_file_overwrites_when_pid_live_but_socket_dead(
    tmp_path: Path,
) -> None:
    """A live PID with a NOT-live socket (wedged/half-dead) => overwrite."""
    import os

    sock_path = tmp_path / "pid_wedged.sock"
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("4242")

    daemon = _make_daemon(sock_path, pid_file_path=pid_path)

    async def _not_live(_path: Path) -> bool:
        return False

    with (
        patch(
            "claude_code_hooks_daemon.daemon.server.os.kill",
            return_value=None,  # incumbent PID is alive
        ),
        patch(
            "claude_code_hooks_daemon.daemon.server._probe_socket_live",
            side_effect=_not_live,
        ),
    ):
        await daemon._write_pid_file()

    assert pid_path.read_text().strip() == str(os.getpid())


# --------------------------------------------------------------------------- #
# start()/_reuse_or_clear_socket — never unlink a LIVE or INDETERMINATE socket
# (Plan 00127, Finding 1)
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_start_does_not_unlink_busy_live_socket_on_timeout(tmp_path: Path) -> None:
    """A busy-but-live incumbent (probe times out) with a live PID must be REUSED,
    never unlinked. Finding 1: timeout maps to INDETERMINATE, not not-live."""
    import os

    sock_path = tmp_path / "busy.sock"
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text(str(os.getpid()))  # a live PID (ours)

    # A real listening socket exists on disk (so .exists() is True), but we
    # force the probe to time out as if the daemon's loop is mid-dispatch.
    s = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    s.bind(str(sock_path))
    s.listen(1)

    async def _timeout(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(Timeout.SOCKET_LIVENESS_PROBE_SEC * 10)

    daemon = _make_daemon(sock_path, pid_file_path=pid_path)
    try:
        with patch(
            "claude_code_hooks_daemon.daemon.server.asyncio.open_unix_connection",
            side_effect=_timeout,
        ):
            with pytest.raises(DaemonAlreadyRunningError):
                await daemon.start()
        # The incumbent socket inode must still be on disk (NOT unlinked).
        assert sock_path.exists()
    finally:
        s.close()


@pytest.mark.anyio
async def test_start_does_not_unlink_live_socket_on_transient_oserror(tmp_path: Path) -> None:
    """A transient OSError (EMFILE) probing a live incumbent must NOT unlink it."""
    import os

    sock_path = tmp_path / "live_emfile.sock"
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text(str(os.getpid()))

    s = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    s.bind(str(sock_path))
    s.listen(1)

    async def _emfile(*args: Any, **kwargs: Any) -> Any:
        raise OSError(24, "Too many open files")

    daemon = _make_daemon(sock_path, pid_file_path=pid_path)
    try:
        with patch(
            "claude_code_hooks_daemon.daemon.server.asyncio.open_unix_connection",
            side_effect=_emfile,
        ):
            with pytest.raises(DaemonAlreadyRunningError):
                await daemon.start()
        assert sock_path.exists()
    finally:
        s.close()


@pytest.mark.anyio
async def test_start_does_not_unlink_indeterminate_socket_without_pid(tmp_path: Path) -> None:
    """An INDETERMINATE probe with NO live PID still must not unlink — it cannot
    be PROVEN stale, so fail safe (a dead daemon leaves a refused, NOT_LIVE socket)."""
    sock_path = tmp_path / "indeterminate.sock"
    # No PID file at all.

    s = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    s.bind(str(sock_path))
    s.listen(1)

    async def _timeout(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(Timeout.SOCKET_LIVENESS_PROBE_SEC * 10)

    daemon = _make_daemon(sock_path, pid_file_path=tmp_path / "absent.pid")
    try:
        with patch(
            "claude_code_hooks_daemon.daemon.server.asyncio.open_unix_connection",
            side_effect=_timeout,
        ):
            with pytest.raises(DaemonAlreadyRunningError):
                await daemon.start()
        assert sock_path.exists()
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# start() under contention — atomic acquisition (Plan 00127, Finding 3)
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_concurrent_starts_yield_single_daemon(tmp_path: Path) -> None:
    """Two near-simultaneous fresh starts on one socket must not orphan a daemon.

    With the start-lock serialising the probe->unlink->bind section, exactly one
    start binds successfully; the other observes the winner LIVE and reuses
    (raises DaemonAlreadyRunningError). The surviving socket still answers.
    """
    sock_path = tmp_path / "race.sock"
    pid_path = tmp_path / "daemon.pid"

    daemon_a = _make_daemon(sock_path, pid_file_path=pid_path)
    daemon_b = _make_daemon(sock_path, pid_file_path=pid_path)

    task_a = asyncio.create_task(daemon_a.start())
    task_b = asyncio.create_task(daemon_b.start())

    # Give both a moment to contend for the lock and bind.
    winners: list[HooksDaemon] = []
    reuse_errors = 0
    try:
        for _ in range(60):
            await asyncio.sleep(0.05)
            if (daemon_a.server is not None) or (daemon_b.server is not None):
                break

        # Whichever lost should have completed with DaemonAlreadyRunningError.
        for task, daemon in ((task_a, daemon_a), (task_b, daemon_b)):
            if task.done():
                exc = task.exception()
                if isinstance(exc, DaemonAlreadyRunningError):
                    reuse_errors += 1
            if daemon.server is not None:
                winners.append(daemon)

        assert len(winners) == 1, "exactly one daemon must own the socket"
        assert reuse_errors == 1, "the loser must reuse via DaemonAlreadyRunningError"
        # The winner's socket is live.
        assert await _probe_socket_live(sock_path) is True
    finally:
        for daemon in winners:
            await daemon.shutdown()
        for task in (task_a, task_b):
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, timeout=Timeout.SOCKET_CONNECT)


@pytest.mark.anyio
async def test_a_start_waiting_on_anothers_lock_says_so_and_when_it_has_it(
    tmp_path: Path,
) -> None:
    """Review 8, R8-2: the wait spends no CPU and finishes no step, so its
    launcher read it as a stall unless it is told."""
    sock_path = tmp_path / "held.sock"
    reports: list[bool] = []
    daemon = HooksDaemon(
        config=_make_config(sock_path),
        controller=_FakeController(),
        start_lock_waiting=reports.append,
    )
    with hold_start_lock(sock_path, Timeout.FILE_LOCK):
        start_task = asyncio.create_task(daemon.start())
        while not reports:
            await asyncio.sleep(0.01)
        assert reports == [True]
        assert daemon.server is None
    try:
        await asyncio.wait_for(daemon.started_event.wait(), timeout=Timeout.SOCKET_CONNECT)
        assert reports == [True, False]
    finally:
        await daemon.shutdown()
        await asyncio.wait_for(start_task, timeout=Timeout.SOCKET_CONNECT)


@pytest.mark.anyio
async def test_a_start_that_takes_the_lock_at_once_reports_no_wait(tmp_path: Path) -> None:
    reports: list[bool] = []
    daemon = HooksDaemon(
        config=_make_config(tmp_path / "free.sock"),
        controller=_FakeController(),
        start_lock_waiting=reports.append,
    )
    start_task = asyncio.create_task(daemon.start())
    try:
        await asyncio.wait_for(daemon.started_event.wait(), timeout=Timeout.SOCKET_CONNECT)
        assert reports == []
    finally:
        await daemon.shutdown()
        await asyncio.wait_for(start_task, timeout=Timeout.SOCKET_CONNECT)


@pytest.mark.anyio
async def test_a_start_says_when_it_serves_and_not_before(tmp_path: Path) -> None:
    """Round 8b: the launch lock is released once the daemon serves, so
    ``serving`` is called only after both binding steps."""
    served: list[bool] = []
    daemon = HooksDaemon(
        config=_make_config(tmp_path / "s.sock"),
        controller=_FakeController(),
        serving=lambda: served.append(daemon.started_event.is_set()),
    )
    start_task = asyncio.create_task(daemon.start())
    try:
        await asyncio.wait_for(daemon.started_event.wait(), timeout=Timeout.SOCKET_CONNECT)
        assert served == [True]
    finally:
        await daemon.shutdown()
        await asyncio.wait_for(start_task, timeout=Timeout.SOCKET_CONNECT)


class TestTheLaunchLock:
    """Plan 00466 lifecycle round 8b: the lock a start holds from its
    launch until its daemon serves. flock is per open file, so a second
    open in this process contends with the first as another process would."""

    @staticmethod
    def _clock() -> Any:
        """``server``'s clock, advanced only by its own sleeps."""
        now = [0.0]
        clock = MagicMock(wraps=time)
        clock.monotonic.side_effect = lambda: now[0]
        clock.sleep.side_effect = lambda seconds: now.__setitem__(0, now[0] + seconds)
        return patch("claude_code_hooks_daemon.daemon.server.time", clock)

    def test_it_is_the_projects_whatever_socket_a_start_uses(self, tmp_path: Path) -> None:
        """Review 9, DR-4: enforcement picks its targets by project root, so
        every start of one project takes one lock, and a start through a
        link to the project takes the same one."""
        project = tmp_path / "project"
        project.mkdir()
        (tmp_path / "link").symlink_to(project)
        path = launch_lock_path(project)
        assert path == launch_lock_path(tmp_path / "link")
        assert path != launch_lock_path(tmp_path / "other")
        assert path.name == "daemon.launch.lock"

    def test_the_stale_file_reaper_never_removes_it(self, tmp_path: Path) -> None:
        """A start reaps before it takes the lock; a lock unlinked under a
        holder leaves the next start a fresh file, excluding nobody."""
        path = launch_lock_path(tmp_path)
        LaunchLock.take(path, Timeout.FILE_LOCK).release()
        long_ago = time.time() - 365 * 86400
        os.utime(path, (long_ago, long_ago))

        cleanup_stale_daemon_files(tmp_path, max_age_days=1)

        assert path.exists()

    def test_a_second_start_waits_out_its_budget_on_a_start_under_way(self, tmp_path: Path) -> None:
        path = launch_lock_path(tmp_path)
        first = LaunchLock.take(path, Timeout.FILE_LOCK)
        try:
            with self._clock(), pytest.raises(StartLockTimeout):
                LaunchLock.take(path, Timeout.DAEMON_START_BUDGET_SEC)
        finally:
            first.release()

    def test_a_start_that_ended_leaves_it_free(self, tmp_path: Path) -> None:
        path = launch_lock_path(tmp_path)
        LaunchLock.take(path, Timeout.FILE_LOCK).release()
        LaunchLock.take(path, Timeout.FILE_LOCK).release()

    def test_a_forked_holder_keeps_it_when_the_launcher_closes_its_copy(
        self, tmp_path: Path
    ) -> None:
        """``close`` is the launcher's, after the fork: the daemon holding
        the same open file keeps the start under way. A dup stands in for
        the forked copy."""
        path = launch_lock_path(tmp_path)
        path.parent.mkdir(parents=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        launcher = LaunchLock(fd, path)
        daemon = LaunchLock(os.dup(fd), path)
        launcher.close()
        try:
            under_way = start_under_way(path)
            assert under_way is not None and under_way.pid is None
        finally:
            daemon.release()
        assert start_under_way(path) is None

    def test_the_daemon_it_names_is_the_start_under_way(self, tmp_path: Path) -> None:
        path = launch_lock_path(tmp_path)
        held = LaunchLock.take(path, Timeout.FILE_LOCK)
        try:
            held.name_holder()
            assert start_under_way(path) == StartUnderWay(pid=os.getpid(), written_at=ANY)
        finally:
            held.release()

    def test_it_says_when_the_lock_was_last_written(self, tmp_path: Path) -> None:
        """Review 10, R10-3: the holder takes the lock, and the daemon names
        itself, after each started; ``stop`` refuses a process that started
        later, whose pid was reused."""
        path = launch_lock_path(tmp_path)
        held = LaunchLock.take(path, Timeout.FILE_LOCK)
        try:
            held.name_holder()
            under_way = start_under_way(path)
            assert under_way is not None
            assert under_way.written_at == path.stat().st_mtime
        finally:
            held.release()

    def test_a_pid_an_earlier_start_left_names_nobody(self, tmp_path: Path) -> None:
        path = launch_lock_path(tmp_path)
        earlier = LaunchLock.take(path, Timeout.FILE_LOCK)
        earlier.name_holder()
        earlier.release()
        held = LaunchLock.take(path, Timeout.FILE_LOCK)
        try:
            under_way = start_under_way(path)
            assert under_way is not None and under_way.pid is None
        finally:
            held.release()

    def test_no_start_under_way_is_none(self, tmp_path: Path) -> None:
        assert start_under_way(launch_lock_path(tmp_path)) is None

    def test_a_planted_symlink_is_refused(self, tmp_path: Path) -> None:
        path = launch_lock_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.symlink_to(tmp_path / "planted")
        with pytest.raises(OSError):
            LaunchLock.take(path, Timeout.FILE_LOCK)
        with pytest.raises(OSError):
            start_under_way(path)
        assert not (tmp_path / "planted").exists()


#: Takes the launch lock named by argv[1], says so, and holds it until stdin closes.
_HOLD_THE_LOCK = (
    "import fcntl, os, sys; fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600); "
    "fcntl.flock(fd, fcntl.LOCK_EX); print(os.getpid(), flush=True); sys.stdin.read()"
)
#: As _HOLD_THE_LOCK, but the taker forks and exits, leaving its child the lock.
_HAND_THE_LOCK_ON = (
    "import fcntl, os, sys; fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600); "
    "fcntl.flock(fd, fcntl.LOCK_EX)\n"
    "if os.fork():\n    os._exit(0)\n"
    "print(os.getpid(), flush=True); sys.stdin.read()"
)


class TestTheLaunchLocksHolderBeforeItNamesADaemon:
    """Review 9, DR-5: a launcher that hangs before its fork holds the lock
    and names nothing. The kernel's lock table names it, by the pid that
    took the lock and the file's inode; it must still hold the file open."""

    @contextlib.contextmanager
    def _held(self, path: Path, program: str) -> Iterator[int]:
        """A real process holding ``path`` locked; yields the pid it prints.

        It ends when its stdin closes, so no signal is ever sent to it."""
        path.parent.mkdir(parents=True, exist_ok=True)
        holder = subprocess.Popen(
            [sys.executable, "-c", program, str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        assert holder.stdin is not None and holder.stdout is not None
        try:
            yield int(holder.stdout.readline())
        finally:
            holder.stdin.close()
            holder.wait(timeout=Timeout.PROCESS_SAMPLE)
            holder.stdout.close()

    def test_a_launcher_holding_it_is_named_by_the_lock_table(self, tmp_path: Path) -> None:
        path = launch_lock_path(tmp_path)
        with self._held(path, _HOLD_THE_LOCK) as launcher:
            assert start_under_way(path) == StartUnderWay(pid=None, holder=launcher, written_at=ANY)

    def test_a_taker_that_has_exited_names_no_holder(self, tmp_path: Path) -> None:
        """The table still names the pid that took the lock; the child now
        holding it is not that pid, so nothing is named."""
        path = launch_lock_path(tmp_path)
        with self._held(path, _HAND_THE_LOCK_ON):
            assert start_under_way(path) == StartUnderWay(pid=None, holder=None, written_at=ANY)

    def test_no_lock_table_names_no_holder(self, tmp_path: Path) -> None:
        path = launch_lock_path(tmp_path)
        with (
            self._held(path, _HOLD_THE_LOCK),
            patch("claude_code_hooks_daemon.daemon.server._PROC_LOCKS", tmp_path / "no-lock-table"),
        ):
            assert start_under_way(path) == StartUnderWay(pid=None, holder=None, written_at=ANY)

    def test_a_table_line_for_another_file_names_no_holder(self, tmp_path: Path) -> None:
        """A candidate that does not hold this very file open is not its holder,
        whatever inode the table gives."""
        path = launch_lock_path(tmp_path)
        table = tmp_path / "locks"
        with self._held(path, _HOLD_THE_LOCK) as launcher:
            inode = path.stat().st_ino
            table.write_text(
                f"1: FLOCK  ADVISORY  WRITE {os.getppid()} 00:00:{inode} 0 EOF\n"
                f"2: -> FLOCK  ADVISORY  WRITE {launcher} 00:00:{inode} 0 EOF\n"
            )
            with patch("claude_code_hooks_daemon.daemon.server._PROC_LOCKS", table):
                assert start_under_way(path) == StartUnderWay(pid=None, holder=None, written_at=ANY)


def test_start_lock_path_is_sibling_of_socket(tmp_path: Path) -> None:
    """The start-lock file is a deterministic sibling of the socket path."""
    sock_path = tmp_path / "daemon.sock"
    lock_path = HooksDaemon._start_lock_path(sock_path)
    assert lock_path.parent == sock_path.parent
    assert lock_path.name.startswith(sock_path.name)
    assert lock_path != sock_path


# --------------------------------------------------------------------------- #
# The daemon's identity answer (Plan 00466 round 6, Sh-2)
# --------------------------------------------------------------------------- #


@pytest.fixture
def short_socket() -> Iterator[Path]:
    """AF_UNIX paths are capped near 108 bytes; ``tmp_path`` nests deeper."""
    directory = Path(tempfile.mkdtemp(prefix="hd-identity-"))
    yield directory / "daemon.sock"
    shutil.rmtree(directory)


@contextlib.contextmanager
def _serving_daemon(daemon: HooksDaemon, path: Path) -> Iterator[None]:
    """``daemon``'s own client handler, serving ``path`` from another thread."""
    loop = asyncio.new_event_loop()
    server = loop.run_until_complete(asyncio.start_unix_server(daemon._handle_client, str(path)))
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=Timeout.REQUEST_LONG)
        server.close()
        loop.run_until_complete(server.wait_closed())
        loop.close()


def test_the_daemon_answers_which_project_it_serves(tmp_path: Path, short_socket: Path) -> None:
    daemon = _make_daemon(short_socket)
    with (
        patch.object(ProjectContext, "project_root", return_value=tmp_path),
        _serving_daemon(daemon, short_socket),
    ):
        identity = daemon_socket_identity(short_socket)
    assert identity == DaemonIdentity(project_root=str(tmp_path), pid=os.getpid())


def test_a_daemon_that_does_not_know_its_project_gives_no_identity(
    short_socket: Path,
) -> None:
    daemon = _make_daemon(short_socket)
    with (
        patch.object(ProjectContext, "project_root", side_effect=RuntimeError("uninitialised")),
        _serving_daemon(daemon, short_socket),
    ):
        assert daemon_socket_identity(short_socket) is None


@pytest.mark.parametrize(
    "answer",
    [b"", b"not json\n", b"[]\n", b'{"result": {}}\n', b'{"result": {"project_root": 7}}\n'],
)
def test_a_listener_that_does_not_answer_as_a_daemon_gives_no_identity(
    short_socket: Path, answer: bytes
) -> None:
    listener = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    listener.bind(str(short_socket))
    listener.listen(1)

    def reply() -> None:
        connection, _ = listener.accept()
        with connection:
            connection.recv(4096)
            connection.sendall(answer)

    replier = threading.Thread(target=reply, daemon=True)
    replier.start()
    try:
        assert daemon_socket_identity(short_socket) is None
    finally:
        replier.join(timeout=Timeout.REQUEST_LONG)
        listener.close()


def test_no_socket_gives_no_identity(short_socket: Path) -> None:
    assert daemon_socket_identity(short_socket) is None
