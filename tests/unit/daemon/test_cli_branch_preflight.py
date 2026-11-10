"""`hooks-daemon branch-preflight` (Plan 00594 Task 4.1): arguments, output and exit codes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.branch_creation import EXIT_CREATION_REFUSED
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_branch_preflight


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _project(tmp_path: Path, branches_yaml: str) -> Path:
    (tmp_path / ".claude" / "hooks-daemon").mkdir(parents=True)
    (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(
        f"version: '2.0'\nbranches:\n  default: main\n{branches_yaml}", encoding="utf-8"
    )
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "remote", "add", "origin", str(tmp_path / "none.git"))
    (tmp_path / "f").write_text("f")
    _git(tmp_path, "add", "f")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "open")
    (tmp_path / "g").write_text("g")
    _git(tmp_path, "add", "g")
    _git(tmp_path, "commit", "-q", "-m", "open work")
    _git(tmp_path, "checkout", "-q", "main")
    return tmp_path


def _run(project: Path, *argv: str) -> int:
    args = build_parser().parse_args(["--project-root", str(project), "branch-preflight", *argv])
    args.project_root = project
    return cmd_branch_preflight(args)


def test_a_clear_repository_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _project(tmp_path, "  wip:\n    cap: 5\n")
    assert _run(project, "fresh") == 0
    assert "may be created" in capsys.readouterr().out


def test_a_full_pool_exits_with_the_named_constant_and_prints_the_fix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path, "  wip:\n    cap: 1\n    mode: block\n    creation_grace: 0\n")
    assert _run(project, "fresh") == EXIT_CREATION_REFUSED
    out = capsys.readouterr().out
    assert RuleID.BRANCH_WIP_CAP in out
    assert "branch-park open --reason" in out


def test_json_lists_each_blocker_with_its_fixes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path, "  wip:\n    cap: 1\n    mode: block\n    creation_grace: 0\n")
    assert _run(project, "--json") == EXIT_CREATION_REFUSED
    document = json.loads(capsys.readouterr().out)
    assert document["may_create"] is False
    [blocker] = document["blockers"]
    assert blocker["rule_id"] == RuleID.BRANCH_WIP_CAP
    assert blocker["refuses"] is True
    assert any("branch-park open --reason" in fix for fix in blocker["fixes"])
    assert blocker["lines"]


def test_a_non_git_directory_is_an_error(tmp_path: Path) -> None:
    (tmp_path / ".claude" / "hooks-daemon").mkdir(parents=True)
    args = build_parser().parse_args(["--project-root", str(tmp_path), "branch-preflight"])
    args.project_root = tmp_path
    assert cmd_branch_preflight(args) == 1
