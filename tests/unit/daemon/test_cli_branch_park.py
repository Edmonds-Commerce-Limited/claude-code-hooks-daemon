"""`hooks-daemon branch-park` (Plan 00558 Task 4.3): the verb's arguments, output and exit codes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from tests.support.git_fixtures import git_setup_timeout

from claude_code_hooks_daemon.core.branch_park import EXIT_PARKED_NOT_PUSHED
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
    bare = tmp_path / "none.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], check=True, timeout=git_setup_timeout()
    )
    _git(tmp_path, "remote", "add", "origin", str(bare))
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
    _git(project, "remote", "set-url", "origin", str(project / "missing.git"))
    assert _run(project, "work", "--reason", "waiting") == EXIT_PARKED_NOT_PUSHED
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


def test_a_refused_push_exits_distinctly_and_names_git_reason_and_retry(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = project / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho 'gate: full-QA verdict required' >&2\nexit 1\n")
    hook.chmod(0o755)
    assert _run(project, "work", "--reason", "waiting") == EXIT_PARKED_NOT_PUSHED
    out = capsys.readouterr().out
    assert "parked locally, not pushed" in out
    assert "gate: full-QA verdict required" in out
    assert "git push origin work" in out
    assert _git(project, "config", "branch.work.hooksDaemonParkedReason") == "waiting"


def test_clear_says_the_park_record_is_cleared(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(project, "work", "--reason", "waiting")
    capsys.readouterr()
    assert _run(project, "work", "--clear") == 0
    assert "Park record cleared: work (waiting)" in capsys.readouterr().out


def test_no_commit_records_the_park_and_pushes_nothing(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tip = _git(project, "rev-parse", "work")
    assert _run(project, "work", "--reason", "waiting", "--no-commit") == 0
    out = capsys.readouterr().out
    assert "this clone only" in out and "invisible to other checkouts" in out
    assert _git(project, "rev-parse", "work") == tip
    assert _git(project, "config", "--get", "branch.work.hooksDaemonParkedReason") == "waiting"
    assert _git(project, "ls-remote", "--heads", "origin", "work") == ""


def test_no_push_commits_but_does_not_push(project: Path) -> None:
    assert _run(project, "work", "--reason", "waiting", "--no-push") == 0
    assert "Parked-Reason: waiting" in _git(project, "log", "-1", "--format=%B", "work")
    assert _git(project, "ls-remote", "--heads", "origin", "work") == ""


def test_config_key_sets_the_default_and_a_flag_overrides_it(project: Path) -> None:
    (project / ".claude" / "hooks-daemon.yaml").write_text(
        "version: '2.0'\nbranches:\n  park:\n    commit: false\n", encoding="utf-8"
    )
    tip = _git(project, "rev-parse", "work")
    assert _run(project, "work", "--reason", "waiting") == 0
    assert _git(project, "rev-parse", "work") == tip
    assert _run(project, "work", "--reason", "now committed", "--commit", "--no-push") == 0
    assert _git(project, "rev-parse", "work") != tip
