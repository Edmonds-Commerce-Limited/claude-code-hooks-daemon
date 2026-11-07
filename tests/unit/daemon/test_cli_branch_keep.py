"""`hooks-daemon branch-keep` (Plan 00571 Phase 3): arguments, output and exit codes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_branch_keep


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
    _git(tmp_path, "branch", "done")
    _git(tmp_path, "checkout", "-q", "-b", "open")
    (tmp_path / "g").write_text("g")
    _git(tmp_path, "add", "g")
    _git(tmp_path, "commit", "-q", "-m", "open work")
    _git(tmp_path, "checkout", "-q", "main")
    return tmp_path


def _run(project: Path, *argv: str) -> int:
    args = build_parser().parse_args(["--project-root", str(project), "branch-keep", *argv])
    args.project_root = project
    return cmd_branch_keep(args)


def test_keep_writes_note_and_reports_a_failed_push(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(project, "done", "--reason", "audit") == 0
    out = capsys.readouterr().out
    assert "Kept done" in out and "Retry: git push origin refs/notes/hooks-daemon/keep" in out
    tip = _git(project, "rev-parse", "done")
    assert "Kept-Reason: audit" in _git(
        project, "notes", "--ref=refs/notes/hooks-daemon/keep", "show", tip
    )


def test_missing_reason_exits_one(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(project, "done") == 1
    assert "reason" in capsys.readouterr().err


def test_unknown_branch_exits_one(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(project, "nope", "--reason", "x") == 1
    assert "no branch" in capsys.readouterr().err


def test_unmerged_branch_exits_one_and_points_at_park(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(project, "open", "--reason", "x") == 1
    assert "branch-park" in capsys.readouterr().err


def test_same_reason_exits_two(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(project, "done", "--reason", "w") == 0
    capsys.readouterr()
    assert _run(project, "done", "--reason", "w") == 2
    assert "new reason" in capsys.readouterr().err
