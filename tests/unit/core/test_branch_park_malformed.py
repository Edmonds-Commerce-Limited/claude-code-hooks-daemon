"""A malformed park record never fails open in any guard (Plan 00618 N-1).

The record carries ``ParkedAt=notanint``. Each consumer of the record must end at
least as strict as a branch with no record at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.branch_creation import creation_verdict
from claude_code_hooks_daemon.core.branch_inventory import BranchState, build_inventory
from claude_code_hooks_daemon.core.branch_park import (
    announce_ended_parks,
    clear_park_record,
    read_park_record,
)
from claude_code_hooks_daemon.core.branch_records import TOUCHED_KEY
from claude_code_hooks_daemon.core.branch_stop_guard import StopCheck, judge_stop

SESSION = "sess-1"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(remote), str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / ".git" / "info" / "exclude").write_text("untracked/\n")
    _git(root, "checkout", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _git(root, "push", "-q", "-u", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    return root


def _malformed_park(repo: Path, name: str) -> str:
    """An unpushed branch whose park record has an unparsable ``ParkedAt``."""
    _git(repo, "checkout", "-q", "-b", name)
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"work on {name}")
    tip = _git(repo, "rev-parse", name)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "config", f"branch.{name}.hooksDaemonParked", tip)
    _git(repo, "config", f"branch.{name}.hooksDaemonParkedReason", "waiting")
    _git(repo, "config", f"branch.{name}.hooksDaemonParkedAt", "notanint")
    _git(repo, "config", f"branch.{name}.hooksDaemonParkedBy", "t")
    return tip


def test_read_is_no_record_not_a_value_error(repo: Path) -> None:
    _malformed_park(repo, "feat")
    assert read_park_record(repo, "feat") is None


def test_creation_guard_still_counts_the_branch_and_does_not_raise(repo: Path) -> None:
    _malformed_park(repo, "feat")
    cfg = BranchesConfig(default="main")
    verdict = creation_verdict(repo, cfg, "newb")
    # The unreadable record is not a park: the branch is open work, never waved through.
    assert verdict.report.open_work_count == 1


def test_stop_guard_still_judges_the_branch(repo: Path) -> None:
    _malformed_park(repo, "feat")
    _git(repo, "config", "--add", f"branch.feat.{TOUCHED_KEY}", f"{SESSION}:")
    cfg = BranchesConfig(default="main")
    judgement = judge_stop(
        repo,
        build_inventory(repo, cfg),
        cfg,
        session_id=SESSION,
        agent_id=None,
        handoff=False,
    )
    assert {(f.branch, f.check) for f in judgement.findings} == {("feat", StopCheck.UNPUSHED)}


def test_session_start_announce_does_not_raise(repo: Path) -> None:
    _malformed_park(repo, "feat")
    assert announce_ended_parks(repo) == []


def test_inventory_judges_the_branch_as_unparked(repo: Path) -> None:
    _malformed_park(repo, "feat")
    inventory = build_inventory(repo, BranchesConfig(default="main"))
    assert inventory.records["feat"].state != BranchState.PARKED


def test_clear_is_a_no_op_not_a_crash(repo: Path) -> None:
    _malformed_park(repo, "feat")
    assert clear_park_record(repo, "feat") is None
