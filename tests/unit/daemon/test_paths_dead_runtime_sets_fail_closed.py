"""Review round 1: a runtime set is dead only when that is PROVEN from this container.

A socket outside the untracked dir (a fallback runtime dir) may live in a
namespace this container does not share, so a refused connect to it proves
nothing and the set is kept.
"""

from __future__ import annotations

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
from claude_code_hooks_daemon.daemon.paths import (
    peer_runtime_sets_not_proven_dead,
    sweep_dead_runtime_sets,
)


@pytest.fixture
def untracked() -> Iterator[Path]:
    root = Path(tempfile.mkdtemp(prefix="fc-", dir="/tmp"))
    directory = root / "untracked"
    directory.mkdir()
    with (
        patch.object(paths, "_get_untracked_dir", return_value=directory),
        patch.object(paths, "_get_hostname_suffix", return_value="-ownhost"),
    ):
        yield directory
    shutil.rmtree(root, ignore_errors=True)


def _refused_socket(path: Path) -> None:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    sock.close()


def _dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def _set_with_socket_at(untracked: Path, ident: str, socket_path: Path, *, named: bool) -> None:
    """A set whose only socket is ``socket_path``, reached through its discovery file."""
    (untracked / f"daemon-{ident}.pid").write_text(str(_dead_pid()))
    if named:
        (untracked / f"daemon-{ident}.socket-path").write_text(str(socket_path))


def test_a_refused_socket_outside_the_tree_keeps_the_set(untracked: Path) -> None:
    fallback = untracked.parent / "fallback-run"
    fallback.mkdir()
    _refused_socket(fallback / "d.sock")
    _set_with_socket_at(untracked, "peer", fallback / "d.sock", named=True)

    assert sweep_dead_runtime_sets(Path("/unused"), min_age_seconds=0.0) == []
    assert (untracked / "daemon-peer.pid").exists()
    assert peer_runtime_sets_not_proven_dead(Path("/unused"), min_age_seconds=0.0) == ["peer"]


def test_a_missing_socket_outside_the_tree_keeps_the_set(untracked: Path) -> None:
    _set_with_socket_at(untracked, "peer", untracked.parent / "gone.sock", named=True)

    assert sweep_dead_runtime_sets(Path("/unused"), min_age_seconds=0.0) == []


def test_a_refused_in_tree_socket_is_swept(untracked: Path) -> None:
    _refused_socket(untracked / "daemon-gone.sock")
    (untracked / "daemon-gone.pid").write_text(str(_dead_pid()))

    removed = sweep_dead_runtime_sets(Path("/unused"), min_age_seconds=0.0)

    assert sorted(removed) == [untracked / "daemon-gone.pid", untracked / "daemon-gone.sock"]
    assert peer_runtime_sets_not_proven_dead(Path("/unused"), min_age_seconds=0.0) == []


def test_own_set_is_not_a_peer(untracked: Path) -> None:
    _refused_socket(untracked / "daemon-ownhost.sock")

    assert peer_runtime_sets_not_proven_dead(Path("/unused"), min_age_seconds=0.0) == []


def test_no_untracked_dir_means_no_peers(tmp_path: Path) -> None:
    with patch.object(paths, "_get_untracked_dir", return_value=tmp_path / "missing"):
        assert peer_runtime_sets_not_proven_dead(Path("/unused")) == []
