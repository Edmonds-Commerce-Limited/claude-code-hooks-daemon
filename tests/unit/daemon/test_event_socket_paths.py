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

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.daemon.paths import (
    _EVENT_SOCKET_FILENAME_BUDGET,
    _UNIX_SOCKET_PATH_LIMIT,
    event_socket_dir_is_fallback,
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

    def test_falls_back_instead_of_none_when_natural_path_exceeds_unix_socket_limit(self) -> None:
        # Plan 00290 F3 fix (canary run 2): a deeply nested project path
        # pushes the NATURAL events dir past the AF_UNIX length limit — the
        # standard client layout, where the bug left most events silently
        # unbound. Per-event sockets must now relocate to the short
        # fallback root (mirroring get_socket_path's own overflow fallback)
        # rather than being skipped entirely.
        deep_project_dir = Path("/" + ("a-fairly-long-directory-name/" * 20))
        path = get_event_socket_path(deep_project_dir, "pre-tool-use")
        self.assertIsNotNone(path)
        assert path is not None  # narrows for mypy
        self.assertLessEqual(len(str(path)), _UNIX_SOCKET_PATH_LIMIT)
        self.assertEqual(path.name, "pre-tool-use.sock")


class TestGetEventSocketPathInDir(unittest.TestCase):
    def test_applies_length_fallback(self) -> None:
        short_dir = Path("/tmp/events-x")
        self.assertEqual(get_event_socket_path_in_dir(short_dir, "stop"), short_dir / "stop.sock")

    def test_none_when_too_long(self) -> None:
        long_dir = Path("/tmp/" + ("x" * _UNIX_SOCKET_PATH_LIMIT))
        self.assertIsNone(get_event_socket_path_in_dir(long_dir, "stop"))


class TestEventSocketDirFallback(_EventSocketPathTestBase):
    """Plan 00290 F3 fix: mirrors TestSocketPathLengthFallback (test_paths.py)
    for the per-event socket directory.

    Uses a SYNTHETIC ``untracked_dir`` (not derived from
    ``get_socket_path(...).parent``) — a sufficiently deep project already
    pushes the LEGACY socket itself into ITS OWN overflow fallback (a short
    ``$XDG_RUNTIME_DIR``-rooted path), which would make ``.parent`` short
    again and defeat these tests. The events-dir fallback is exercised in
    isolation by constructing an ``untracked_dir`` long enough to overflow
    the (deeper) events path while staying agnostic of the legacy socket's
    own, unrelated fallback decision.
    """

    # events{suffix} for HOSTNAME=test-host is "events-test-host" (18 chars
    # incl. leading "/"). Budget math: fits iff
    # len(untracked_dir) + 18 + 30 <= 104, i.e. len(untracked_dir) <= 56.
    # 90 chars comfortably overflows; 20 chars comfortably fits.
    _DEEP_UNTRACKED_DIR = Path("/" + "a" * 90)
    _SHORT_UNTRACKED_DIR = Path("/" + "a" * 20)

    def test_short_untracked_dir_is_not_fallback(self) -> None:
        self.assertFalse(event_socket_dir_is_fallback(self._SHORT_UNTRACKED_DIR))

    def test_deep_untracked_dir_uses_fallback(self) -> None:
        self.assertTrue(event_socket_dir_is_fallback(self._DEEP_UNTRACKED_DIR))

    def test_deep_path_over_limit_uses_xdg_runtime_dir(self) -> None:
        with tempfile.TemporaryDirectory() as xdg_dir:
            with patch.dict("os.environ", {"XDG_RUNTIME_DIR": xdg_dir}):
                events_dir = get_event_socket_dir_from_untracked(self._DEEP_UNTRACKED_DIR)
        self.assertTrue(str(events_dir).startswith(xdg_dir))
        self.assertIn("-events", events_dir.name)

    def test_deep_path_over_limit_uses_tmp_when_no_xdg_or_run_user(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("XDG_RUNTIME_DIR", None)
            with patch.object(Path, "is_dir", return_value=False):
                events_dir = get_event_socket_dir_from_untracked(self._DEEP_UNTRACKED_DIR)
        self.assertTrue(str(events_dir).startswith("/tmp/"))  # nosec B108
        self.assertIn("-events", events_dir.name)

    def test_fallback_dir_is_deterministic_for_same_untracked_dir(self) -> None:
        first = get_event_socket_dir_from_untracked(self._DEEP_UNTRACKED_DIR)
        second = get_event_socket_dir_from_untracked(self._DEEP_UNTRACKED_DIR)
        self.assertEqual(first, second)

    def test_fallback_dir_differs_across_distinct_projects(self) -> None:
        dir_a = Path("/" + "a" * 90)
        dir_b = Path("/" + "b" * 90)
        events_a = get_event_socket_dir_from_untracked(dir_a)
        events_b = get_event_socket_dir_from_untracked(dir_b)
        self.assertNotEqual(events_a, events_b)


class TestAllWiredEventsBindAtRealisticClientDepth(_EventSocketPathTestBase):
    """Plan 00290 F3 fix: every wired event must resolve to a bindable
    (non-None) socket path at a REALISTIC standard client checkout depth —
    the exact shape the canary found only 7/31 bound at."""

    def test_every_wired_event_resolves_under_realistic_client_depth(self) -> None:
        from claude_code_hooks_daemon.constants.events import wired_event_metas

        # `<some-org>/<some-deeply-nested-monorepo>/services/billing-api/.claude/hooks-daemon/untracked`
        realistic_client_project = Path(
            "/home/runner/work/some-org/some-deeply-nested-monorepo-checkout/"
            "services/billing-api"
        )
        events_dir = get_event_socket_dir(realistic_client_project)
        for meta in wired_event_metas():
            path = get_event_socket_path_in_dir(events_dir, meta.bash_key)
            self.assertIsNotNone(
                path, f"{meta.bash_key}: socket path unexpectedly exceeds the AF_UNIX limit"
            )
            assert path is not None  # narrows for mypy
            self.assertLessEqual(len(str(path)), _UNIX_SOCKET_PATH_LIMIT)


def test_event_socket_filename_budget_covers_every_wired_event() -> None:
    """The hardcoded worst-case budget (kept literal so paths.py stays
    stdlib-only importable — see its docstring) must stay >= the real
    worst case declared in constants/events.py."""
    from claude_code_hooks_daemon.constants.events import wired_event_metas

    worst_case = max(len(meta.bash_key) + len(".sock") for meta in wired_event_metas())
    assert worst_case <= _EVENT_SOCKET_FILENAME_BUDGET


if __name__ == "__main__":
    unittest.main()
