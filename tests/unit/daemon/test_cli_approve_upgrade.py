"""Tests for the ``approve-upgrade`` CLI command (Plan 00376 Task 3.2).

The owner's route through the upgrade gate's escalation. The approval is
human-only (review MAJOR 4): it needs a terminal on stdin and the typed phrase
naming both versions, and the marker it writes is bound to the from/to
versions and the install path, so a marker an agent could forge by other means
does not count and an agent's shell (no terminal) cannot run this.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir
from claude_code_hooks_daemon.install.upgrade_gate import (
    APPROVAL_SUBDIR,
    ApprovalState,
    check_approval,
)

_PHRASE = "approve upgrade from v3.66.0 to v4.0.0\n"


class _FakeTty(io.StringIO):
    def __init__(self, text: str, *, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "hooks-daemon").mkdir(parents=True)
    return tmp_path


def _args(project_root: Path, version: str, from_version: str = "3.66.0") -> argparse.Namespace:
    return argparse.Namespace(project_root=project_root, version=version, from_version=from_version)


def _approve(args: argparse.Namespace, answer: str, *, tty: bool = True) -> int:
    with patch("sys.stdin", _FakeTty(answer, tty=tty)):
        return cli.cmd_approve_upgrade(args)


def _state(project: Path, to_version: str = "4.0.0") -> ApprovalState:
    return check_approval(
        get_untracked_dir(project),
        to_version=to_version,
        from_version="3.66.0",
        daemon_dir=project / ".claude" / "hooks-daemon",
        project_root=project,
    )


@pytest.mark.parametrize("spelling", ["4.0.0", "v4.0.0", "v4.0", "4.0.0+main.abc1234"])
def test_the_typed_phrase_records_an_approval_bound_to_this_upgrade(
    project: Path, spelling: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _approve(_args(project, spelling), _PHRASE) == 0
    assert _state(project) is ApprovalState.VALID
    assert "4.0.0" in capsys.readouterr().out


def test_without_a_terminal_nothing_is_approved(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _approve(_args(project, "4.0.0"), _PHRASE, tty=False) == 1
    assert "terminal" in capsys.readouterr().out
    assert not (get_untracked_dir(project) / APPROVAL_SUBDIR).exists()


def test_the_wrong_phrase_approves_nothing(project: Path) -> None:
    assert _approve(_args(project, "4.0.0"), "yes\n") == 1
    assert _state(project) is ApprovalState.ABSENT


def test_a_self_install_binds_the_project_root_as_the_daemon_dir(tmp_path: Path) -> None:
    (tmp_path / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    assert _approve(_args(tmp_path, "4.0.0"), _PHRASE) == 0
    state = check_approval(
        get_untracked_dir(tmp_path),
        to_version="4.0.0",
        from_version="3.66.0",
        daemon_dir=tmp_path,
        project_root=tmp_path,
    )
    assert state is ApprovalState.VALID


def test_refuses_something_that_is_not_a_version(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _approve(_args(project, "latest"), _PHRASE) == 1
    assert "version" in capsys.readouterr().err
    assert not (get_untracked_dir(project) / APPROVAL_SUBDIR).exists()


def test_subcommand_is_wired_into_the_parser_and_needs_from() -> None:
    seen: list[argparse.Namespace] = []

    def capture(args: argparse.Namespace) -> int:
        seen.append(args)
        return 0

    with (
        patch(
            "sys.argv",
            ["claude-hooks-daemon", "approve-upgrade", "4.0.0", "--from", "3.66.0"],
        ),
        patch.object(cli, "cmd_approve_upgrade", capture),
    ):
        cli.main()
    assert len(seen) == 1
    assert seen[0].version == "4.0.0"
    assert seen[0].from_version == "3.66.0"

    with (
        patch("sys.argv", ["claude-hooks-daemon", "approve-upgrade", "4.0.0"]),
        patch.object(cli, "cmd_approve_upgrade", capture),
        pytest.raises(SystemExit),
    ):
        cli.main()
