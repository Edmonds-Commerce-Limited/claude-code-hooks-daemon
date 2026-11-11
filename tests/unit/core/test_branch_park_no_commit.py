"""A park with no trailer commit and/or no push (Plan 00594, client report).

The park record in git config is the park; the trailer commit and the push are
optional extras. The record is written before any push, the inventory and the
pools read it, and the stop guards treat a standing record as handed over.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.branch_creation import creation_verdict
from claude_code_hooks_daemon.core.branch_inventory import BranchState, Pool, build_inventory
from claude_code_hooks_daemon.core.branch_park import (
    BranchParkError,
    BranchParkSameReason,
    announce_ended_parks,
    park_branch,
    read_park_record,
)
from claude_code_hooks_daemon.core.branch_records import TOUCHED_KEY
from claude_code_hooks_daemon.core.branch_stop_gate import StopDecision, decide_stop
from claude_code_hooks_daemon.core.branch_sweep import open_work_count, pool_count
from tests.support.git_fixtures import git_setup_timeout

_REASON = "waiting on a full-QA verdict"
_SESSION = "sess-1"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=git_setup_timeout(),
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(bare)],
        check=True,
        timeout=git_setup_timeout(),
    )
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Tess")
    (root / ".git" / "info" / "exclude").write_text("untracked/\n")
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _git(root, "push", "-q", "-u", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    _git(root, "checkout", "-q", "-b", "work")
    (root / "f.txt").write_text("x")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-q", "-m", "work")
    _git(root, "checkout", "-q", "main")
    _git(root, "config", "--add", f"branch.work.{TOUCHED_KEY}", f"{_SESSION}:agent-1")
    return root


def _remote_has(repo: Path, name: str) -> bool:
    out = _git(repo, "ls-remote", "--heads", "origin", name)
    return bool(out)


class TestNoCommitPark:
    def test_leaves_the_tip_alone_and_records_the_park(self, repo: Path) -> None:
        tip = _git(repo, "rev-parse", "work")
        result = park_branch(repo, "work", reason=_REASON, remote="origin", commit=False)
        assert _git(repo, "rev-parse", "work") == tip
        assert result.sha == tip
        assert result.pushed is False
        assert result.local_only is True
        record = read_park_record(repo, "work")
        assert record is not None and record.sha == tip and record.reason == _REASON

    def test_never_pushes(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin", commit=False, push=True)
        assert not _remote_has(repo, "work")

    def test_a_same_reason_repark_is_refused(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin", commit=False)
        with pytest.raises(BranchParkSameReason):
            park_branch(repo, "work", reason=_REASON, remote="origin", commit=False)

    def test_a_new_reason_replaces_the_record(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin", commit=False)
        park_branch(repo, "work", reason="still waiting", remote="origin", commit=False)
        record = read_park_record(repo, "work")
        assert record is not None and record.reason == "still waiting"

    def test_a_remote_only_branch_cannot_be_parked_without_a_commit(self, repo: Path) -> None:
        _git(repo, "update-ref", "refs/remotes/origin/ghost", _git(repo, "rev-parse", "work"))
        with pytest.raises(BranchParkError, match="local branch"):
            park_branch(repo, "ghost", reason=_REASON, remote="origin", commit=False)

    def test_clear_drops_the_record_without_a_commit(self, repo: Path) -> None:
        tip = _git(repo, "rev-parse", "work")
        park_branch(repo, "work", reason=_REASON, remote="origin", commit=False)
        result = park_branch(repo, "work", reason=None, remote="origin", clear=True)
        assert read_park_record(repo, "work") is None
        assert _git(repo, "rev-parse", "work") == tip
        assert result.local_only is True

    def test_new_work_ends_the_park(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin", commit=False)
        _git(repo, "checkout", "-q", "work")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "more")
        _git(repo, "checkout", "-q", "main")
        assert announce_ended_parks(repo) == [f"Park cleared: work ({_REASON})"]


class TestNoPushPark:
    def test_commits_but_does_not_push(self, repo: Path) -> None:
        before = _git(repo, "rev-parse", "work")
        result = park_branch(repo, "work", reason=_REASON, remote="origin", push=False)
        assert result.sha != before
        assert _git(repo, "rev-parse", "work") == result.sha
        assert "Parked-Reason: " + _REASON in _git(repo, "log", "-1", "--format=%B", "work")
        assert result.pushed is False and result.local_only is True
        assert result.push_error is None and result.retry_command is None
        assert not _remote_has(repo, "work")
        assert read_park_record(repo, "work") is not None

    def test_the_default_still_commits_and_pushes(self, repo: Path) -> None:
        result = park_branch(repo, "work", reason=_REASON, remote="origin")
        assert result.pushed is True and result.local_only is False
        assert _remote_has(repo, "work")


class TestInventoryAndPools:
    def test_a_no_commit_park_is_parked_not_open(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin", commit=False)
        config = BranchesConfig(default="main")
        inventory = build_inventory(repo, config)
        record = inventory.records["work"]
        assert record.state == BranchState.PARKED
        assert record.parked_reason == _REASON
        assert open_work_count(inventory) == 0
        assert pool_count(inventory, Pool.PARKED) == 1

    def test_parked_counts_against_the_parked_pool_in_the_creation_guard(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin", commit=False)
        config = BranchesConfig.model_validate(
            {
                "default": "main",
                "wip": {"cap": 1, "mode": "block", "creation_grace": 0},
                "parked": {"cap": 1},
                "duplicates": {"mode": "off"},
            }
        )
        verdict = creation_verdict(repo, config, "fresh")
        assert verdict.decision == "deny"
        assert any("Parked branches: 1" in line for line in verdict.lines)

    def test_new_work_returns_the_branch_to_open(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin", commit=False)
        _git(repo, "checkout", "-q", "work")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "more")
        _git(repo, "checkout", "-q", "main")
        inventory = build_inventory(repo, BranchesConfig(default="main"))
        assert inventory.records["work"].state != BranchState.PARKED


def _stop(repo: Path, untracked: Path, agent: str | None) -> StopDecision:
    return decide_stop(
        repo,
        BranchesConfig(),
        untracked,
        session_id=_SESSION,
        agent_id=agent,
        handoff=False,
        now=1_000_000.0,
    )


class TestStopGuard:
    def test_an_unparked_unpushed_branch_is_held(self, repo: Path, tmp_path: Path) -> None:
        decision = _stop(repo, tmp_path, "agent-1")
        assert decision.reason is not None or decision.context

    def test_a_no_commit_park_is_handed_over(self, repo: Path, tmp_path: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin", commit=False)
        for agent in ("agent-1", None):
            decision = _stop(repo, tmp_path, agent)
            assert decision.reason is None
            assert decision.context == ()

    def test_a_park_with_commit_and_no_push_is_handed_over(
        self, repo: Path, tmp_path: Path
    ) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin", push=False)
        decision = _stop(repo, tmp_path, "agent-1")
        assert decision.reason is None and decision.context == ()

    def test_work_after_the_park_is_held_again(self, repo: Path, tmp_path: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin", commit=False)
        _git(repo, "checkout", "-q", "work")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "more")
        _git(repo, "checkout", "-q", "main")
        decision = _stop(repo, tmp_path, "agent-1")
        assert decision.reason is not None or decision.context


class TestParkConfig:
    def test_defaults_keep_current_behaviour(self) -> None:
        config = BranchesConfig()
        assert config.park.commit is True
        assert config.park.push is True

    def test_unknown_keys_are_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            BranchesConfig.model_validate({"park": {"bogus": 1}})
