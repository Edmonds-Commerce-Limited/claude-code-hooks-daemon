"""The paths a test's own daemon uses are its alone."""

from __future__ import annotations

from pathlib import Path

from tests.isolated_daemon import isolated_daemon_paths

#: The kernel's limit on an AF_UNIX socket path, with its terminating NUL.
_SUN_PATH_BYTES = 108


def test_two_sessions_running_the_same_test_get_different_paths() -> None:
    """Each pytest session numbers its base directory, and the test's own
    directory under it has the same name in every session."""
    first = isolated_daemon_paths(Path("/tmp/pytest-of-root/pytest-7/test_x0"), "daemon")
    second = isolated_daemon_paths(Path("/tmp/pytest-of-root/pytest-8/test_x0"), "daemon")
    assert set(first).isdisjoint(second)


def test_the_same_directory_gets_the_same_paths() -> None:
    tmp_path = Path("/tmp/pytest-of-root/pytest-7/test_x0")
    assert isolated_daemon_paths(tmp_path, "daemon") == isolated_daemon_paths(tmp_path, "daemon")


def test_the_socket_path_fits_however_deep_the_test_directory() -> None:
    deep = Path("/tmp", *(["a-very-long-directory-name"] * 20), "test_x0")
    socket = isolated_daemon_paths(deep, "missing-plugin").socket
    assert len(str(socket).encode()) < _SUN_PATH_BYTES
    assert socket.parent == Path("/tmp")
