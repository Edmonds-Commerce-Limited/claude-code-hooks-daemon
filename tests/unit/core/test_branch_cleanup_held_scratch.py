"""cleanup_after_merge on a branch held by a worktree that holds scratch (Plan 00627 Task 6.2).

The cleanup prints and nothing else: when the holding worktree's
``untracked/scratch`` has a child, the bare ``git worktree remove`` line (which
the guard would deny, and which would lose the notes) is replaced by the human
route, ``worktree-reap --reap --only <name>`` at a terminal. Real repositories.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_cleanup
from claude_code_hooks_daemon.core.branch_cleanup import (
    CleanupReport,
    cleanup_after_merge,
    holds_scratch,
)
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}

_CONFIG = BranchesConfig(default="main")
_NAME = "agent-abc123"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    )
    return result.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    (path / ".gitignore").write_text("untracked/\n.claude/worktrees/\n", encoding="utf-8")
    _git(path, "add", ".gitignore")
    _git(path, "commit", "-m", "Initial commit")
    return path


def _merged_and_held(repo: Path, name: str, path: Path) -> Path:
    _git(repo, "checkout", "-b", name)
    (repo / "work.txt").write_text("work\n", encoding="utf-8")
    _git(repo, "add", "work.txt")
    _git(repo, "commit", "-m", "Work")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "-m", f"Merge {name}", name)
    _git(repo, "worktree", "add", str(path), name)
    return path


def _sanctioned(repo: Path) -> Path:
    return _merged_and_held(repo, _NAME, repo / ".claude" / "worktrees" / _NAME)


def _scratch(worktree: Path) -> Path:
    scratch = worktree / "untracked" / "scratch"
    scratch.mkdir(parents=True)
    return scratch


def _reap_command(name: str) -> str:
    return daemon_cli_command_for_docs("worktree-reap", "--reap", "--only", name)


def _clean(repo: Path) -> CleanupReport:
    return cleanup_after_merge(repo, [_NAME], config=_CONFIG, target="main", mode="act")


def _deny_scandir(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(path: Path) -> None:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(branch_cleanup.os, "scandir", denied)


class TestHoldsScratch:
    def test_absent_is_false(self, tmp_path: Path) -> None:
        assert holds_scratch(tmp_path) is False

    def test_empty_is_false(self, tmp_path: Path) -> None:
        _scratch(tmp_path)
        assert holds_scratch(tmp_path) is False

    def test_a_child_is_true(self, tmp_path: Path) -> None:
        (_scratch(tmp_path) / "notes.md").write_text("x\n", encoding="utf-8")
        assert holds_scratch(tmp_path) is True

    def test_a_link_is_not_a_scratch_directory(self, tmp_path: Path) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "notes.md").write_text("x\n", encoding="utf-8")
        (tmp_path / "wt" / "untracked").mkdir(parents=True)
        (tmp_path / "wt" / "untracked" / "scratch").symlink_to(elsewhere)
        assert holds_scratch(tmp_path / "wt") is False

    def test_unreadable_fails_closed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _scratch(tmp_path)
        _deny_scandir(monkeypatch)
        assert holds_scratch(tmp_path) is True

    def test_the_probe_reads_one_entry_however_many_there_are(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scratch = _scratch(tmp_path)
        for index in range(50):
            (scratch / f"n{index}").write_text("x\n", encoding="utf-8")
        pulled: list[str] = []
        real = os.scandir

        class _Counting:
            def __init__(self, path: Path) -> None:
                self._inner = real(path)

            def __enter__(self) -> _Counting:
                return self

            def __exit__(self, *exc: object) -> None:
                self._inner.close()

            def __iter__(self) -> _Counting:
                return self

            def __next__(self) -> os.DirEntry[str]:
                entry = next(self._inner)
                pulled.append(entry.name)
                return entry

        monkeypatch.setattr(branch_cleanup.os, "scandir", _Counting)
        assert holds_scratch(tmp_path) is True
        assert len(pulled) == 1


class TestCleanupAfterMergeWithScratch:
    def test_scratch_prints_the_human_command_and_no_bare_remove(self, repo: Path) -> None:
        worktree = _sanctioned(repo)
        (_scratch(worktree) / "notes.md").write_text("keep me\n", encoding="utf-8")
        report = _clean(repo)
        assert report.deleted == ()
        assert _reap_command(_NAME) in report.commands
        assert not any(c.startswith("git worktree remove") for c in report.commands)
        assert any("holds scratch" in line and "terminal" in line for line in report.skipped)
        assert (worktree / "untracked" / "scratch" / "notes.md").read_text() == "keep me\n"

    def test_the_branch_delete_line_is_kept(self, repo: Path) -> None:
        worktree = _sanctioned(repo)
        (_scratch(worktree) / "notes.md").write_text("x\n", encoding="utf-8")
        report = _clean(repo)
        delete = daemon_cli_command_for_docs("delete-branch", _NAME, "--protected-ref", "main")
        assert delete in report.commands

    @pytest.mark.parametrize("make_root", [True, False], ids=["empty-root", "absent-root"])
    def test_no_scratch_keeps_todays_output(self, repo: Path, make_root: bool) -> None:
        worktree = _sanctioned(repo)
        if make_root:
            _scratch(worktree)
        report = _clean(repo)
        assert f"git worktree remove {worktree}" in report.commands
        assert _reap_command(_NAME) not in report.commands
        assert report.skipped == (f"{_NAME}: checked out in the worktree {worktree}",)

    def test_outside_the_sanctioned_roots_no_command_is_printed(
        self, repo: Path, tmp_path: Path
    ) -> None:
        worktree = _merged_and_held(repo, _NAME, tmp_path / "elsewhere" / _NAME)
        (_scratch(worktree) / "notes.md").write_text("x\n", encoding="utf-8")
        report = _clean(repo)
        assert not any("worktree-reap" in c for c in report.commands)
        assert not any(c.startswith("git worktree remove") for c in report.commands)
        assert any("holds scratch" in line and "by hand" in line for line in report.skipped)

    def test_a_nested_path_under_a_sanctioned_root_gets_no_command(self, repo: Path) -> None:
        nested = repo / ".claude" / "worktrees" / "group" / _NAME
        worktree = _merged_and_held(repo, _NAME, nested)
        (_scratch(worktree) / "notes.md").write_text("x\n", encoding="utf-8")
        report = _clean(repo)
        assert not any("worktree-reap" in c for c in report.commands)
        assert any("by hand" in line for line in report.skipped)

    def test_unreadable_scratch_prints_the_human_line(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        worktree = _sanctioned(repo)
        _scratch(worktree)
        _deny_scandir(monkeypatch)
        report = _clean(repo)
        assert _reap_command(_NAME) in report.commands
        assert not any(c.startswith("git worktree remove") for c in report.commands)

    def test_a_merge_run_inside_a_linked_worktree_names_the_reap_command(self, repo: Path) -> None:
        worktree = _sanctioned(repo)
        (_scratch(worktree) / "notes.md").write_text("x\n", encoding="utf-8")
        other = repo / ".claude" / "worktrees" / "agent-other"
        _git(repo, "worktree", "add", "-b", "other", str(other), "main")
        report = cleanup_after_merge(other, [_NAME], config=_CONFIG, target="main", mode="act")
        assert _reap_command(_NAME) in report.commands
