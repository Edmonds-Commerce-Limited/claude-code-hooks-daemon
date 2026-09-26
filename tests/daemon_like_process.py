"""Stand-ins for a project's daemon, for tests that need one running (Plan 00466).

``init.sh``'s ``is_daemon_running`` counts a live pid as the daemon only when
it is proven (round 5, Sh-D): its command line is exactly the one
``start_daemon`` launches a daemon of the project with (round 6, P5-3), or
the daemon's socket answers as that project's daemon (round 6, Sh-2).

:func:`daemon_like_process` is a process with that command line. Its
``-m claude_code_hooks_daemon.daemon.cli`` runs a stand-in module that only
waits on its stdin, from a directory that comes first on its ``sys.path``,
so its arguments sit at the exact positions a real launch puts them. It ends
when the context closes that stdin: no signal is ever sent to it.

:func:`answering_daemon_socket` is a socket that answers the daemon's
identity request as a daemon of a given project, and :func:`silent_socket`
one that accepts every connection and never answers.
"""

from __future__ import annotations

import contextlib
import json
import socket
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

from claude_code_hooks_daemon.constants import Timeout

DAEMON_CLI_MODULE = "claude_code_hooks_daemon.daemon.cli"

#: How often the answering socket's accept loop checks it has been closed.
_ACCEPT_POLL_SEC = 0.05


def _write_stand_in_package(directory: Path) -> None:
    """A ``claude_code_hooks_daemon.daemon.cli`` that only waits on stdin."""
    package = directory / "claude_code_hooks_daemon"
    (package / "daemon").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "daemon" / "__init__.py").write_text("")
    (package / "daemon" / "cli.py").write_text("import sys\n\nsys.stdin.read()\n")


@contextlib.contextmanager
def daemon_like_process(project_root: Path) -> Iterator[int]:
    """Yield the pid of a process launched as ``project_root``'s daemon is."""
    with tempfile.TemporaryDirectory(prefix="daemon-like-") as stand_in:
        _write_stand_in_package(Path(stand_in))
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                DAEMON_CLI_MODULE,
                "--project-root",
                str(project_root),
                "start",
            ],
            cwd=stand_in,
            stdin=subprocess.PIPE,
        )
        try:
            yield process.pid
        finally:
            assert process.stdin is not None
            process.stdin.close()
            process.wait(timeout=Timeout.REQUEST_LONG)


def _answer(connection: socket.socket, project_root: Path, pid: int) -> None:
    """Answer one identity request on ``connection``; ignore anything else."""
    connection.settimeout(Timeout.SOCKET_LIVENESS_PROBE_SEC)
    with connection, connection.makefile("rb") as reader:
        try:
            request = json.loads(reader.readline() or b"null")
        except (TimeoutError, ValueError):
            return
        if not isinstance(request, dict) or request.get("event") != "_system":
            return
        answer = {"result": {"project_root": str(project_root), "pid": pid}}
        connection.sendall(json.dumps(answer).encode() + b"\n")


@contextlib.contextmanager
def _serving(path: Path, serve_one: Callable[[socket.socket], None]) -> Iterator[None]:
    """A socket at ``path`` handing each connection it accepts to ``serve_one``."""
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(8)
    listener.settimeout(_ACCEPT_POLL_SEC)
    closing = threading.Event()

    def serve() -> None:
        while not closing.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            serve_one(connection)

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    try:
        yield
    finally:
        closing.set()
        server.join(timeout=Timeout.REQUEST_LONG)
        listener.close()


@contextlib.contextmanager
def answering_daemon_socket(path: Path, project_root: Path, pid: int) -> Iterator[None]:
    """A socket at ``path`` answering as the daemon ``pid`` of ``project_root``."""
    with _serving(path, lambda connection: _answer(connection, project_root, pid)):
        yield


@contextlib.contextmanager
def silent_socket(path: Path) -> Iterator[list[socket.socket]]:
    """A socket at ``path`` accepting every connection and never answering;
    yields the connections it has accepted, which it holds open until it
    closes."""
    accepted: list[socket.socket] = []
    try:
        with _serving(path, accepted.append):
            yield accepted
    finally:
        for connection in accepted:
            connection.close()
