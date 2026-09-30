"""``check-post-upgrade-tasks`` (Plan 00376 Task 4.3).

The command behind the upgrade skill's mandatory post-upgrade-tasks step. Its
exit codes mirror ``check-truth-changes``: 0 nothing to do, 1 tasks to carry
out, 2 on a bad range.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_check_post_upgrade_tasks, main
from claude_code_hooks_daemon.install import upgrade_guides

_TASK = "# Task: t\n\n**Type**: audit\n**Severity**: critical\n**Applies to**: all\n"


@pytest.fixture
def upgrades(tmp_path: Path) -> Path:
    root = tmp_path / "UPGRADES"
    tasks = root / "v3" / "v3.63.0-to-v3.64.0" / "post-upgrade-tasks"
    tasks.mkdir(parents=True)
    (tasks / "01-rewrite.md").write_text(_TASK)
    staged = root / "UNRELEASED" / "post-upgrade-tasks"
    staged.mkdir(parents=True)
    (staged / "01-staged.md").write_text(_TASK)
    return root


@pytest.fixture(autouse=True)
def release_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_guides, "is_branch_install", lambda: False)


def _args(upgrades: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "from_version": "3.63.0",
        "to_version": "3.64.0",
        "format": "text",
        "upgrades_dir": str(upgrades),
        "include_unreleased": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_tasks_in_range_exit_one_and_are_named(
    upgrades: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cmd_check_post_upgrade_tasks(_args(upgrades)) == 1
    out = capsys.readouterr().out
    assert "01-rewrite.md" in out
    assert "01-staged.md" not in out


def test_nothing_in_range_exits_zero(upgrades: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd_check_post_upgrade_tasks(_args(upgrades, from_version="3.64.0")) == 0
    assert "No post-upgrade tasks" in capsys.readouterr().out


def test_flag_forces_the_holding_area_in(
    upgrades: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_check_post_upgrade_tasks(
        _args(upgrades, from_version="3.64.0", include_unreleased=True, format="json")
    )
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert [task["source"] for task in payload["tasks"]] == ["UNRELEASED"]


def test_bad_range_exits_two(upgrades: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd_check_post_upgrade_tasks(_args(upgrades, from_version="3.65.0")) == 2
    assert "ERROR" in capsys.readouterr().err


def test_registered_with_the_parser(
    upgrades: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hooks-daemon",
            "check-post-upgrade-tasks",
            "--from",
            "v3.63.0",
            "--to",
            "3.64.0+main.abc1234",
            "--upgrades-dir",
            str(upgrades),
        ],
    )
    assert main() == 1
    assert "01-rewrite.md" in capsys.readouterr().out
