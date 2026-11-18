"""The stop guard's open-pool checks follow the pool modes and the shared count (Plan 00618 D-1, D-2).

D-1: ``wip.mode`` and ``dormancy.mode`` set to ``warn`` make the stop guard
advise and allow, as the creation guard only warns; ``off`` reports nothing;
``block`` still denies. D-2: open branches on one tip count once at stop time,
as :func:`branch_sweep.open_work_count` counts them.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_ladder, branch_stop_gate
from claude_code_hooks_daemon.core.branch_inventory import DormancyStage, build_inventory
from claude_code_hooks_daemon.core.branch_park import BranchParkError
from claude_code_hooks_daemon.core.branch_records import TOUCHED_KEY
from claude_code_hooks_daemon.core.branch_stop_gate import StopDecision, decide_stop
from claude_code_hooks_daemon.core.branch_stop_guard import StopCheck
from claude_code_hooks_daemon.core.branch_sweep import open_work_count

SESSION = "sess-pool-modes"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


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


@pytest.fixture
def untracked(tmp_path: Path) -> Path:
    path = tmp_path / "untracked"
    path.mkdir()
    return path


def _pushed_branch(repo: Path, name: str, *, message: str, touched: bool = True) -> str:
    """An open branch one commit past main, pushed, optionally touched by this session."""
    _git(repo, "branch", name, "main")
    tree = _git(repo, "rev-parse", f"{name}^{{tree}}").strip()
    parent = _git(repo, "rev-parse", name).strip()
    tip = _git(repo, "commit-tree", tree, "-p", parent, "-m", message).strip()
    _git(repo, "update-ref", f"refs/heads/{name}", tip)
    _git(repo, "push", "-q", "origin", name)
    if touched:
        _git(repo, "config", "--add", f"branch.{name}.{TOUCHED_KEY}", f"{SESSION}:")
    return tip


def _same_tip_branch(repo: Path, name: str, tip: str) -> None:
    """A second open branch at ``tip``, pushed, not touched by this session."""
    _git(repo, "update-ref", f"refs/heads/{name}", tip)
    _git(repo, "push", "-q", "origin", name)


def _config(**sections: Any) -> BranchesConfig:
    return BranchesConfig.model_validate(sections)


def _decide(repo: Path, untracked: Path, config: BranchesConfig) -> StopDecision:
    return decide_stop(
        repo,
        config,
        untracked,
        session_id=SESSION,
        agent_id=None,
        handoff=False,
        now=1_000_000.0,
    )


def _mentions(decision: StopDecision, check: StopCheck) -> bool:
    return any(check.value in line for line in decision.context)


class TestWipModeAtStop:
    """Cap 1, two of the session's own pushed open branches on different tips."""

    @pytest.fixture
    def over_cap(self, repo: Path) -> None:
        _pushed_branch(repo, "work-a", message="a")
        _pushed_branch(repo, "work-b", message="b")

    def test_block_mode_denies_over_cap(self, repo: Path, untracked: Path, over_cap: None) -> None:
        decision = _decide(repo, untracked, _config(wip={"cap": 1, "mode": "block"}))
        assert decision.reason is not None
        assert StopCheck.OVER_CAP.value in decision.reason

    def test_warn_mode_advises_and_allows(
        self, repo: Path, untracked: Path, over_cap: None
    ) -> None:
        decision = _decide(repo, untracked, _config(wip={"cap": 1, "mode": "warn"}))
        assert decision.reason is None
        assert _mentions(decision, StopCheck.OVER_CAP)

    def test_off_mode_allows_without_an_over_cap_line(
        self, repo: Path, untracked: Path, over_cap: None
    ) -> None:
        decision = _decide(repo, untracked, _config(wip={"cap": 1, "mode": "off"}))
        assert decision.reason is None
        assert not _mentions(decision, StopCheck.OVER_CAP)

    def test_warn_mode_still_denies_a_blocking_finding_of_another_check(
        self, repo: Path, untracked: Path, over_cap: None
    ) -> None:
        tip = _git(repo, "rev-parse", "work-a").strip()
        tree = _git(repo, "rev-parse", f"{tip}^{{tree}}").strip()
        local = _git(repo, "commit-tree", tree, "-p", tip, "-m", "unpushed").strip()
        _git(repo, "update-ref", "refs/heads/work-a", local)
        decision = _decide(repo, untracked, _config(wip={"cap": 1, "mode": "warn"}))
        assert decision.reason is not None
        assert StopCheck.UNPUSHED.value in decision.reason
        assert StopCheck.OVER_CAP.value not in decision.reason


