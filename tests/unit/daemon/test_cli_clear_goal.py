"""Tests for the ``clear-goal`` CLI command (Plan 00321).

The automatic retraction fires when a retirement empties the goal ledger. That
leaves one gap, and it is the one that stranded a real session: if the ledger
is ALREADY empty while the upstream ``/goal`` slot still holds a condition,
there is no retirement left to trigger anything, so the stale goal challenges
every stop until the session ends.

``clear-goal`` closes that gap. Unlike ``inject-goal`` it takes no plan number
-- there is no plan involved in retracting a goal, and requiring an ACTIVE one
would refuse in exactly the stale-slot case this exists for.
"""

import argparse
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import (
    _CLEAR_SUFFIX,
    _SIGNAL_SUBDIR,
    _SIGNAL_SUFFIX,
)

_SESSION = "cli-session-42"


@pytest.fixture(autouse=True)
def _reset_project_context():
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    yield
    ProjectContext.reset()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _SESSION)
    monkeypatch.setattr(
        "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
        "ProjectContext.daemon_untracked_dir",
        classmethod(lambda cls: tmp_path / "untracked"),
    )
    return tmp_path


def _args(project_root: Path) -> argparse.Namespace:
    return argparse.Namespace(project_root=project_root)


def _clear_path(project_root: Path) -> Path:
    return project_root / "untracked" / _SIGNAL_SUBDIR / f"{_SESSION}{_CLEAR_SUFFIX}"


def test_writes_a_clear_trigger(project: Path) -> None:
    assert cli.cmd_clear_goal(_args(project)) == 0
    assert _clear_path(project).exists()


def test_works_with_no_live_plan_at_all(project: Path) -> None:
    """The whole point: no plan number, no ledger entry, no plan folder.

    ``inject-goal`` requires an ACTIVE plan and would refuse here, which is
    why it could not be reused to clear a stale slot.
    """
    assert not (project / "CLAUDE" / "Plan").exists()
    assert cli.cmd_clear_goal(_args(project)) == 0
    assert _clear_path(project).exists()


def test_also_removes_a_pending_goal_intent(project: Path) -> None:
    """A queued but un-injected goal must not survive the retraction."""
    sidecar = project / "untracked" / _SIGNAL_SUBDIR
    sidecar.mkdir(parents=True)
    pending = sidecar / f"{_SESSION}{_SIGNAL_SUFFIX}"
    pending.write_text("{}", encoding="utf-8")

    assert cli.cmd_clear_goal(_args(project)) == 0

    assert not pending.exists()
    assert _clear_path(project).exists()


def test_refuses_without_a_session_id(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Session-keyed, exactly like inject-goal: no id, no target."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

    assert cli.cmd_clear_goal(_args(project)) == 1

    assert "CLAUDE_CODE_SESSION_ID" in capsys.readouterr().err
    assert not _clear_path(project).exists()


def test_is_idempotent(project: Path) -> None:
    """Clearing an already-cleared goal is not an error."""
    assert cli.cmd_clear_goal(_args(project)) == 0
    assert cli.cmd_clear_goal(_args(project)) == 0
    assert _clear_path(project).exists()
