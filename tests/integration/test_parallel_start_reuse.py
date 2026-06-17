"""Plan 00127: parallel same-root start reuses a single live daemon.

Empirical reproduction (context.md PIDs 272/274, one PID file): two starts
sharing one (hostname, project root) — and therefore one
``daemon-{hostname}.{sock,pid}`` — must NOT orphan the first daemon. The second
start must DETECT the live incumbent and REUSE it (exit 0, incumbent socket and
PID file untouched).

This drives the REAL liveness probe (``_socket_is_live``) and real
``read_pid_file`` against a real asyncio unix listener, then runs the real
``cmd_start`` parent path against the same socket/PID/root.
"""

import argparse
import asyncio
import os
import threading
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.cli import cmd_start


class _Listener:
    """A real asyncio unix-socket listener running in a background thread."""

    def __init__(self, sock_path: Path) -> None:
        self.sock_path = sock_path
        self.accepted = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        async def _accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            self.accepted += 1
            writer.close()

        server = await asyncio.start_unix_server(_accept, path=str(self.sock_path))
        self._ready.set()
        try:
            while not self._stop.is_set():
                await asyncio.sleep(0.05)
        finally:
            server.close()
            await server.wait_closed()

    def start(self) -> None:
        self._thread.start()
        assert self._ready.wait(timeout=Timeout.SOCKET_CONNECT), "listener failed to start"

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=Timeout.SOCKET_CONNECT)


def test_parallel_same_root_start_reuses_single_daemon(tmp_path: Path) -> None:
    """A second start against a live same-root daemon returns 0 via reuse:
    the socket file is untouched, the listener still answers, and the PID file
    still points at the incumbent."""
    sock_path = tmp_path / "daemon.sock"
    pid_path = tmp_path / "daemon.pid"

    listener = _Listener(sock_path)
    listener.start()

    # The incumbent's PID file points at THIS (live) process.
    incumbent_pid = os.getpid()
    pid_path.write_text(str(incumbent_pid))

    args = argparse.Namespace(
        project_root=tmp_path,
        socket=str(sock_path),
        pid_file=str(pid_path),
    )

    try:
        # Patch only the path resolvers so cmd_start uses our explicit paths;
        # the liveness probe and read_pid_file run for real.
        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.enforce_single_daemon") as mock_enforce,
            patch("os.fork") as mock_fork,
        ):
            result = cmd_start(args)

        assert result == 0, "second start must reuse the live incumbent"
        mock_enforce.assert_not_called()
        mock_fork.assert_not_called()

        # Incumbent untouched: socket file present and still connectable.
        assert sock_path.exists()
        client_loop = asyncio.new_event_loop()
        try:
            _reader, writer = client_loop.run_until_complete(
                asyncio.open_unix_connection(path=str(sock_path))
            )
            writer.close()
            client_loop.run_until_complete(writer.wait_closed())
        finally:
            client_loop.close()

        # PID file still points at the incumbent.
        assert pid_path.read_text().strip() == str(incumbent_pid)
    finally:
        listener.stop()
