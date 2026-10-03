"""Tests for commit_runs_in_foreign_repo (ledger 00474 N300/N305)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.commit_location import commit_runs_in_foreign_repo
from claude_code_hooks_daemon.utils.git_commit_parsing import CommitReading, read_commit_form


def _init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path.resolve()


def _reading(command: str) -> CommitReading:
    return read_commit_form(command)


class TestCommitRunsInForeignRepo:
    """The gate stands down only when the commit certainly runs elsewhere."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        """The project's own repository."""
        return _init(tmp_path / "project")

    def test_no_cwd_is_not_foreign(self, project: Path) -> None:
        """Without a cwd the commit is judged against this project."""
        assert commit_runs_in_foreign_repo(_reading("git commit -m x"), None, project) is False

    def test_cwd_inside_project_is_not_foreign(self, project: Path) -> None:
        """A commit run from the project's own root is not foreign."""
        assert commit_runs_in_foreign_repo(_reading("git commit -m x"), project, project) is False

    def test_cwd_outside_any_repo_is_not_foreign(self, project: Path, tmp_path: Path) -> None:
        """A directory in no repository cannot be called another repository."""
        bare = tmp_path / "plain"
        bare.mkdir()
        assert commit_runs_in_foreign_repo(_reading("git commit -m x"), bare, project) is False

    def test_cwd_in_other_repo_is_foreign(self, project: Path, tmp_path: Path) -> None:
        """A commit run inside another checkout is foreign."""
        other = _init(tmp_path / "other")
        assert commit_runs_in_foreign_repo(_reading("git commit -m x"), other, project) is True

    def test_dash_c_into_other_repo_is_foreign(self, project: Path, tmp_path: Path) -> None:
        """A -C move into another checkout makes the commit foreign."""
        other = _init(tmp_path / "other")
        reading = _reading(f"git -C {other} commit -m x")
        assert commit_runs_in_foreign_repo(reading, project, project) is True
