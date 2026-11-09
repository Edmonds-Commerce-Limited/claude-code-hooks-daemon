"""`hooks-daemon branch-park` (Plan 00558 Task 4.3): the verb's arguments, output and exit codes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_branch_park


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "hooks-daemon").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "remote", "add", "origin", str(tmp_path / "none.git"))
    (tmp_path / "f").write_text("f")
    _git(tmp_path, "add", "f")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "branch", "work")
    return tmp_path


def _run(project: Path, *argv: str) -> int:
    args = build_parser().parse_args(["--project-root", str(project), "branch-park", *argv])
    args.project_root = project
    return cmd_branch_park(args)


def test_park_reports_a_failed_push_with_retry(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(project, "work", "--reason", "waiting") == 0
    out = capsys.readouterr().out
    assert "Parked work" in out and "Retry: git push origin work" in out
    assert "Parked-Reason: waiting" in _git(project, "log", "-1", "--format=%B", "work")


def test_clear_with_reason_is_a_usage_error(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(project, "work", "--clear", "--reason", "x") == 2
    assert "--clear takes no --reason" in capsys.readouterr().err


def test_missing_reason_exits_one(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(project, "work") == 1
    assert "reason" in capsys.readouterr().err


def test_a_same_reason_repark_exits_two(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(project, "work", "--reason", "w") == 0
    capsys.readouterr()
    assert _run(project, "work", "--reason", "w") == 2
    assert "new reason" in capsys.readouterr().err


def test_clear_unparks(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(project, "work", "--reason", "w") == 0
    assert _run(project, "work", "--clear") == 0
    assert "Unparked:" in _git(project, "log", "-1", "--format=%B", "work")
    assert "Unparked work" in capsys.readouterr().out
