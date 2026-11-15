"""``delete-branch --remote-only``: the leased agent route to a proven remote delete."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.support.git_fixtures import git_setup_timeout, run_git

from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_delete_branch

_EXIT_REFUSED = 1
_EXIT_USAGE = 2


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """`dup` is unmerged but its file is on main; `novel` holds a file found nowhere else."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    run_git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    run_git(tmp_path, "init", "--initial-branch=main", str(work))
    (work / ".claude" / "hooks-daemon").mkdir(parents=True)
    run_git(work, "config", "user.email", "t@example.invalid")
    run_git(work, "config", "user.name", "Tester")
    run_git(work, "config", "commit.gpgsign", "false")
    run_git(work, "remote", "add", "origin", str(origin))
    run_git(work, "commit", "--allow-empty", "-m", "base")
    run_git(work, "push", "-u", "origin", "main")
    run_git(work, "remote", "set-head", "origin", "main")
    for name in ("dup", "novel"):
        run_git(work, "checkout", "-q", "-b", name, "main")
        (work / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
        run_git(work, "add", f"{name}.txt")
        run_git(work, "commit", "-m", name)
        run_git(work, "push", "-u", "origin", name)
        run_git(work, "checkout", "-q", "main")
    (work / "dup.txt").write_text("dup\n", encoding="utf-8")
    run_git(work, "add", "dup.txt")
    run_git(work, "commit", "-m", "same file, independent commit")
    run_git(work, "push", "origin", "main")
    run_git(work, "fetch", "origin")
    return work


def _heads(work: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(work), "ls-remote", "--heads", "origin"],
        check=True,
        capture_output=True,
        text=True,
        timeout=git_setup_timeout(),
    ).stdout


def _args(repo: Path, branches: list[str], **overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "project_root": repo,
        "branches": branches,
        "protected_ref": None,
        "dry_run": False,
        "format": "text",
        "remote_only": True,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_the_flag_is_parsed() -> None:
    args = build_parser().parse_args(["delete-branch", "--remote-only", "dup"])
    assert args.remote_only is True


def test_a_proven_branch_is_deleted_and_its_restore_line_printed(
    clone: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cmd_delete_branch(_args(clone, ["dup"])) == 0
    out = capsys.readouterr().out
    assert "Deleted remote branch(es): origin/dup" in out
    assert ":refs/heads/dup" in out
    assert "refs/heads/dup" not in _heads(clone)


def test_an_unproven_branch_is_refused_with_exit_one(
    clone: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cmd_delete_branch(_args(clone, ["novel"])) == _EXIT_REFUSED
    captured = capsys.readouterr()
    assert "novel.txt" in captured.out + captured.err
    assert "refs/heads/novel" in _heads(clone)


@pytest.mark.parametrize("override", [{"protected_ref": "main"}, {"dry_run": True}])
def test_options_that_have_no_meaning_here_are_a_usage_error(
    clone: Path, override: dict[str, Any]
) -> None:
    assert cmd_delete_branch(_args(clone, ["dup"], **override)) == _EXIT_USAGE
    assert "refs/heads/dup" in _heads(clone)
