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
from claude_code_hooks_daemon.handlers.session_start.branch_sweep import BranchSweepHandler


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


def _sweep_handlers(controller: DaemonController) -> list[BranchSweepHandler]:
    return [
        handler
        for handlers in controller._router.get_all_handlers().values()
        for handler in handlers
        if isinstance(handler, BranchSweepHandler)
    ]


def test_a_stale_block_notice_reaches_the_session_start_handler(repo: Path) -> None:
    controller = _initialise(repo, BranchesConfig(home_commit=False))
    sweeps = _sweep_handlers(controller)
    assert sweeps
    provider = sweeps[0].claude_md_notices
    assert provider is not None
    assert any("stale on main" in notice for notice in provider())


def test_the_notice_is_available_before_the_deferred_injection_has_run(repo: Path) -> None:
    """The SessionStart that started the daemon is answered before the injection runs."""
    controller = DaemonController()
    controller.initialise(
        workspace_root=repo,
        branches=BranchesConfig(home_commit=False),
        defer_nonessential_startup=True,
    )
    provider = _sweep_handlers(controller)[0].claude_md_notices
    assert provider is not None
    assert any("stale on main" in notice for notice in provider())


def test_the_notice_clears_when_the_block_is_made_current(repo: Path) -> None:
    controller = _initialise(repo, BranchesConfig(home_commit=False))
    provider = _sweep_handlers(controller)[0].claude_md_notices
    assert provider is not None
    assert provider()
    _initialise(repo, BranchesConfig())  # a default-config start-up writes and commits it
    assert provider() == []


def test_the_controller_answers_the_upgrade_script_with_the_current_notices(repo: Path) -> None:
    assert DaemonController().claude_md_notices() == []
    controller = _initialise(repo, BranchesConfig(home_commit=False))
    assert any("stale on main" in notice for notice in controller.claude_md_notices())


def test_a_missing_branch_sweep_is_logged_as_a_notice_with_no_recipient(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Plan 00594 round 3: with no sweep handler the CLAUDE.md notice reaches no agent."""
    with caplog.at_level("WARNING"):
        DaemonController._publish_claude_md_notices([], lambda: [])
    warnings = [r for r in caplog.records if "no recipient" in r.getMessage()]
    assert len(warnings) == 1
    assert warnings[0].levelname == "WARNING"
    assert "branch_sweep" in warnings[0].getMessage()


def test_no_recipient_warning_when_the_sweep_is_registered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        DaemonController._publish_claude_md_notices([BranchSweepHandler()], lambda: [])
    assert not [r for r in caplog.records if "no recipient" in r.getMessage()]
