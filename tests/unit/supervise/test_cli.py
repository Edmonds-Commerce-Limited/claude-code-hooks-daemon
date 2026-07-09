"""Tests for claude_code_hooks_daemon.supervise.cli.main."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.supervise.cli import _resolve_decision_log, main


@pytest.fixture(autouse=True)
def _real_stdin_with_fileno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give `sys.stdin` a real fileno() for the duration of each test.

    Pytest's captured stdin has no `fileno()`, but `supervise()` needs a real
    fd to select() on. A /dev/null file object supplies one without requiring
    a real controlling terminal.
    """
    devnull = Path(os.devnull).open(encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", devnull)
    yield
    devnull.close()


class TestMainUsage:
    """Argument parsing and usage errors."""

    def test_no_child_argv_returns_usage_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["--"])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "usage" in captured.err.lower()

    def test_missing_separator_returns_usage_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main([])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "usage" in captured.err.lower()


class TestMainExecution:
    """Full execution through main(), including exit-code propagation."""

    def test_runs_child_and_propagates_exit_code(
        self, tmp_path: Path, capfd: pytest.CaptureFixture[str]
    ) -> None:
        log_path = tmp_path / "decision.log"

        exit_code = main(
            ["--log", str(log_path), "--", "bash", "-lc", "printf 'MAIN_OUT\\n'; exit 7"]
        )

        assert exit_code == 7
        assert "MAIN_OUT" in capfd.readouterr().out
        assert log_path.exists()

    def test_arm_flag_is_accepted_but_still_transparent(self, tmp_path: Path) -> None:
        """v0: --arm is a documented no-op; behaviour is identical to dry-run."""
        log_path = tmp_path / "decision.log"

        exit_code = main(["--arm", "--log", str(log_path), "--", "bash", "-lc", "exit 0"])

        assert exit_code == 0


class TestResolveDecisionLogDefaultPath:
    """`_resolve_decision_log(None)` derives its path from ProjectContext."""

    def test_initializes_project_context_when_not_already(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        monkeypatch.setattr(Path, "cwd", classmethod(lambda _cls: project_root))

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=str(project_root).encode() + b"\n"),
                MagicMock(returncode=0, stdout=b"git@github.com:user/test-repo.git\n"),
                MagicMock(returncode=0, stdout=str(project_root).encode() + b"\n"),
            ]
            log = _resolve_decision_log(None)

        assert log.path == ProjectContext.daemon_untracked_dir() / "supervise" / "decision.log"

    def test_reuses_already_initialized_project_context(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True)
        config_path = claude_dir / "hooks-daemon.yaml"
        config_path.write_text("version: 1.0\n")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=str(project_root).encode() + b"\n"),
                MagicMock(returncode=0, stdout=b"git@github.com:user/test-repo.git\n"),
                MagicMock(returncode=0, stdout=str(project_root).encode() + b"\n"),
            ]
            ProjectContext.initialize(config_path)

        log = _resolve_decision_log(None)

        assert log.path == ProjectContext.daemon_untracked_dir() / "supervise" / "decision.log"
