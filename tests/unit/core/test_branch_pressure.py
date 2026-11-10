"""Where branch-pool pressure lands (Plan 00594 Task 4.2, DESIGN.md section 2.3).

Creation is a backstop (cap + ``wip.creation_grace``), the stop gate judges only
the stopping session's own touched open branches, and no deny offers a rename
or the deletion of a foreign branch.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Final

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.branch_creation import creation_report, creation_verdict
from claude_code_hooks_daemon.core.branch_records import TOUCHED_KEY
from claude_code_hooks_daemon.core.branch_stop_gate import StopDecision, decide_stop

SESSION: Final[str] = "sess-1"
DAY: Final[int] = 86_400
FOUR: Final[tuple[str, ...]] = ("one", "two", "three", "four")


def _git(repo: Path, *args: str, days_ago: float = 0) -> str:
    stamp = f"@{int(time.time() - days_ago * DAY)} +0000"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(remote), str(root))
    (root / ".git" / "info" / "exclude").write_text("untracked/\n")
    _git(root, "checkout", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root", days_ago=500)
    _git(root, "push", "-q", "-u", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    return root


@pytest.fixture
def untracked(tmp_path: Path) -> Path:
    path = tmp_path / "untracked"
    path.mkdir()
    return path


def _open(repo: Path, name: str, *, days_ago: float = 1, touched: bool = False) -> None:
    """An open, pushed work branch (one commit that changes a file)."""
    _git(repo, "checkout", "-q", "-b", name, "main")
    (repo / f"{name}.txt").write_text(name)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", name, days_ago=days_ago)
    _git(repo, "push", "-q", "origin", name)
    _git(repo, "checkout", "-q", "main")
    if touched:
        _git(repo, "config", "--add", f"branch.{name}.{TOUCHED_KEY}", f"{SESSION}:")


def _config(cap: int, wip: dict[str, Any] | None = None, **extra: Any) -> BranchesConfig:
    return BranchesConfig.model_validate(
        {
            "default": "main",
            "wip": {"cap": cap, "mode": "block", **(wip or {})},
            "duplicates": {"mode": "off"},
            **extra,
        }
    )


def _stop(repo: Path, untracked: Path, config: BranchesConfig) -> StopDecision:
    return decide_stop(
        repo,
        config,
        untracked,
        session_id=SESSION,
        agent_id=None,
        handoff=False,
        now=time.time(),
    )


class TestCreationGraceConfig:
    def test_default_is_two(self) -> None:
        assert BranchesConfig().wip.creation_grace == 2

    def test_zero_is_allowed(self) -> None:
        assert _config(1, {"creation_grace": 0}).wip.creation_grace == 0

    def test_negative_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _config(1, {"creation_grace": -1})


class TestCreationIsABackstop:
    def test_at_the_cap_creation_is_not_denied(self, repo: Path) -> None:
        for name in ("one", "two"):
            _open(repo, name)
        verdict = creation_verdict(repo, _config(2), "fresh")
        assert verdict.decision == "warn"
        assert any("cap 2" in line for line in verdict.lines)

    def test_at_cap_plus_grace_creation_is_denied(self, repo: Path) -> None:
        for name in FOUR:
            _open(repo, name)
        verdict = creation_verdict(repo, _config(2), "fresh")
        assert verdict.decision == "deny"
        assert verdict.rule_id == RuleID.BRANCH_WIP_CAP

    def test_grace_zero_restores_the_old_cap_deny(self, repo: Path) -> None:
        for name in ("one", "two"):
            _open(repo, name)
        verdict = creation_verdict(repo, _config(2, {"creation_grace": 0}), "fresh")
        assert verdict.decision == "deny"

    def test_grace_widens_the_backstop(self, repo: Path) -> None:
        for name in FOUR:
            _open(repo, name)
        verdict = creation_verdict(repo, _config(2, {"creation_grace": 5}), "fresh")
        assert verdict.decision == "warn"

    def test_warn_mode_never_denies_even_past_the_backstop(self, repo: Path) -> None:
        for name in FOUR:
            _open(repo, name)
        verdict = creation_verdict(repo, _config(2, {"mode": "warn"}), "fresh")
        assert verdict.decision == "warn"

    def test_the_report_still_lists_the_cap_below_the_backstop(self, repo: Path) -> None:
        for name in ("one", "two"):
            _open(repo, name)
        report = creation_report(repo, _config(2), "fresh")
        assert [b.rule_id for b in report.blockers] == [RuleID.BRANCH_WIP_CAP]
        assert report.blockers[0].refuses is False
        assert report.may_create is True

    def test_other_pools_still_deny_at_their_cap(self, repo: Path) -> None:
        _git(repo, "branch", "done", "main")
        verdict = creation_verdict(repo, _config(50, merged={"cap": 1}), "fresh")
        assert verdict.decision == "deny"
        assert verdict.rule_id == RuleID.BRANCH_MERGED_POOL

    def test_the_cap_deny_offers_neither_rename_nor_foreign_delete(self, repo: Path) -> None:
        for name in FOUR:
            _open(repo, name)
        text = "\n".join(creation_verdict(repo, _config(2), "fresh").lines).lower()
        assert "rename" not in text
        assert "branch -m" not in text
        assert "foreign" not in text


class TestStopJudgesOwnOpenBranches:
    def test_own_branch_in_an_over_cap_pool_denies(self, repo: Path, untracked: Path) -> None:
        _open(repo, "mine", touched=True)
        _open(repo, "theirs")
        decision = _stop(repo, untracked, _config(1))
        assert decision.reason is not None
        assert "mine" in decision.reason
        assert "open pool over cap" in decision.reason
        assert "theirs" not in decision.reason

    def test_a_pool_at_the_cap_is_not_over_it(self, repo: Path, untracked: Path) -> None:
        _open(repo, "mine", touched=True)
        _open(repo, "theirs")
        assert _stop(repo, untracked, _config(2)).reason is None

    def test_over_cap_with_nothing_touched_by_this_session_allows(
        self, repo: Path, untracked: Path
    ) -> None:
        _open(repo, "theirs")
        _open(repo, "others")
        decision = _stop(repo, untracked, _config(1))
        assert decision.reason is None
        assert decision.context == ()

    def test_own_dormant_branch_denies(self, repo: Path, untracked: Path) -> None:
        _open(repo, "stale", days_ago=400, touched=True)
        decision = _stop(repo, untracked, _config(50))
        assert decision.reason is not None
        assert "stale" in decision.reason
        assert "dormant" in decision.reason
        assert "branch-park" in decision.reason

    def test_a_foreign_dormant_branch_does_not_deny(self, repo: Path, untracked: Path) -> None:
        _open(repo, "stale", days_ago=400)
        assert _stop(repo, untracked, _config(50)).reason is None

    def test_warn_mode_gives_context_only(self, repo: Path, untracked: Path) -> None:
        _open(repo, "mine", touched=True)
        _open(repo, "theirs")
        config = _config(1, stop_guard={"mode": "warn"})
        decision = _stop(repo, untracked, config)
        assert decision.reason is None
        assert any("mine" in line and "over cap" in line for line in decision.context)

    def test_wip_mode_off_never_counts_the_cap(self, repo: Path, untracked: Path) -> None:
        _open(repo, "mine", touched=True)
        _open(repo, "theirs")
        assert _stop(repo, untracked, _config(1, {"mode": "off"})).reason is None

    def test_the_deny_offers_neither_rename_nor_foreign_delete(
        self, repo: Path, untracked: Path
    ) -> None:
        _open(repo, "mine", touched=True)
        _open(repo, "theirs")
        reason = (_stop(repo, untracked, _config(1)).reason or "").lower()
        assert "rename" not in reason
        assert "branch -m" not in reason
        assert "delete-branch theirs" not in reason
