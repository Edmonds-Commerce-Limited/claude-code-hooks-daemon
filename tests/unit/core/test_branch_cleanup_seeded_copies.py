"""A copy-mode seeded file identical to its source never blocks a removal (Plan 00579).

Real repositories: the subject is git's ignore semantics plus the seed list the
``worktree_create`` handler is configured with.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.branch_cleanup import worktree_blockers

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}

_REGENERABLE = BranchesConfig().cleanup_after_merge.regenerable

_SEED_ENTRY = ".local-grants.json"
_SEED_DIR = ".seed-dir"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    )


def _write_config(repo: Path, entries_yaml: str) -> None:
    (repo / ".claude").mkdir(exist_ok=True)
    (repo / ".claude" / "hooks-daemon.yaml").write_text(
        "handlers:\n"
        "  worktree_create:\n"
        "    worktree_create:\n"
        "      options:\n"
        "        seed:\n"
        "          default_mode: symlink\n"
        f"          entries:\n{entries_yaml}",
        encoding="utf-8",
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    (path / ".gitignore").write_text("untracked/\n", encoding="utf-8")
    (path / "tracked.txt").write_text("t\n", encoding="utf-8")
    _git(path, "add", ".gitignore", "tracked.txt")
    _git(path, "commit", "-m", "Initial commit")
    (path / ".git" / "info" / "exclude").write_text(
        f"{_SEED_ENTRY}\n{_SEED_DIR}/\n.claude/\n", encoding="utf-8"
    )
    return path


def _worktree(repo: Path) -> Path:
    _git(repo, "branch", "feat")
    path = repo.parent / "wt-feat"
    _git(repo, "worktree", "add", str(path), "feat")
    return path


def _copy_seeded_file(repo: Path, content: str = "grants\n") -> Path:
    _write_config(repo, f"            - path: {_SEED_ENTRY}\n              mode: copy\n")
    (repo / _SEED_ENTRY).write_text(content, encoding="utf-8")
    path = _worktree(repo)
    (path / _SEED_ENTRY).write_text(content, encoding="utf-8")
    return path


class TestSeededFileCopy:
    def test_an_identical_copy_is_not_a_blocker(self, repo: Path) -> None:
        path = _copy_seeded_file(repo)
        assert worktree_blockers(path, _REGENERABLE) == ()

    def test_a_diverged_copy_blocks_and_is_named(self, repo: Path) -> None:
        path = _copy_seeded_file(repo)
        (path / _SEED_ENTRY).write_text("grants plus a new permission\n", encoding="utf-8")
        blockers = worktree_blockers(path, _REGENERABLE)
        assert len(blockers) == 1
        assert _SEED_ENTRY in blockers[0]
        assert "differs from its source" in blockers[0]

    def test_a_same_size_diverged_copy_blocks(self, repo: Path) -> None:
        path = _copy_seeded_file(repo, "aaaa\n")
        (path / _SEED_ENTRY).write_text("bbbb\n", encoding="utf-8")
        assert "differs from its source" in worktree_blockers(path, _REGENERABLE)[0]

    def test_a_missing_source_counts_as_diverged(self, repo: Path) -> None:
        path = _copy_seeded_file(repo)
        (repo / _SEED_ENTRY).unlink()
        blockers = worktree_blockers(path, _REGENERABLE)
        assert len(blockers) == 1
        assert _SEED_ENTRY in blockers[0]
        assert "differs from its source" in blockers[0]

    def test_a_source_that_is_a_directory_counts_as_diverged(self, repo: Path) -> None:
        path = _copy_seeded_file(repo)
        (repo / _SEED_ENTRY).unlink()
        (repo / _SEED_ENTRY).mkdir()
        assert "differs from its source" in worktree_blockers(path, _REGENERABLE)[0]

    def test_a_file_that_is_not_in_the_seed_list_still_blocks(self, repo: Path) -> None:
        path = _copy_seeded_file(repo)
        (path / "other.local").write_text("x\n", encoding="utf-8")
        (repo / ".git" / "info" / "exclude").write_text(
            f"*.local\n{_SEED_ENTRY}\n.claude/\n", encoding="utf-8"
        )
        blockers = worktree_blockers(path, _REGENERABLE)
        assert "other.local" in blockers

    def test_a_symlink_mode_entry_that_became_a_real_file_still_blocks(self, repo: Path) -> None:
        _write_config(repo, f"            - {_SEED_ENTRY}\n")
        (repo / _SEED_ENTRY).write_text("grants\n", encoding="utf-8")
        path = _worktree(repo)
        (path / _SEED_ENTRY).write_text("grants\n", encoding="utf-8")
        assert worktree_blockers(path, _REGENERABLE) == (_SEED_ENTRY,)

    def test_default_mode_copy_applies_to_a_bare_entry(self, repo: Path) -> None:
        (repo / ".claude").mkdir()
        (repo / ".claude" / "hooks-daemon.yaml").write_text(
            "handlers:\n  worktree_create:\n    worktree_create:\n      options:\n"
            f"        seed:\n          default_mode: copy\n          entries:\n"
            f"            - {_SEED_ENTRY}\n",
            encoding="utf-8",
        )
        (repo / _SEED_ENTRY).write_text("grants\n", encoding="utf-8")
        path = _worktree(repo)
        (path / _SEED_ENTRY).write_text("grants\n", encoding="utf-8")
        assert worktree_blockers(path, _REGENERABLE) == ()

    def test_no_config_changes_nothing(self, repo: Path) -> None:
        path = _worktree(repo)
        (path / _SEED_ENTRY).write_text("grants\n", encoding="utf-8")
        assert worktree_blockers(path, _REGENERABLE) == (_SEED_ENTRY,)

    def test_a_malformed_config_changes_nothing(self, repo: Path) -> None:
        (repo / ".claude").mkdir()
        (repo / ".claude" / "hooks-daemon.yaml").write_text("handlers: [unclosed\n")
        path = _worktree(repo)
        (path / _SEED_ENTRY).write_text("grants\n", encoding="utf-8")
        assert worktree_blockers(path, _REGENERABLE) == (_SEED_ENTRY,)


class TestSeededDirectoryCopy:
    def _seeded_directory(self, repo: Path) -> Path:
        _write_config(repo, f"            - path: {_SEED_DIR}\n              mode: copy\n")
        (repo / _SEED_DIR / "sub").mkdir(parents=True)
        (repo / _SEED_DIR / "a.txt").write_text("a\n", encoding="utf-8")
        (repo / _SEED_DIR / "sub" / "b.txt").write_text("b\n", encoding="utf-8")
        path = _worktree(repo)
        (path / _SEED_DIR / "sub").mkdir(parents=True)
        (path / _SEED_DIR / "a.txt").write_text("a\n", encoding="utf-8")
        (path / _SEED_DIR / "sub" / "b.txt").write_text("b\n", encoding="utf-8")
        return path

    def test_an_identical_directory_is_not_a_blocker(self, repo: Path) -> None:
        assert worktree_blockers(self._seeded_directory(repo), _REGENERABLE) == ()

    def test_a_changed_file_inside_blocks_the_directory(self, repo: Path) -> None:
        path = self._seeded_directory(repo)
        (path / _SEED_DIR / "sub" / "b.txt").write_text("changed\n", encoding="utf-8")
        blockers = worktree_blockers(path, _REGENERABLE)
        assert len(blockers) == 1
        assert _SEED_DIR in blockers[0]
        assert "differs from its source" in blockers[0]

    def test_an_extra_file_inside_blocks_the_directory(self, repo: Path) -> None:
        path = self._seeded_directory(repo)
        (path / _SEED_DIR / "extra.txt").write_text("new\n", encoding="utf-8")
        assert "differs from its source" in worktree_blockers(path, _REGENERABLE)[0]

    def test_a_file_missing_from_the_worktree_copy_blocks_the_directory(self, repo: Path) -> None:
        path = self._seeded_directory(repo)
        (path / _SEED_DIR / "a.txt").unlink()
        assert "differs from its source" in worktree_blockers(path, _REGENERABLE)[0]
