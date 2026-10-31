"""Plan 00555 Task 2.5 (b): the daemon writes the protected-path globs to a snapshot
that init.sh reads while the daemon is down."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

SNAPSHOT_NAME = ".protected-paths.snapshot"


@pytest.fixture
def untracked(tmp_path: Path) -> Iterator[Path]:
    target = tmp_path / "untracked"
    target.mkdir()
    with patch.object(ProjectContext, "daemon_untracked_dir", return_value=target):
        yield target


class TestDaemonStartWritesTheSnapshot:
    def test_a_failed_write_is_logged_and_start_continues(self) -> None:
        from claude_code_hooks_daemon.daemon.server import HooksDaemon

        with patch.object(sfm, "write_protected_paths_snapshot", side_effect=OSError("ro")):
            HooksDaemon._write_protected_paths_snapshot_best_effort()

    def test_a_good_write_is_requested_once(self) -> None:
        from claude_code_hooks_daemon.daemon.server import HooksDaemon

        with patch.object(sfm, "write_protected_paths_snapshot") as write:
            HooksDaemon._write_protected_paths_snapshot_best_effort()
        write.assert_called_once_with()


class TestWriteProtectedPathsSnapshot:
    def test_writes_one_glob_per_line(self, untracked: Path) -> None:
        patterns = ("*.alpha*", "beta_*")
        with patch.object(sfm, "resolve_configured_patterns", return_value=patterns):
            written = sfm.write_protected_paths_snapshot()
        assert written == untracked / SNAPSHOT_NAME
        assert written.read_text() == "*.alpha*\nbeta_*\n"

    def test_replaces_an_existing_snapshot_and_leaves_no_temp_file(self, untracked: Path) -> None:
        (untracked / SNAPSHOT_NAME).write_text("stale\n")
        with patch.object(sfm, "resolve_configured_patterns", return_value=("x*",)):
            sfm.write_protected_paths_snapshot()
        assert (untracked / SNAPSHOT_NAME).read_text() == "x*\n"
        assert [p.name for p in untracked.iterdir()] == [SNAPSHOT_NAME]

    def test_an_unwritable_directory_raises_oserror(self, tmp_path: Path) -> None:
        missing = tmp_path / "no" / "such"
        with (
            patch.object(ProjectContext, "daemon_untracked_dir", return_value=missing),
            patch.object(sfm, "resolve_configured_patterns", return_value=("x*",)),
            pytest.raises(OSError),
        ):
            sfm.write_protected_paths_snapshot()
