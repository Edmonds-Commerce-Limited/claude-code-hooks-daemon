"""The controller passes ``branches:`` to the CLAUDE.md injector (Plan 00594 M-1).

Every injector test builds ``ClaudeMdInjector`` directly, so a controller that
stopped passing ``branches=`` would silently turn ``home_commit: false`` back
into committing on a protected home branch with no test failing.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.handlers.session_start.project_handler_load_checker import (
    ProjectHandlerLoadCheckerHandler,
)


def _git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=path, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed repository on ``main`` whose CLAUDE.md has no daemon block."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    _git(tmp_path, "remote", "add", "origin", "git@example.invalid:owner/repo.git")
    (tmp_path / "CLAUDE.md").write_text("# Project\n", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(
        "version: '1.0'\nhandlers:\n  pre_tool_use: {}\n", encoding="utf-8"
    )
    _git(tmp_path, "add", "CLAUDE.md", ".claude/hooks-daemon.yaml")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_project_context() -> Iterator[None]:
    yield
    ProjectContext.reset()


def _initialise(repo: Path, branches: BranchesConfig) -> DaemonController:
    controller = DaemonController()
    controller.initialise(workspace_root=repo, branches=branches)
    return controller


def test_branches_reach_the_injector_so_home_commit_false_does_not_write_or_commit(
    repo: Path,
) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    _initialise(repo, BranchesConfig(home_commit=False))
    assert "<hooksdaemon>" not in (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert _git(repo, "status", "--porcelain", "CLAUDE.md") == ""
    assert _git(repo, "rev-parse", "HEAD") == head


def test_the_default_branches_config_still_writes_and_commits(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    _initialise(repo, BranchesConfig())
    assert "<hooksdaemon>" in (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert _git(repo, "rev-parse", "HEAD") != head


def test_a_stale_block_notice_reaches_the_session_start_handler(repo: Path) -> None:
    controller = _initialise(repo, BranchesConfig(home_commit=False))
    checkers = [
        handler
        for handlers in controller._router.get_all_handlers().values()
        for handler in handlers
        if isinstance(handler, ProjectHandlerLoadCheckerHandler)
    ]
    assert checkers
    assert any("stale on main" in notice for notice in checkers[0]._startup_notices)
