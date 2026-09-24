"""Tests for the ``approve-upgrade`` CLI command (Plan 00376 Task 3.2).

The owner's route through the upgrade gate's escalation: record a one-shot
approval for one target release, which the next acknowledged upgrade to that
release consumes. The marker lives where the gate looks for it, which is the
project's daemon untracked directory as ``install_layout`` resolves it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir
from claude_code_hooks_daemon.install.upgrade_gate import APPROVAL_SUBDIR
from claude_code_hooks_daemon.utils.one_shot_approval import OneShotApprovalStore

_STORE = OneShotApprovalStore(APPROVAL_SUBDIR)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "hooks-daemon").mkdir(parents=True)
    return tmp_path


def _args(project_root: Path, version: str) -> argparse.Namespace:
    return argparse.Namespace(project_root=project_root, version=version)


@pytest.mark.parametrize("spelling", ["4.0.0", "v4.0.0", "v4.0", "4.0.0+main.abc1234"])
def test_records_one_marker_per_release_whatever_the_spelling(
    project: Path, spelling: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.cmd_approve_upgrade(_args(project, spelling)) == 0
    marker = _STORE.path(get_untracked_dir(project), "4.0.0")
    assert marker.is_file()
    out = capsys.readouterr().out
    assert "4.0.0" in out
    assert str(marker) in out


def test_refuses_something_that_is_not_a_version(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.cmd_approve_upgrade(_args(project, "latest")) == 1
    assert "version" in capsys.readouterr().err
    assert not (get_untracked_dir(project) / APPROVAL_SUBDIR).exists()


def test_subcommand_is_wired_into_the_parser() -> None:
    seen: list[argparse.Namespace] = []

    def capture(args: argparse.Namespace) -> int:
        seen.append(args)
        return 0

    with (
        patch("sys.argv", ["claude-hooks-daemon", "approve-upgrade", "4.0.0"]),
        patch.object(cli, "cmd_approve_upgrade", capture),
    ):
        cli.main()
    assert len(seen) == 1
    assert seen[0].version == "4.0.0"
