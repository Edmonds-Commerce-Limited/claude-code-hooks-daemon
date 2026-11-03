"""Tests for the Stop and SubagentStop decision (Plan 00558 Task 4.4)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.core.branch_inventory import DormancyStage
from claude_code_hooks_daemon.core.branch_records import TOUCHED_KEY
from claude_code_hooks_daemon.core.branch_stop_gate import (
    MAX_STOP_BLOCKS,
    NOISY_INTERVAL_SECONDS,
    STATE_KIND,
    StopDecision,
    decide_stop,
)
from claude_code_hooks_daemon.utils.spend_ledger import read_state, state_path

SESSION = "sess-1"
AGENT = "agent-1"


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


def _unpushed_branch(repo: Path, name: str, agent: str = "") -> None:
    _git(repo, "branch", name, "main")
    tree = _git(repo, "rev-parse", f"{name}^{{tree}}").strip()
    parent = _git(repo, "rev-parse", name).strip()
    tip = _git(repo, "commit-tree", tree, "-p", parent, "-m", "work").strip()
    _git(repo, "update-ref", f"refs/heads/{name}", tip)
    _git(repo, "config", "--add", f"branch.{name}.{TOUCHED_KEY}", f"{SESSION}:{agent}")


def _decide(
    repo: Path,
    untracked: Path,
    *,
    agent: str | None = None,
    handoff: bool = False,
    config: BranchesConfig | None = None,
    now: float = 1_000_000.0,
) -> StopDecision:
    return decide_stop(
        repo,
        config or BranchesConfig(),
        untracked,
        session_id=SESSION,
        agent_id=agent,
        handoff=handoff,
        now=now,
    )


class TestBlocking:
    def test_clean_repo_allows_silently(self, repo: Path, untracked: Path) -> None:
        decision = _decide(repo, untracked)
        assert decision.reason is None
        assert decision.context == ()

    def test_unpushed_branch_denies_naming_branch_check_and_commands(
        self, repo: Path, untracked: Path
    ) -> None:
        _unpushed_branch(repo, "feat-a")
        decision = _decide(repo, untracked)
        assert decision.reason is not None
        assert "feat-a" in decision.reason
        assert "commits no remote holds" in decision.reason
        assert "git push" in decision.reason
        assert BRANCH_LIMIT_PRINCIPLE in decision.reason

    def test_gives_way_after_max_blocks_and_records_abandoned(
        self, repo: Path, untracked: Path
    ) -> None:
        _unpushed_branch(repo, "feat-a")
        for _ in range(MAX_STOP_BLOCKS):
            assert _decide(repo, untracked).reason is not None
        decision = _decide(repo, untracked)
        assert decision.reason is None
        assert any("abandoned" in line and "feat-a" in line for line in decision.context)
        state = read_state(state_path(untracked, SESSION, STATE_KIND, "main"))
        assert state["abandoned"] == ["feat-a"]

    def test_warn_mode_allows_with_context(self, repo: Path, untracked: Path) -> None:
        _unpushed_branch(repo, "feat-a")
        config = BranchesConfig.model_validate({"stop_guard": {"mode": "warn"}})
        decision = _decide(repo, untracked, config=config)
        assert decision.reason is None
        assert any("feat-a" in line for line in decision.context)

    def test_off_mode_allows_silently(self, repo: Path, untracked: Path) -> None:
        _unpushed_branch(repo, "feat-a")
        config = BranchesConfig.model_validate({"stop_guard": {"mode": "off"}})
        assert _decide(repo, untracked, config=config) == StopDecision(None, ())

    def test_release_in_progress_allows(self, repo: Path, untracked: Path) -> None:
        _unpushed_branch(repo, "feat-a")
        (untracked / "release-state.json").write_text("{}")
        assert _decide(repo, untracked) == StopDecision(None, ())

    def test_not_a_repository_allows(self, tmp_path: Path, untracked: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert _decide(plain, untracked).reason is None

    def test_subagent_unpushed_advise_goes_to_context(self, repo: Path, untracked: Path) -> None:
        _unpushed_branch(repo, "feat-a")
        config = BranchesConfig.model_validate({"stop_guard": {"unpushed_subagent": "advise"}})
        decision = _decide(repo, untracked, config=config)
        assert decision.reason is None or "feat-a" in decision.reason

    def test_handoff_appends_branch_and_tip(self, repo: Path, untracked: Path) -> None:
        _unpushed_branch(repo, "feat-a", AGENT)
        tip = _git(repo, "rev-parse", "feat-a").strip()
        decision = _decide(repo, untracked, agent=AGENT, handoff=True)
        assert decision.reason is not None
        assert "feat-a" in decision.reason
        assert tip in decision.reason

    def test_subagent_block_count_is_per_agent(self, repo: Path, untracked: Path) -> None:
        _unpushed_branch(repo, "feat-a", AGENT)
        _decide(repo, untracked, agent=AGENT)
        main_state = read_state(state_path(untracked, SESSION, STATE_KIND, "main"))
        agent_state = read_state(state_path(untracked, SESSION, STATE_KIND, AGENT))
        assert main_state == {}
        assert agent_state["blocks"] == 1


class TestNoisyLine:
    @pytest.fixture
    def stale(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from claude_code_hooks_daemon.core import branch_stop_gate

        _git(repo, "branch", "old-idle", "main")
        real = branch_stop_gate.build_inventory

        def staged(root: Path, config: BranchesConfig) -> object:
            inventory = real(root, config)
            record = inventory.records["old-idle"]
            inventory.records["old-idle"] = type(record)(
                **{**record.__dict__, "dormancy_stage": DormancyStage.NOISY}
            )
            return inventory

        monkeypatch.setattr(branch_stop_gate, "build_inventory", staged)

    def test_main_thread_stop_lists_noisy_branches(
        self, repo: Path, untracked: Path, stale: None
    ) -> None:
        decision = _decide(repo, untracked)
        assert any("old-idle" in line for line in decision.context)

    def test_at_most_once_per_hour(self, repo: Path, untracked: Path, stale: None) -> None:
        _decide(repo, untracked, now=1_000_000.0)
        again = _decide(repo, untracked, now=1_000_000.0 + NOISY_INTERVAL_SECONDS - 1)
        assert again.context == ()
        later = _decide(repo, untracked, now=1_000_000.0 + NOISY_INTERVAL_SECONDS + 1)
        assert any("old-idle" in line for line in later.context)

    def test_subagent_stop_has_no_noisy_line(
        self, repo: Path, untracked: Path, stale: None
    ) -> None:
        assert _decide(repo, untracked, agent=AGENT).context == ()
