"""`worktree-reap` keeps a worktree whose removal would lose ignored content.

Plan 00627 Task 6.2, Unit 1. The reap predicate reads `git status --porcelain`,
which does not list ignored files, and `reap_worktree` runs a plain `git
worktree remove`, which deletes them. So a worktree holding an ignored scratch
note passed the predicate and lost the note. These tests use a real repository
and a real linked worktree, because the defect lives in what git does.
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import branch_cleanup
from claude_code_hooks_daemon.daemon.cli import cmd_worktree_reap
from claude_code_hooks_daemon.utils.git_repo import run_git

pytestmark = pytest.mark.usefixtures("default_branch_is_main")

_NAME = "agent-scratch-1"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test Author")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test Author")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """``main`` and a linked ``agent-*`` worktree level with it, ``untracked/`` ignored."""
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    (path / ".gitignore").write_text("untracked/\n.claude/worktrees/\n", encoding="utf-8")
    _git(path, "add", ".gitignore")
    _git(path, "commit", "-m", "Initial commit")
    _git(path, "worktree", "add", "-b", _NAME, str(path / ".claude" / "worktrees" / _NAME))
    return path


def _worktree(repo: Path) -> Path:
    return repo / ".claude" / "worktrees" / _NAME


def _reap(repo: Path, *, reap: bool) -> int:
    args = argparse.Namespace(
        project_root=str(repo), base_branch="main", reap=reap, only=None, reap_branches=False
    )
    return cmd_worktree_reap(args, age_fn=lambda _p: 999_999.0, process_cwds_fn=lambda: {})


def _line_for(out: str) -> str:
    """The worktree's verdict line: the last naming it, after any evacuation detail."""
    return [line for line in out.splitlines() if _NAME in line][-1]


def test_the_fixture_worktree_is_otherwise_reapable(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Guards the fixture: with no ignored content the worktree IS reaped."""
    _reap(repo, reap=True)
    assert not _worktree(repo).exists()
    assert "REAPED" in capsys.readouterr().out


def test_an_ignored_scratch_note_keeps_the_worktree_and_the_note(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    note = _worktree(repo) / "untracked" / "scratch" / "notes.md"
    note.parent.mkdir(parents=True)
    note.write_text("work that exists nowhere else\n", encoding="utf-8")

    rc = _reap(repo, reap=True)

    assert note.read_text(encoding="utf-8") == "work that exists nowhere else\n"
    line = _line_for(capsys.readouterr().out)
    assert line.startswith("KEEP")
    assert "untracked/" in line
    assert rc == 1
    assert _NAME in _git(repo, "branch", "--list", _NAME)


def test_the_dry_run_reports_keep_not_a_removal(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    note = _worktree(repo) / "untracked" / "scratch" / "notes.md"
    note.parent.mkdir(parents=True)
    note.write_text("x\n", encoding="utf-8")

    _reap(repo, reap=False)

    out = capsys.readouterr().out
    assert _line_for(out).startswith("KEEP")
    assert "would remove" not in out.lower()


def test_ignored_content_that_is_all_regenerable_is_still_reaped(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _worktree(repo) / "untracked" / "qa" / "report.json"
    store.parent.mkdir(parents=True)
    store.write_text("{}\n", encoding="utf-8")

    _reap(repo, reap=True)

    assert not _worktree(repo).exists()
    assert "REAPED" in capsys.readouterr().out


def test_a_git_failure_reading_the_worktree_keeps_it(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unread tree is never called clean."""
    worktree = _worktree(repo)

    def failing_in_the_worktree(
        cwd: Path,
        *args: str,
        timeout: float = 30.0,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if Path(cwd) == worktree and args[0] == "ls-files":
            return subprocess.CompletedProcess([], 128, "", "fatal: injected")
        return run_git(cwd, *args, timeout=timeout, env=env)

    monkeypatch.setattr(branch_cleanup, "run_git", failing_in_the_worktree)

    _reap(repo, reap=True)

    assert worktree.exists()
    line = _line_for(capsys.readouterr().out)
    assert line.startswith("KEEP")
    assert "injected" in line


def test_a_note_written_after_the_blockers_check_is_not_deleted(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Plan 00627 finding 4: the blockers are read again just before the removal.

    The seam runs the real check, then writes an ignored note into the worktree
    after the first check returns, as an agent still at work would.
    """
    note = _worktree(repo) / "untracked" / "scratch" / "late.md"
    calls: list[Path] = []

    def check_then_write(path: Path, regenerable: Sequence[str]) -> tuple[str, ...]:
        found = branch_cleanup.worktree_blockers(path, regenerable)
        calls.append(path)
        if len(calls) == 1:
            note.parent.mkdir(parents=True)
            note.write_text("written after the check\n", encoding="utf-8")
        return found

    args = argparse.Namespace(
        project_root=str(repo), base_branch="main", reap=True, only=None, reap_branches=False
    )
    rc = cmd_worktree_reap(
        args,
        age_fn=lambda _p: 999_999.0,
        process_cwds_fn=lambda: {},
        blockers_fn=check_then_write,
    )

    assert note.read_text(encoding="utf-8") == "written after the check\n"
    line = _line_for(capsys.readouterr().out)
    assert line.startswith("KEEP")
    assert "untracked/" in line
    assert rc == 1
    assert _NAME in _git(repo, "branch", "--list", _NAME)
