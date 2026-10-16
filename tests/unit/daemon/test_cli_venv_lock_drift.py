"""Plan 00474 N469: ``restart`` and ``status`` say when the venv is not built for the source.

After a dependency change, ``restart`` starts the daemon from the venv it was
already running from, because nothing on that path builds one. The daemon it
forks runs from this CLI's own interpreter, so the CLI judges ``sys.prefix``
and names ``repair``, the command that builds the venv for the current source.
Silent when the venv matches, so existing output is unchanged.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import cmd_restart, cmd_status

_DRIFT = "claude_code_hooks_daemon.daemon.cli.venv_lock_drift"


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


@pytest.fixture
def root(tmp_path: Path) -> Path:
    claude_dir = tmp_path / ".claude"
    (claude_dir / "hooks-daemon" / "untracked").mkdir(parents=True)
    (claude_dir / "hooks-daemon.yaml").write_text("version: '1.0'\n")
    return tmp_path


def _restart(root: Path, drift: str | None) -> tuple[int, Any]:
    args = argparse.Namespace(project_root=root)
    with (
        patch("claude_code_hooks_daemon.daemon.cli.cmd_stop", return_value=0),
        patch("claude_code_hooks_daemon.daemon.cli.cmd_start", return_value=0),
        patch("claude_code_hooks_daemon.daemon.cli._get_current_mode", return_value=None),
        patch("time.sleep"),
        patch(_DRIFT, return_value=drift) as mock_drift,
    ):
        rc = cmd_restart(args)
    return rc, mock_drift


class TestRestartNamesVenvDrift:
    def test_restart_warns_and_names_repair_when_the_venv_is_stale(
        self, root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc, mock_drift = _restart(root, "REASON-X")

        assert rc == 0, "a stale venv is reported, never a failed restart"
        err = capsys.readouterr().err
        assert "NOT BUILT FOR THIS SOURCE" in err
        assert "REASON-X" in err
        assert "hooks-daemon repair" in err
        daemon_dir, venv_dir = mock_drift.call_args.args
        assert daemon_dir == root / ".claude" / "hooks-daemon"
        assert venv_dir == Path(sys.prefix)

    def test_restart_is_silent_when_the_venv_matches(
        self, root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc, _mock_drift = _restart(root, None)

        assert rc == 0
        assert "NOT BUILT FOR THIS SOURCE" not in capsys.readouterr().err


class TestStatusNamesVenvDrift:
    def _status(self, root: Path, drift: str | None) -> int:
        socket_path = root / ".claude" / "hooks-daemon" / "untracked" / "socket"
        pid_path = root / ".claude" / "hooks-daemon" / "untracked" / "pid"
        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli._resolve_effective_daemon",
                return_value=(socket_path, pid_path, None),
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch(_DRIFT, return_value=drift),
        ):
            return cmd_status(argparse.Namespace(project_root=root))

    def test_status_warns_when_the_venv_is_stale(
        self, root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._status(root, "REASON-Y")

        err = capsys.readouterr().err
        assert "NOT BUILT FOR THIS SOURCE" in err
        assert "REASON-Y" in err

    def test_status_is_silent_when_the_venv_matches(
        self, root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._status(root, None)

        assert "NOT BUILT FOR THIS SOURCE" not in capsys.readouterr().err
