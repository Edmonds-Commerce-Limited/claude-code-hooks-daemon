"""`hooks-daemon branch-preflight` (Plan 00594 Task 4.1): arguments, output and exit codes."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.branch_cleanup import clean_sweep
from claude_code_hooks_daemon.core.branch_creation import (
    EXIT_CREATION_REFUSED,
    LABELS_RELATIVE_PATH,
    write_labels,
)
from claude_code_hooks_daemon.core.branch_keep import keep_branch
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


def _clone_with_merged_remote_branch(tmp_path: Path) -> tuple[Path, Path, str]:
    """A clone, a merged ``rc/1.0`` held only by the remote, and a second clone to keep it from."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    (work / ".claude" / "hooks-daemon").mkdir(parents=True)
    (work / ".claude" / "hooks-daemon.yaml").write_text(
        "version: '2.0'\nbranches:\n  default: main\n  wip:\n    count_remote: true\n  merged:\n    cap: 10\n    mode: block\n",
        encoding="utf-8",
    )
    (work / "f").write_text("f")
    _git(work, "add", "f")
    _git(work, "commit", "-q", "-m", "base")
    _git(work, "push", "-q", "origin", "main")
    _git(work, "checkout", "-q", "-b", "rc/1.0")
    (work / "g").write_text("g")
    _git(work, "add", "g")
    _git(work, "commit", "-q", "-m", "release candidate")
    tip = _git(work, "rev-parse", "HEAD")
    # A remote-only branch is counted only when its tip is authored by this clone's user
    # (the session's pinned GIT_AUTHOR_EMAIL beats the -c identity above).
    _git(work, "config", "user.email", _git(work, "log", "-1", "--format=%ae"))
    _git(work, "checkout", "-q", "main")
    _git(work, "merge", "-q", "--no-ff", "-m", "merge rc", "rc/1.0")
    _git(work, "push", "-q", "origin", "main", "rc/1.0")
    _git(work, "branch", "-q", "-D", "rc/1.0")
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(origin), str(other))
    return work, other, tip


def _stale_snapshot(work: Path, tip: str) -> None:
    """The labels SessionStart wrote while the keep note was not yet in this clone."""
    write_labels(
        work / LABELS_RELATIVE_PATH,
        [
            {
                "name": "rc/1.0",
                "group": "merged",
                "action": "delete",
                "stale": True,
                "local_tip": None,
                "remote_tip": tip,
            }
        ],
    )


def test_control_a_stale_merged_branch_with_no_keep_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    work, _other, tip = _clone_with_merged_remote_branch(tmp_path)
    _stale_snapshot(work, tip)
    assert _run(work, "fresh") == EXIT_CREATION_REFUSED, capsys.readouterr().out
    assert RuleID.BRANCH_MERGED_POOL in capsys.readouterr().out


def test_a_keep_fetched_by_the_sweep_lifts_the_stale_mark_preflight_reads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The sweep honours a keep written in another clone; preflight kept refusing on the old mark."""
    work, other, tip = _clone_with_merged_remote_branch(tmp_path)
    _stale_snapshot(work, tip)
    keep_branch(
        other,
        [tip],
        reason="clients still run this rc",
        remote="origin",
        user="Tess",
        now=time.time(),
    )
    clean_sweep(
        work,
        Config.load_or_default(work / ".claude" / "hooks-daemon.yaml").branches,
        dry_run=True,
        remote=True,
    )
    assert _run(work, "fresh") == 0, capsys.readouterr().out


def test_a_non_git_directory_is_an_error(tmp_path: Path) -> None:
    (tmp_path / ".claude" / "hooks-daemon").mkdir(parents=True)
    args = build_parser().parse_args(["--project-root", str(tmp_path), "branch-preflight"])
    args.project_root = tmp_path
    assert cmd_branch_preflight(args) == 1
