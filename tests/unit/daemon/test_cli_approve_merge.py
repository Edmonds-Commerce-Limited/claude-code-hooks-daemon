"""Tests for the ``approve-merge`` CLI command (Plan 00367 Phase 4).

A human's route through ``worktree.merge_to_main_requires_human_approval``:
record a one-shot approval for one branch, which the next ``git merge`` of
that branch in the main checkout consumes.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.handlers.pre_tool_use.merge_to_main_approval import (
    APPROVAL_SUBDIR,
)
from claude_code_hooks_daemon.utils.one_shot_approval import OneShotApprovalStore

_STORE = OneShotApprovalStore(APPROVAL_SUBDIR)
_CONFIG_GATE_ON = 'version: "2.0"\nworktree:\n  merge_to_main_requires_human_approval: true\n'
_CONFIG_GATE_OFF = 'version: "2.0"\n'


@pytest.fixture(autouse=True)
def _reset_project_context() -> Iterator[None]:
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    yield
    ProjectContext.reset()


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(_CONFIG_GATE_ON, encoding="utf-8")
    with patch(
        "claude_code_hooks_daemon.core.project_context.ProjectContext.daemon_untracked_dir",
        return_value=tmp_path / "untracked",
    ):
        yield tmp_path


def _args(project_root: Path, branch: str) -> argparse.Namespace:
    return argparse.Namespace(project_root=project_root, branch=branch)


def test_records_a_marker_for_the_branch(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.cmd_approve_merge(_args(project, "worktree-plan-00367")) == 0
    marker = _STORE.path(project / "untracked", "worktree-plan-00367")
    assert marker.is_file()
    out = capsys.readouterr().out
    assert "worktree-plan-00367" in out
    assert str(marker) in out


def test_refuses_an_empty_branch(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.cmd_approve_merge(_args(project, "  ")) == 1
    assert "branch" in capsys.readouterr().err


def test_notes_when_the_gate_is_off(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (project / ".claude" / "hooks-daemon.yaml").write_text(_CONFIG_GATE_OFF, encoding="utf-8")
    assert cli.cmd_approve_merge(_args(project, "feature")) == 0
    assert _STORE.path(project / "untracked", "feature").is_file()
    assert "merge_to_main_requires_human_approval" in capsys.readouterr().out


def test_subcommand_is_wired_into_the_parser() -> None:
    seen: list[argparse.Namespace] = []

    def capture(args: argparse.Namespace) -> int:
        seen.append(args)
        return 0

    with (
        patch("sys.argv", ["claude-hooks-daemon", "approve-merge", "worktree-plan-00367"]),
        patch.object(cli, "cmd_approve_merge", capture),
    ):
        cli.main()
    assert len(seen) == 1
    assert seen[0].branch == "worktree-plan-00367"
