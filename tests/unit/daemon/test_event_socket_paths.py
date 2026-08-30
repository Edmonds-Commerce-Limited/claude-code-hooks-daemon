"""Tests for per-event Unix socket path helpers (Plan 00290, Task 2.1).

See ``CLAUDE/Plan/00290-rust-socket-relay-forwarder/DESIGN-socket-relay.md``
§1.1 for the naming contract: ``{untracked}/events{suffix}/{event-file-name}.sock``,
a sibling of the legacy ``{untracked}/daemon{suffix}.sock``.

Mirrors ``tests/daemon/test_paths.py``'s convention: a short, non-existent
fake project path (not ``tmp_path``, whose long pytest-generated prefix would
itself trip the AF_UNIX length fallback and confuse the assertions below),
with ``Path.mkdir`` mocked so path generation never touches the real
filesystem.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.daemon.paths import (
    _UNIX_SOCKET_PATH_LIMIT,
    get_event_socket_dir,
    get_event_socket_dir_from_untracked,
    get_event_socket_path,
    get_event_socket_path_in_dir,
    get_socket_path,
)


class _EventSocketPathTestBase(unittest.TestCase):
    """Mocks ``Path.mkdir`` and pins ``$HOSTNAME`` for deterministic suffixes."""

    def setUp(self) -> None:
        self.mkdir_patcher = patch.object(Path, "mkdir")
        self.mkdir_patcher.start()
        self.env_patcher = patch.dict("os.environ", {"HOSTNAME": "test-host"})
        self.env_patcher.start()

    def tearDown(self) -> None:
        self.mkdir_patcher.stop()
        self.env_patcher.stop()


class TestGetEventSocketDir(_EventSocketPathTestBase):
    def test_is_sibling_of_legacy_socket(self) -> None:
        project_dir = Path("/home/dev/my-project")
        legacy_socket = get_socket_path(project_dir)
        events_dir = get_event_socket_dir(project_dir)
        self.assertEqual(events_dir.parent, legacy_socket.parent)

    def test_directory_name_carries_hostname_suffix(self) -> None:
        events_dir = get_event_socket_dir(Path("/home/dev/my-project"))
        self.assertEqual(events_dir.name, "events-test-host")

    def test_from_untracked_matches_project_dir_variant(self) -> None:
        project_dir = Path("/home/dev/my-project")
        untracked_dir = get_socket_path(project_dir).parent
        self.assertEqual(
            get_event_socket_dir_from_untracked(untracked_dir),
            get_event_socket_dir(project_dir),
        )


class TestGetEventSocketPath(_EventSocketPathTestBase):
    def test_naming_matches_forwarder_filename(self) -> None:
        project_dir = Path("/home/dev/my-project")
        path = get_event_socket_path(project_dir, "pre-tool-use")
        self.assertIsNotNone(path)
        assert path is not None  # narrows for mypy
        self.assertEqual(path.name, "pre-tool-use.sock")
        self.assertEqual(path.parent, get_event_socket_dir(project_dir))

    def test_distinct_events_get_distinct_sockets(self) -> None:
        project_dir = Path("/home/dev/my-project")
        pre = get_event_socket_path(project_dir, "pre-tool-use")
        post = get_event_socket_path(project_dir, "post-tool-use")
        self.assertNotEqual(pre, post)

    def test_returns_none_when_path_exceeds_unix_socket_limit(self) -> None:
        # A deeply nested project path pushes the computed socket path past
        # the AF_UNIX length limit — per §1.1, per-event listeners are
        # skipped entirely (None) rather than relocated to a fallback dir.
        deep_project_dir = Path("/" + ("a-fairly-long-directory-name/" * 20))
        path = get_event_socket_path(deep_project_dir, "pre-tool-use")
        self.assertIsNone(path)


class TestGetEventSocketPathInDir(unittest.TestCase):
    def test_applies_length_fallback(self) -> None:
        short_dir = Path("/tmp/events-x")
        self.assertEqual(get_event_socket_path_in_dir(short_dir, "stop"), short_dir / "stop.sock")

    def test_none_when_too_long(self) -> None:
        long_dir = Path("/tmp/" + ("x" * _UNIX_SOCKET_PATH_LIMIT))
        self.assertIsNone(get_event_socket_path_in_dir(long_dir, "stop"))


if __name__ == "__main__":
    unittest.main()
