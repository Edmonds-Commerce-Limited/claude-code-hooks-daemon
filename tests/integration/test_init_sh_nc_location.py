"""init.sh's nc rung finds an overflow events dir through the daemon's location file (Plan 00609).

The generated forwarders carry no machine-specific events dir, so when the
natural ``untracked/events<suffix>`` does not exist the nc rung reads
``untracked/events<suffix>.location`` (line 1: the untracked dir it was written
for, line 2: the events dir). It is trusted only when line 1 is this checkout's
own untracked dir. The tests source a copy of the real init.sh and run the real
``send_request_stdin`` against a stub ``nc`` that reports the socket it was given.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_INIT_SH = Path(__file__).resolve().parents[2] / "init.sh"
_TIMEOUT_SECONDS = 30
_HOST = "testhost"

#: Prints the socket path it was given (its last argument) and drains stdin.
_STUB_NC = (
    '#!/bin/sh\nfor a; do last="$a"; done\ncat > /dev/null\nprintf "NC-SOCKET=%s\\n" "$last"\n'
)


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """Short, so socket paths stay under the AF_UNIX limit."""
    path = Path(tempfile.mkdtemp(prefix="nc-"))
    yield path
    shutil.rmtree(path)


def _project(root: Path) -> Path:
    claude = root / ".claude"
    claude.mkdir(parents=True)
    (claude / "init.sh").write_text(_INIT_SH.read_text())
    (claude / "hooks-daemon.env").write_text('export HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/d"\n')
    (root / "d" / "untracked").mkdir(parents=True)
    return root


def _stub_nc(root: Path) -> Path:
    bin_dir = root / "stubbin"
    bin_dir.mkdir()
    nc = bin_dir / "nc"
    nc.write_text(_STUB_NC)
    nc.chmod(0o755)
    return bin_dir


def _send(project: Path, stub_bin: Path) -> subprocess.CompletedProcess[str]:
    script = f'source "{project}/.claude/init.sh" >/dev/null 2>&1\nsend_request_stdin PreToolUse "" pre-tool-use ""\n'
    return subprocess.run(
        ["bash", "-c", script],
        input="{}",
        capture_output=True,
        text=True,
        env={
            "PATH": f"{stub_bin}:/usr/bin:/bin",
            "HOSTNAME": _HOST,
            "HOOKS_DAEMON_NC_UNIX_CAPABLE": "1",
            "HOME": str(project),
        },
        timeout=_TIMEOUT_SECONDS,
    )


def _listen(sock_path: Path) -> socket.socket:
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(sock_path))
    listener.listen(1)
    return listener


def test_a_location_naming_its_own_untracked_dir_is_used(short_dir: Path) -> None:
    project = _project(short_dir / "p")
    stub = _stub_nc(short_dir)
    untracked = project / "d" / "untracked"
    real_events = short_dir / "ev"
    listener = _listen(real_events / "pre-tool-use.sock")
    try:
        (untracked / f"events-{_HOST}.location").write_text(f"{untracked}\n{real_events}\n")
        result = _send(project, stub)
    finally:
        listener.close()

    assert f"NC-SOCKET={real_events}/pre-tool-use.sock" in result.stdout, result.stderr


def test_a_location_naming_another_checkouts_dir_is_ignored(short_dir: Path) -> None:
    project = _project(short_dir / "p")
    stub = _stub_nc(short_dir)
    untracked = project / "d" / "untracked"
    real_events = short_dir / "ev"
    listener = _listen(real_events / "pre-tool-use.sock")
    try:
        (untracked / f"events-{_HOST}.location").write_text(
            f"/another/checkout/untracked\n{real_events}\n"
        )
        result = _send(project, stub)
    finally:
        listener.close()

    assert "NC-SOCKET" not in result.stdout, "dialled another checkout's events dir"


def test_the_natural_events_dir_wins_and_the_location_is_not_consulted(short_dir: Path) -> None:
    project = _project(short_dir / "p")
    stub = _stub_nc(short_dir)
    untracked = project / "d" / "untracked"
    natural = untracked / f"events-{_HOST}"
    elsewhere = short_dir / "ev"
    listener = _listen(natural / "pre-tool-use.sock")
    other = _listen(elsewhere / "pre-tool-use.sock")
    try:
        (untracked / f"events-{_HOST}.location").write_text(f"{untracked}\n{elsewhere}\n")
        result = _send(project, stub)
    finally:
        listener.close()
        other.close()

    assert f"NC-SOCKET={natural}/pre-tool-use.sock" in result.stdout, result.stderr