class TestDormancyModeAtStop:
    """One own pushed open branch the inventory places at the dormancy block stage."""

    @pytest.fixture
    def dormant(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _pushed_branch(repo, "old-work", message="old")
        real = branch_stop_gate.build_inventory

        def staged(root: Path, config: BranchesConfig) -> object:
            inventory = real(root, config)
            record = inventory.records["old-work"]
            inventory.records["old-work"] = type(record)(
                **{**record.__dict__, "dormancy_stage": DormancyStage.BLOCK}
            )
            return inventory

        monkeypatch.setattr(branch_stop_gate, "build_inventory", staged)

    def test_block_mode_denies_a_dormant_branch(
        self, repo: Path, untracked: Path, dormant: None
    ) -> None:
        decision = _decide(repo, untracked, _config(dormancy={"mode": "block"}))
        assert decision.reason is not None
        assert StopCheck.DORMANT.value in decision.reason

    def test_warn_mode_advises_and_allows(self, repo: Path, untracked: Path, dormant: None) -> None:
        decision = _decide(repo, untracked, _config(dormancy={"mode": "warn"}))
        assert decision.reason is None
        assert _mentions(decision, StopCheck.DORMANT)

    def test_off_mode_allows_without_a_dormant_line(
        self, repo: Path, untracked: Path, dormant: None
    ) -> None:
        decision = _decide(repo, untracked, _config(dormancy={"mode": "off"}))
        assert decision.reason is None
        assert not _mentions(decision, StopCheck.DORMANT)


class TestSameTipCountsOnceAtStop:
    def test_two_names_on_one_pushed_tip_are_one_open_branch(
        self, repo: Path, untracked: Path
    ) -> None:
        tip = _pushed_branch(repo, "a", message="a")
        _same_tip_branch(repo, "a2", tip)
        config = _config(wip={"cap": 1, "mode": "block"})
        assert open_work_count(build_inventory(repo, config)) == 1
        decision = _decide(repo, untracked, config)
        assert decision.reason is None
        assert not _mentions(decision, StopCheck.OVER_CAP)

    def test_distinct_tips_over_cap_still_deny(self, repo: Path, untracked: Path) -> None:
        tip = _pushed_branch(repo, "a", message="a")
        _same_tip_branch(repo, "a2", tip)
        _pushed_branch(repo, "b", message="b", touched=False)
        config = _config(wip={"cap": 1, "mode": "block"})
        assert open_work_count(build_inventory(repo, config)) == 2
        decision = _decide(repo, untracked, config)
        assert decision.reason is not None
        assert StopCheck.OVER_CAP.value in decision.reason


class TestLadderAtStop:
    """Plan 00619 Task 1.3: the stop report carries the ladder, and never holds a stop by it."""

    def test_a_pool_at_the_warn_level_is_reported_and_the_stop_is_allowed(
        self, repo: Path, untracked: Path
    ) -> None:
        _pushed_branch(repo, "work-a", message="a")
        _pushed_branch(repo, "work-b", message="b")
        decision = _decide(repo, untracked, _config(wip={"cap": 3, "creation_grace": 0}))
        assert decision.reason is None
        text = "\n".join(decision.context)
        assert "BRANCH POOL WARNING" in text
        assert "2 of 3" in text

    def test_silent_below_the_warn_level(self, repo: Path, untracked: Path) -> None:
        _pushed_branch(repo, "work-a", message="a")
        decision = _decide(repo, untracked, _config(wip={"cap": 10}))
        assert "BRANCH POOL" not in "\n".join(decision.context)

    def test_a_failed_ladder_read_never_loosens_a_held_stop(
        self, repo: Path, untracked: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ladder's own read failing must leave the stop decision, and its counter, alone."""

        def boom(*_args: object, **_kwargs: object) -> object:
            raise BranchParkError("git config --get-regexp failed: timed out")

        monkeypatch.setattr(branch_ladder, "work_pools", boom)
        _pushed_branch(repo, "work-a", message="a")
        _pushed_branch(repo, "work-b", message="b")
        decision = _decide(repo, untracked, _config(wip={"cap": 1, "mode": "block"}))
        assert decision.reason is not None
        assert StopCheck.OVER_CAP.value in decision.reason
        written = [p for p in untracked.rglob("*") if p.is_file()]
        assert written, "the block counter must still be persisted"
        assert "BRANCH POOL" not in "\n".join(decision.context)

    def test_the_ladder_ages_use_the_injected_clock(self, repo: Path, untracked: Path) -> None:
        _pushed_branch(repo, "work-a", message="a")
        _pushed_branch(repo, "work-b", message="b")
        decision = decide_stop(
            repo,
            _config(wip={"cap": 3, "creation_grace": 0}),
            untracked,
            session_id=SESSION,
            agent_id=None,
            handoff=False,
            now=time.time() + 5 * 86_400,
        )
        assert "(5d old)" in "\n".join(decision.context)

    def test_a_subagent_stop_is_not_given_the_ladder(self, repo: Path, untracked: Path) -> None:
        _pushed_branch(repo, "work-a", message="a")
        _pushed_branch(repo, "work-b", message="b")
        decision = decide_stop(
            repo,
            _config(wip={"cap": 3, "creation_grace": 0}),
            untracked,
            session_id=SESSION,
            agent_id="agent-1",
            handoff=False,
            now=1_000_000.0,
        )
        assert "BRANCH POOL" not in "\n".join(decision.context)
