"""Plan 00291 Task 3.3 — ``status`` names a branch install every time it runs.

A guarded branch install must be visible from the one command every operator
runs. A release install prints nothing extra, so existing byte-for-byte
expectations of ``status`` output still hold.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import cmd_status
from claude_code_hooks_daemon.install.install_stamp import InstallStamp

_BRANCH_STAMP = InstallStamp(
    raw="v3.63.0+main.8d011476", version="3.63.0", ref="main", sha="8d011476"
)
_RELEASE_STAMP = InstallStamp(raw="v3.63.0", version="3.63.0", ref=None, sha=None)


@pytest.fixture(autouse=True)
def mock_git_checks(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_repo_name",
        lambda project_root: "test-repo",
    )
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_toplevel",
        lambda project_root: project_root,
    )


@pytest.fixture(autouse=True)
def reset_project_context() -> None:
    ProjectContext._initialized = False


def _make_project(tmp_path: Path) -> Path:
    claude_dir = tmp_path / ".claude"
    untracked_dir = claude_dir / "hooks-daemon" / "untracked" / "venv"
    untracked_dir.mkdir(parents=True)
    socket_path = untracked_dir / "socket"
    socket_path.touch()
    (claude_dir / "hooks-daemon.yaml").write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")
    return socket_path


def _status_output(
    tmp_path: Path, stamp: InstallStamp | None, *, running: bool, capsys: Any
) -> tuple[int, str]:
    socket_path = _make_project(tmp_path)
    args = argparse.Namespace(project_root=tmp_path)
    with (
        patch(
            "claude_code_hooks_daemon.daemon.cli.read_pid_file",
            return_value=12345 if running else None,
        ),
        patch("claude_code_hooks_daemon.daemon.cli.get_socket_path", return_value=socket_path),
        patch("claude_code_hooks_daemon.daemon.cli.read_install_stamp", return_value=stamp),
    ):
        rc = cmd_status(args)
    return rc, capsys.readouterr().out


class TestStatusNamesABranchInstall:
    def test_running_branch_install_prints_the_stamp_and_the_way_out(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc, out = _status_output(tmp_path, _BRANCH_STAMP, running=True, capsys=capsys)
        assert rc == 0
        assert "Daemon: RUNNING" in out
        assert "Install: NON-RELEASE v3.63.0+main.8d011476" in out
        assert "tracking 'main'" in out
        assert "release tag" in out

    def test_stopped_branch_install_still_prints_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc, out = _status_output(tmp_path, _BRANCH_STAMP, running=False, capsys=capsys)
        assert rc == 1
        assert "Daemon: NOT RUNNING" in out
        assert "Install: NON-RELEASE v3.63.0+main.8d011476" in out

    def test_release_install_prints_no_install_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _, out = _status_output(tmp_path, _RELEASE_STAMP, running=True, capsys=capsys)
        assert "Install:" not in out
        assert "NON-RELEASE" not in out

    def test_unstamped_install_prints_no_install_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _, out = _status_output(tmp_path, None, running=True, capsys=capsys)
        assert "Install:" not in out
