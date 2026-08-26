"""Tests for the ``inject-goal`` CLI command (Plan 00269, Task 2.3).

Manual fallback / primary debugging tool for supervisor goal injection: writes
the SAME ``<session>.goal-intent`` signal the ``goal_injection`` handler
writes, with ``source: cli``. The signal file is session-keyed, so the
command resolves the target session id from ``CLAUDE_CODE_SESSION_ID`` (set
when run from a Claude Code Bash tool) and refuses with a clear message when
it is unset or the plan folder does not exist.
"""

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import (
    _SIGNAL_SUBDIR,
    _SIGNAL_SUFFIX,
)

_SESSION = "cli-session-42"
_PLAN_NUMBER = "00269"


@pytest.fixture(autouse=True)
def _reset_project_context():
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    yield
    ProjectContext.reset()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    plan_dir = tmp_path / "CLAUDE" / "Plan" / "00269-supervisor-goal-message-injection"
    plan_dir.mkdir(parents=True)
    (plan_dir / "PLAN.md").write_text(
        "# Plan 00269: supervisor goal message injection\n\n**Status**: In Progress\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _SESSION)
    monkeypatch.setattr(
        "claude_code_hooks_daemon.handlers.post_tool_use.goal_injection."
        "ProjectContext.daemon_untracked_dir",
        classmethod(lambda cls: tmp_path / "untracked"),
    )
    return tmp_path


def _args(project_root: Path, plan_number: str = _PLAN_NUMBER) -> argparse.Namespace:
    return argparse.Namespace(plan_number=plan_number, project_root=project_root)


def _signal_path(project_root: Path) -> Path:
    return project_root / "untracked" / _SIGNAL_SUBDIR / f"{_SESSION}{_SIGNAL_SUFFIX}"


def test_writes_cli_sourced_signal(project: Path, capsys) -> None:
    rc = cli.cmd_inject_goal(_args(project))
    assert rc == 0
    data = json.loads(_signal_path(project).read_text(encoding="utf-8"))
    assert data["source"] == "cli"
    assert data["plan_number"] == _PLAN_NUMBER
    assert data["session_id"] == _SESSION
    joined = data["rendered_lines"][0]
    assert joined.startswith("🤖 [ccy-supervisor]")
    assert "supervisor goal message injection" in joined
    assert str(_signal_path(project)) in capsys.readouterr().out


def test_refuses_without_session_id(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    rc = cli.cmd_inject_goal(_args(project))
    assert rc == 1
    assert "CLAUDE_CODE_SESSION_ID" in capsys.readouterr().err
    assert not _signal_path(project).exists()


def test_refuses_missing_plan_folder(project: Path, capsys) -> None:
    rc = cli.cmd_inject_goal(_args(project, plan_number="00042"))
    assert rc == 1
    assert "00042" in capsys.readouterr().err
    assert not _signal_path(project).exists()


def test_refuses_invalid_plan_number(project: Path, capsys) -> None:
    rc = cli.cmd_inject_goal(_args(project, plan_number="269"))
    assert rc == 1
    assert "5-digit" in capsys.readouterr().err


def test_applies_config_options(project: Path) -> None:
    config = project / ".claude" / "hooks-daemon.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "handlers:\n"
        "  post_tool_use:\n"
        "    goal_injection:\n"
        "      enabled: true\n"
        "      options:\n"
        "        lines:\n"
        "          - id: motto\n"
        '            text: "Motto for {plan_number}."\n',
        encoding="utf-8",
    )
    rc = cli.cmd_inject_goal(_args(project))
    assert rc == 0
    data = json.loads(_signal_path(project).read_text(encoding="utf-8"))
    assert f"Motto for {_PLAN_NUMBER}." in data["rendered_lines"][0]


def test_completed_plan_folder_not_matched(project: Path, capsys) -> None:
    completed = project / "CLAUDE" / "Plan" / "Completed" / "00099-old-plan"
    completed.mkdir(parents=True)
    (completed / "PLAN.md").write_text("# Plan 00099: old\n**Status**: Complete\n")
    rc = cli.cmd_inject_goal(_args(project, plan_number="00099"))
    assert rc == 1
    assert "00099" in capsys.readouterr().err
