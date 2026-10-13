"""Plan 00517 Task 4.3: the sweep of dead per-host runtime sets.

Socket and pid paths are hostname-keyed, so every container restart leaves the
previous host's ``daemon-<id>.{sock,pid,sock.start.lock,socket-path}`` and
``events-<id>/`` behind. A set is swept only when EVERY socket in it refuses a
connection and its pid is not a live daemon. A listening socket (a host view
sharing the checkout) keeps its whole set. These tests use real AF_UNIX sockets.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import paths
from claude_code_hooks_daemon.daemon.paths import sweep_dead_runtime_sets

OWN_ID = "ownhost"


@pytest.fixture
def untracked() -> Iterator[Path]:
    """A SHORT directory (AF_UNIX paths are limited to ~108 bytes) used as untracked/."""
    root = Path(tempfile.mkdtemp(prefix="rs-", dir="/tmp"))
    directory = root / "untracked"
    directory.mkdir()
    with (
        patch.object(paths, "_get_untracked_dir", return_value=directory),
        patch.object(paths, "_get_hostname_suffix", return_value=f"-{OWN_ID}"),
    ):
        yield directory
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def listeners() -> Iterator[list[socket.socket]]:
    """Sockets a test left listening, closed afterwards."""
    held: list[socket.socket] = []
    yield held
    for sock in held:
        sock.close()


def _dead_socket(path: Path) -> None:
    """A socket file nothing listens on: bound, then closed, so the file stays."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    sock.close()


def _listening_socket(path: Path, listeners: list[socket.socket]) -> None:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    sock.listen(1)
    listeners.append(sock)


def _dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def _dead_set(untracked: Path, ident: str) -> list[Path]:
    """A whole dead set for host ``ident``: socket, pid, start lock, discovery, events dir."""
    sock = untracked / f"daemon-{ident}.sock"
    _dead_socket(sock)
    pid_file = untracked / f"daemon-{ident}.pid"
    pid_file.write_text(str(_dead_pid()))
    lock = untracked / f"daemon-{ident}.sock.start.lock"
    lock.write_text("")
    discovery = untracked / f"daemon-{ident}.socket-path"
    discovery.write_text(str(sock))
    events = untracked / f"events-{ident}"
    events.mkdir()
    _dead_socket(events / "pre-tool-use.sock")
    return [sock, pid_file, lock, discovery, events]


def _sweep() -> list[Path]:
    return sweep_dead_runtime_sets(Path("/unused"), min_age_seconds=0.0)


def _relisten(path: Path, listeners: list[socket.socket]) -> None:
    """Replace a dead socket file with a listening one."""
    path.unlink()
    _listening_socket(path, listeners)


