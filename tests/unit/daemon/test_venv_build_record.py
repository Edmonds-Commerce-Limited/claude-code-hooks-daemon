"""Plan 00555 Task 2.7: Python-side holder and last-result records for venv builds.

The bash drivers write ``untracked/.venv-bootstrap.current`` (holder) and
``untracked/.venv-bootstrap.result`` (last result). The Python ``repair`` and
the start-time cleanup take the same lock, so they write the same files in the
same key=value format, and ``status`` reads the result back.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import _repair_venv_locked, cmd_status
from claude_code_hooks_daemon.daemon.venv_lock import (
    BuildResult,
    build_log_path,
    read_build_result,
    venv_lock,
    write_build_result,
)


def _kv(path: Path) -> dict[str, str]:
    return dict(line.partition("=")[::2] for line in path.read_text().splitlines())


class TestHolderRecord:
    def test_a_named_holder_is_recorded_while_the_lock_is_held(self, tmp_path: Path) -> None:
        log = tmp_path / "untracked" / ".venv-bootstrap-fp.log"
        with venv_lock(tmp_path, holder="repair", log=log):
            record = _kv(tmp_path / "untracked" / ".venv-bootstrap.current")
            assert record["holder"] == "repair"
            assert record["pid"] == str(os.getpid())
            assert record["log"] == str(log)
            assert record["started"].isdigit()

        assert not (tmp_path / "untracked" / ".venv-bootstrap.current").exists()

    def test_no_holder_means_no_record(self, tmp_path: Path) -> None:
        with venv_lock(tmp_path):
            assert not (tmp_path / "untracked" / ".venv-bootstrap.current").exists()

    def test_a_record_without_a_log_omits_the_key(self, tmp_path: Path) -> None:
        with venv_lock(tmp_path, holder="cleanup"):
            record = _kv(tmp_path / "untracked" / ".venv-bootstrap.current")
        assert "log" not in record

    def test_the_record_is_removed_when_the_body_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError):
            with venv_lock(tmp_path, holder="repair"):
                raise RuntimeError("boom")
        assert not (tmp_path / "untracked" / ".venv-bootstrap.current").exists()


class TestBuildResult:
    def test_write_then_read_round_trips(self, tmp_path: Path) -> None:
        (tmp_path / "untracked").mkdir()
        log = build_log_path(tmp_path, "fp1")
        write_build_result(tmp_path, "failed", 2, log)

        result = read_build_result(tmp_path)

        assert result is not None
        assert result == BuildResult(
            result="failed", finished_at=result.finished_at, exit=2, log=str(log)
        )
        assert result.finished_at.endswith("Z")
        assert _kv(tmp_path / "untracked" / ".venv-bootstrap.result")["result"] == "failed"

    def test_the_log_names_the_verdict(self, tmp_path: Path) -> None:
        (tmp_path / "untracked").mkdir()
        log = build_log_path(tmp_path, "fp1")
        write_build_result(tmp_path, "succeeded", 0, log)
        assert "succeeded" in log.read_text()

    def test_no_record_reads_as_none(self, tmp_path: Path) -> None:
        assert read_build_result(tmp_path) is None

    def test_a_record_the_bash_writer_made_is_read(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        (untracked / ".venv-bootstrap.result").write_text(
            "result=timed-out\nfinished_at=2026-10-31T01:02:03Z\nexit=143\nlog=/x/y.log\n"
        )
        assert read_build_result(tmp_path) == BuildResult(
            result="timed-out", finished_at="2026-10-31T01:02:03Z", exit=143, log="/x/y.log"
        )

    def test_a_malformed_record_is_an_error_not_a_guess(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        (untracked / ".venv-bootstrap.result").write_text("result=failed\n")
        with pytest.raises(ValueError, match="finished_at"):
            read_build_result(tmp_path)


class TestRepairRecordsItsResult:
    def _venv(self, daemon_dir: Path) -> Path:
        return daemon_dir / "untracked" / "venv-home_x_hooks-daemon-py311-abcd1234"

    def test_a_failed_sync_is_recorded_with_the_fingerprint_log(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path
        (daemon_dir / "untracked").mkdir()
        with patch("claude_code_hooks_daemon.daemon.cli.find_uv", return_value=None):
            rc = _repair_venv_locked(daemon_dir, self._venv(daemon_dir), {})

        assert rc == 1
        result = read_build_result(daemon_dir)
        assert result is not None
        assert result.result == "failed"
        assert result.log == str(build_log_path(daemon_dir, "home_x_hooks-daemon-py311-abcd1234"))
        assert Path(result.log).exists()

    def test_an_exception_is_recorded_then_propagates(self, tmp_path: Path) -> None:
        (tmp_path / "untracked").mkdir()
        with patch("claude_code_hooks_daemon.daemon.cli.find_uv", side_effect=OSError("disk")):
            with pytest.raises(OSError, match="disk"):
                _repair_venv_locked(tmp_path, self._venv(tmp_path), {})

        result = read_build_result(tmp_path)
        assert result is not None and result.result == "failed"


class TestStatusNamesTheLastBuild:
    @pytest.fixture(autouse=True)
    def no_git(self, monkeypatch: Any) -> None:
        ProjectContext._initialized = False
        monkeypatch.setattr(
            "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_repo_name",
            lambda project_root: "test-repo",
        )
        monkeypatch.setattr(
            "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_toplevel",
            lambda project_root: project_root,
        )

    def _status(self, tmp_path: Path, capsys: Any) -> str:
        untracked = tmp_path / ".claude" / "hooks-daemon" / "untracked"
        untracked.mkdir(parents=True, exist_ok=True)
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text("version: '1.0'\n")
        args = argparse.Namespace(project_root=tmp_path)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=untracked / "s.sock",
            ),
        ):
            assert cmd_status(args) == 1
        out: str = capsys.readouterr().out
        return out

    def test_not_running_names_the_log_and_last_result(self, tmp_path: Path, capsys: Any) -> None:
        untracked = tmp_path / ".claude" / "hooks-daemon" / "untracked"
        untracked.mkdir(parents=True)
        write_build_result(
            tmp_path / ".claude" / "hooks-daemon", "failed", 1, untracked / ".venv-bootstrap-a.log"
        )

        out = self._status(tmp_path, capsys)

        assert "Last venv build: failed" in out
        assert str(untracked / ".venv-bootstrap-a.log") in out

    def test_no_build_record_adds_nothing(self, tmp_path: Path, capsys: Any) -> None:
        assert "Last venv build" not in self._status(tmp_path, capsys)
