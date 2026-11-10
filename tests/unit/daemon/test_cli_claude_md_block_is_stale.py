"""The upgrade script's staleness question leaves the project untouched (Plan 00594 round 3)."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import claude_md_block_is_stale


def _git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=path, capture_output=True, text=True, check=True
    ).stdout


def _tree_state(path: Path) -> tuple[str, dict[str, bytes]]:
    status = _git(path, "status", "--porcelain", "--ignored")
    files = {
        str(p.relative_to(path)): p.read_bytes()
        for p in sorted(path.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(path).parts
    }
    return status, files


@pytest.fixture(autouse=True)
def _reset_project_context() -> Iterator[None]:
    yield
    ProjectContext.reset()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    _git(tmp_path, "remote", "add", "origin", "git@example.invalid:owner/repo.git")
    (tmp_path / "CLAUDE.md").write_text("# Project\n", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(
        'version: "2.0"\nbranches:\n  home_commit: false\n', encoding="utf-8"
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_the_staleness_question_leaves_the_tree_byte_identical(project: Path) -> None:
    config = Config.load(project / ".claude" / "hooks-daemon.yaml")
    before = _tree_state(project)
    assert claude_md_block_is_stale(config, project) is True
    assert _tree_state(project) == before
