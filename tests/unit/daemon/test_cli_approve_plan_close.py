"""Tests for the ``approve-plan-close`` CLI command (Plan 00367).

A human's route through the ``plan_workflow.close_requires_human_approval``
gate: record a one-shot approval for one plan, which the very next terminal
status flip of that plan consumes. The command refuses a plan number that
names no active plan folder, because an approval for a typo would sit in
``untracked/`` waiting to close the wrong plan.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.plan_qa.close_approval import approval_marker_path

_CONFIG_GATE_ON = (
    'version: "2.0"\nplan_workflow:\n  enabled: true\n  close_requires_human_approval: true\n'
)
_CONFIG_GATE_OFF = 'version: "2.0"\nplan_workflow:\n  enabled: true\n'
_CONFIG_NO_PLANS = 'version: "2.0"\nplan_workflow:\n  enabled: false\n'


@pytest.fixture(autouse=True)
def _reset_project_context() -> Iterator[None]:
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    yield
    ProjectContext.reset()


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(_CONFIG_GATE_ON, encoding="utf-8")
    (tmp_path / "CLAUDE" / "Plan" / "00042-widget").mkdir(parents=True)
    (tmp_path / "CLAUDE" / "Plan" / "00042-widget" / "PLAN.md").write_text(
        "# Plan 00042: Widget\n\n**Status**: In Progress\n", encoding="utf-8"
    )
    with patch(
        "claude_code_hooks_daemon.core.project_context.ProjectContext.daemon_untracked_dir",
        return_value=tmp_path / "untracked",
    ):
        yield tmp_path


def _args(project_root: Path, plan_number: str) -> argparse.Namespace:
    return argparse.Namespace(project_root=project_root, plan_number=plan_number)


def test_records_a_marker_for_an_active_plan(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.cmd_approve_plan_close(_args(project, "42")) == 0
    marker = approval_marker_path(project / "untracked", 42)
    assert marker.is_file()
    out = capsys.readouterr().out
    assert "00042" in out
    assert str(marker) in out


def test_accepts_a_zero_padded_number(project: Path) -> None:
    assert cli.cmd_approve_plan_close(_args(project, "00042")) == 0
    assert approval_marker_path(project / "untracked", 42).is_file()


def test_refuses_a_number_with_no_active_plan_folder(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.cmd_approve_plan_close(_args(project, "99")) == 1
    assert not approval_marker_path(project / "untracked", 99).exists()
    assert "00099" in capsys.readouterr().err


def test_refuses_a_non_numeric_argument(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.cmd_approve_plan_close(_args(project, "forty-two")) == 1
    assert "plan number" in capsys.readouterr().err


def test_refuses_when_plan_workflow_is_disabled(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / ".claude" / "hooks-daemon.yaml").write_text(_CONFIG_NO_PLANS, encoding="utf-8")
    assert cli.cmd_approve_plan_close(_args(project, "42")) == 1
    assert "plan_workflow" in capsys.readouterr().err


def test_warns_when_the_gate_is_off(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The marker is still written (the human may be about to turn the key
    on), but nothing will consume it while the gate is off, and the human
    should know that rather than wait for a deny that never comes."""
    (project / ".claude" / "hooks-daemon.yaml").write_text(_CONFIG_GATE_OFF, encoding="utf-8")
    assert cli.cmd_approve_plan_close(_args(project, "42")) == 0
    assert approval_marker_path(project / "untracked", 42).is_file()
    assert "close_requires_human_approval" in capsys.readouterr().out


def test_subcommand_is_wired_into_the_parser() -> None:
    seen: list[argparse.Namespace] = []

    def capture(args: argparse.Namespace) -> int:
        seen.append(args)
        return 0

    with (
        patch("sys.argv", ["claude-hooks-daemon", "approve-plan-close", "00042"]),
        patch.object(cli, "cmd_approve_plan_close", capture),
    ):
        cli.main()
    assert len(seen) == 1
    assert seen[0].plan_number == "00042"
