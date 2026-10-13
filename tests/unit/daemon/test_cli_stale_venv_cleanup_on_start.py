"""Plan 00517 Task 4.1: daemon start (so restart and provision) removes proven-stale venvs.

Only a venv the one staleness rule proves stale is removed; an UNPROVEN venv,
the live venv and a venv a process uses are left, and a failure in the cleanup
never stops the start.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.paths import project_path_slug
from claude_code_hooks_daemon.daemon.venv_lock import VenvLockTimeout

STALE_HASH = "sha256:" + "0" * 64
_RESOLVER = "claude_code_hooks_daemon.daemon.paths.resolve_existing_venv_python"


def _venv(path: Path, lock_hash: str | None = None) -> Path:
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").symlink_to(Path(sys.executable).resolve())
    if lock_hash is not None:
        (path / ".daemon-metadata.json").write_text(
            json.dumps({"python_path": str(path / "bin" / "python"), "lock_hash": lock_hash})
        )
    return path


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "untracked").mkdir()
    with patch(_RESOLVER, return_value=tmp_path / "no-venv" / "bin" / "python"):
        yield tmp_path


def _name(project: Path, tail: str) -> str:
    return f"venv-{project_path_slug(project)}-{tail}"


class TestCleanupProvenStaleVenvs:
    def test_removes_a_proven_stale_venv_and_returns_its_path(self, project: Path) -> None:
        stale = _venv(project / "untracked" / _name(project, "py310-aaaaaaaa"), STALE_HASH)

        removed = cli._cleanup_proven_stale_venvs(project)

        assert removed == [stale]
        assert not stale.exists()

    def test_leaves_unproven_and_other_view_venvs(self, project: Path) -> None:
        no_metadata = _venv(project / "untracked" / _name(project, "py310-aaaaaaaa"))
        other_view = _venv(project / "untracked" / "venv-elsewhere-py310-bbbbbbbb", STALE_HASH)

        assert cli._cleanup_proven_stale_venvs(project) == []

        assert no_metadata.exists()
        assert other_view.exists()

    def test_leaves_the_live_venv(self, project: Path) -> None:
        live = _venv(project / "untracked" / _name(project, "py310-aaaaaaaa"), STALE_HASH)

        with patch(_RESOLVER, return_value=live / "bin" / "python"):
            assert cli._cleanup_proven_stale_venvs(project) == []

        assert live.exists()

    def test_leaves_a_stale_venv_a_process_is_using(self, project: Path) -> None:
        stale = _venv(project / "untracked" / _name(project, "py310-aaaaaaaa"), STALE_HASH)
        child = subprocess.Popen(
            [str(stale / "bin" / "python"), "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            removed = cli._cleanup_proven_stale_venvs(project)
        finally:
            child.terminate()
            child.wait(timeout=Timeout.DAEMON_SHUTDOWN)

        assert removed == []
        assert stale.exists()

    def test_takes_no_lock_when_nothing_is_stale(self, project: Path) -> None:
        _venv(project / "untracked" / _name(project, "py310-aaaaaaaa"))

        with patch(f"{cli.__name__}.venv_lock") as lock:
            assert cli._cleanup_proven_stale_venvs(project) == []

        lock.assert_not_called()

    def test_removes_under_the_venv_build_lock(self, project: Path) -> None:
        _venv(project / "untracked" / _name(project, "py310-aaaaaaaa"), STALE_HASH)

        with patch(f"{cli.__name__}.venv_lock") as lock:
            cli._cleanup_proven_stale_venvs(project)

        lock.assert_called_once()
        lock.return_value.__enter__.assert_called_once()


class TestReapRunsTheCleanupFailOpen:
    """``_reap_stale_runtime_files`` runs on every start, restart and provision."""

    def _reap(self, project: Path) -> None:
        with (
            patch(f"{cli.__name__}.cleanup_stale_daemon_files", return_value=0),
            patch(f"{cli.__name__}.cleanup_stale_session_dirs", return_value=0),
            patch(f"{cli.__name__}.write_cleanup_status"),
        ):
            cli._reap_stale_runtime_files(project, Config())

    def test_start_removes_and_announces_a_proven_stale_venv(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        stale = _venv(project / "untracked" / _name(project, "py310-aaaaaaaa"), STALE_HASH)

        self._reap(project)

        assert not stale.exists()
        assert f"Removed stale venv: {stale}" in capsys.readouterr().out

    def test_start_never_removes_an_unproven_venv(self, project: Path) -> None:
        orphan = _venv(project / "untracked" / _name(project, "py310-aaaaaaaa"))

        self._reap(project)

        assert orphan.exists()

    @pytest.mark.parametrize(
        "error", [OSError("disk gone"), VenvLockTimeout("held"), ValueError("bad backend")]
    )
    def test_a_cleanup_error_never_stops_the_start(
        self, project: Path, error: Exception, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch(f"{cli.__name__}._cleanup_proven_stale_venvs", MagicMock(side_effect=error)):
            self._reap(project)  # must not raise

        assert "Removed stale venv" not in capsys.readouterr().out

    def test_an_unexpected_cleanup_error_never_stops_the_start(self, project: Path) -> None:
        with patch(
            f"{cli.__name__}._cleanup_proven_stale_venvs", MagicMock(side_effect=RuntimeError("x"))
        ):
            self._reap(project)  # must not raise


class TestReapSweepsDeadRuntimeSets:
    """Task 4.3: the same start-time hook sweeps other hosts' dead runtime sets, fail-open."""

    def _reap(self, project: Path) -> None:
        with (
            patch(f"{cli.__name__}.cleanup_stale_daemon_files", return_value=0),
            patch(f"{cli.__name__}.cleanup_stale_session_dirs", return_value=0),
            patch(f"{cli.__name__}.write_cleanup_status"),
        ):
            cli._reap_stale_runtime_files(project, Config())

    def test_start_announces_what_the_sweep_removed(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        removed = [project / "untracked" / "daemon-gone.pid", project / "untracked" / "events-gone"]

        with patch(f"{cli.__name__}.sweep_dead_runtime_sets", return_value=removed) as sweep:
            self._reap(project)

        sweep.assert_called_once_with(project)
        assert "Removed 2 file(s) of dead per-host runtime sets" in capsys.readouterr().out

    def test_start_is_silent_when_nothing_was_swept(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch(f"{cli.__name__}.sweep_dead_runtime_sets", return_value=[]):
            self._reap(project)

        assert "dead per-host" not in capsys.readouterr().out

    def test_a_sweep_error_never_stops_the_start_or_the_venv_cleanup(self, project: Path) -> None:
        stale = _venv(project / "untracked" / _name(project, "py310-aaaaaaaa"), STALE_HASH)

        with patch(
            f"{cli.__name__}.sweep_dead_runtime_sets", MagicMock(side_effect=RuntimeError("x"))
        ):
            self._reap(project)  # must not raise

        assert not stale.exists()