class TestSweepDeadRuntimeSets:
    def test_a_dead_set_is_removed_whole(
        self, untracked: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        members = _dead_set(untracked, "deadhost")

        with caplog.at_level(logging.INFO, logger=paths.logger.name):
            removed = _sweep()

        assert sorted(removed) == sorted(members)
        assert not any(member.exists() for member in members)
        assert all(str(member) in caplog.text for member in members)

    def test_a_listening_socket_keeps_the_whole_set(
        self, untracked: Path, listeners: list[socket.socket]
    ) -> None:
        # A host view sharing the checkout: its daemon socket listens, while a
        # per-event socket beside it happens to be dead. Nothing in the set goes.
        members = _dead_set(untracked, "peerhost")
        _relisten(untracked / "daemon-peerhost.sock", listeners)

        assert _sweep() == []

        assert all(member.exists() for member in members)

    def test_a_listening_event_socket_keeps_the_whole_set(
        self, untracked: Path, listeners: list[socket.socket]
    ) -> None:
        members = _dead_set(untracked, "peerhost")
        _relisten(untracked / "events-peerhost" / "pre-tool-use.sock", listeners)

        assert _sweep() == []

        assert all(member.exists() for member in members)

    def test_a_socket_named_by_the_discovery_file_keeps_the_set(
        self, untracked: Path, listeners: list[socket.socket]
    ) -> None:
        # A long project path puts the real socket elsewhere; the discovery
        # file names it, and it is probed like any other.
        members = _dead_set(untracked, "peerhost")
        elsewhere = untracked.parent / "run.sock"
        _listening_socket(elsewhere, listeners)
        (untracked / "daemon-peerhost.socket-path").write_text(str(elsewhere))

        assert _sweep() == []

        assert all(member.exists() for member in members)

    def test_a_live_daemon_pid_keeps_the_set(self, untracked: Path) -> None:
        members = _dead_set(untracked, "peerhost")

        with patch.object(paths, "read_pid_file", return_value=4242) as read_pid:
            assert _sweep() == []

        read_pid.assert_called_once_with(untracked / "daemon-peerhost.pid", verify_daemon=True)
        assert all(member.exists() for member in members)

    def test_this_hosts_own_set_is_never_swept(self, untracked: Path) -> None:
        own = _dead_set(untracked, OWN_ID)

        assert _sweep() == []

        assert all(member.exists() for member in own)

    def test_only_the_dead_set_goes_when_two_sets_differ(
        self, untracked: Path, listeners: list[socket.socket]
    ) -> None:
        dead = _dead_set(untracked, "deadhost")
        alive = _dead_set(untracked, "alivehost")
        _relisten(untracked / "daemon-alivehost.sock", listeners)

        removed = _sweep()

        assert sorted(removed) == sorted(dead)
        assert all(member.exists() for member in alive)

    def test_a_set_touched_within_the_grace_period_is_left(self, untracked: Path) -> None:
        # A peer's start creates its start lock, then its pid and sockets; a set
        # written this minute may be mid-start.
        members = _dead_set(untracked, "deadhost")

        assert sweep_dead_runtime_sets(Path("/unused")) == []

        assert all(member.exists() for member in members)

    def test_a_set_past_the_grace_period_is_swept(self, untracked: Path) -> None:
        members = _dead_set(untracked, "deadhost")
        old = 1_700_000_000
        for member in [*members, untracked / "events-deadhost" / "pre-tool-use.sock"]:
            os.utime(member, (old, old), follow_symlinks=False)

        assert sorted(sweep_dead_runtime_sets(Path("/unused"))) == sorted(members)

    def test_dotted_hostnames_group_into_one_set(self, untracked: Path) -> None:
        members = _dead_set(untracked, "work.local")

        assert sorted(_sweep()) == sorted(members)

    def test_files_that_are_not_a_set_are_untouched(self, untracked: Path) -> None:
        files = [untracked / "daemon.launch.lock", untracked / "daemon-deadhost.log"]
        directories = [untracked / "events", untracked / "venv-x"]
        for file in files:
            file.write_text("")
        for directory in directories:
            directory.mkdir()

        assert _sweep() == []

        assert all(path.exists() for path in [*files, *directories])

    def test_a_removal_that_fails_leaves_that_member_and_the_rest_carry_on(
        self, untracked: Path
    ) -> None:
        _dead_set(untracked, "deadhost")

        with patch("shutil.rmtree", side_effect=PermissionError("denied")):
            removed = _sweep()

        assert untracked / "events-deadhost" not in removed
        assert (untracked / "events-deadhost").is_dir()
        assert not (untracked / "daemon-deadhost.sock").exists()
        assert not (untracked / "daemon-deadhost.pid").exists()

    def test_nothing_to_do_without_an_untracked_directory(self, tmp_path: Path) -> None:
        with patch.object(paths, "_get_untracked_dir", return_value=tmp_path / "missing"):
            assert sweep_dead_runtime_sets(Path("/unused"), min_age_seconds=0.0) == []


class TestSocketIsDead:
    def test_a_missing_socket_file_is_dead(self, untracked: Path) -> None:
        assert paths._socket_is_dead(untracked / "gone.sock") is True

    def test_a_regular_file_is_dead(self, untracked: Path) -> None:
        plain = untracked / "plain.sock"
        plain.write_text("x")

        assert paths._socket_is_dead(plain) is True

    def test_a_listening_socket_is_alive(
        self, untracked: Path, listeners: list[socket.socket]
    ) -> None:
        _listening_socket(untracked / "up.sock", listeners)

        assert paths._socket_is_dead(untracked / "up.sock") is False

    @pytest.mark.parametrize("error", [PermissionError("no"), TimeoutError("slow"), OSError("?")])
    def test_any_other_failure_is_not_proof_of_death(self, untracked: Path, error: OSError) -> None:
        with patch.object(socket.socket, "connect", side_effect=error):
            assert paths._socket_is_dead(untracked / "x.sock") is False
