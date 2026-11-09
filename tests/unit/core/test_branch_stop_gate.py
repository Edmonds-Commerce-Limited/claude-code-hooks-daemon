"""Tests for the Stop and SubagentStop decision (Plan 00558 Task 4.4)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.core import branch_stop_gate
from claude_code_hooks_daemon.core.agent_ownership import RunningHolds
from claude_code_hooks_daemon.core.branch_cleanup import sweep_clean_command
from claude_code_hooks_daemon.core.branch_inventory import DormancyStage
from claude_code_hooks_daemon.core.branch_records import TOUCHED_KEY
from claude_code_hooks_daemon.core.branch_stop_gate import (
    MAX_STOP_BLOCKS,
    NOISY_INTERVAL_SECONDS,
    STATE_KIND,
    StopDecision,
    _deny_reason,
    decide_stop,
)
from claude_code_hooks_daemon.core.branch_stop_guard import StopCheck, StopFinding
from claude_code_hooks_daemon.utils.spend_ledger import read_state, state_path
from claude_code_hooks_daemon.utils.work_queue import (
    WORK_QUEUE_FILENAME,
    add_record,
    update_record,
)

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


class TestMergedOneStep:
    """A merged finding names ``branch-sweep --clean`` (Plan 00571 Task 2.3, #165)."""

    def _finding(self, check: StopCheck, *, on_remote: bool = False) -> StopFinding:
        return StopFinding("done", check, "a" * 40, ("git branch -d done",), on_remote=on_remote)

    def test_a_merged_finding_names_the_clean_command(self) -> None:
        reason = _deny_reason([self._finding(StopCheck.MERGED)], {}, block=1, handoff=False)
        assert sweep_clean_command() in reason
        assert "--remote" not in reason
        assert "git branch -d done" in reason

    def test_a_remote_copy_adds_the_remote_flag(self) -> None:
        finding = self._finding(StopCheck.MERGED, on_remote=True)
        reason = _deny_reason([finding], {}, block=1, handoff=False)
        assert sweep_clean_command(remote=True) in reason

    def test_no_merged_finding_no_clean_line(self) -> None:
        reason = _deny_reason([self._finding(StopCheck.UNPUSHED)], {}, block=1, handoff=False)
        assert "--clean" not in reason


def _queue(untracked: Path, branch: str, *, status: str = "running") -> None:
    path = untracked / WORK_QUEUE_FILENAME
    add_record(
        path,
        f"agent-for-{branch}",
        worktree=f"/wt/{branch}",
        branch=branch,
        brief="work",
        brief_file=None,
        last_sha="a" * 40,
        now=1.0,
    )
    if status != "running":
        update_record(path, f"agent-for-{branch}", status=status, now=2.0)


class TestHandedOverToTheWorkQueue:
    """A branch a running work-queue agent owns is handed over (Plan 00571 Task 2.5, N581)."""

    def test_the_coordinator_is_not_held_on_a_running_agents_branch(
        self, repo: Path, untracked: Path
    ) -> None:
        _unpushed_branch(repo, "feat-a", agent="sub-1")
        _queue(untracked, "feat-a")
        decisions = [_decide(repo, untracked) for _ in range(MAX_STOP_BLOCKS + 1)]
        for decision in decisions:
            assert decision.reason is None
            assert not any("abandoned at stop" in line for line in decision.context)
        last = decisions[-1]
        assert any("handed over" in line and "feat-a" in line for line in last.context)

    def test_a_finished_record_hands_nothing_over(self, repo: Path, untracked: Path) -> None:
        _unpushed_branch(repo, "feat-a", agent="sub-1")
        _queue(untracked, "feat-a", status="done")
        assert _decide(repo, untracked).reason is not None

    def test_the_sub_agent_itself_is_still_judged(self, repo: Path, untracked: Path) -> None:
        _unpushed_branch(repo, "feat-a", agent="sub-1")
        _queue(untracked, "feat-a")
        config = BranchesConfig.model_validate({"stop_guard": {"unpushed_subagent": "block"}})
        assert _decide(repo, untracked, agent="sub-1", config=config).reason is not None

    def test_a_running_worktree_hold_hands_its_branch_over_in_any_path_spelling(
        self, repo: Path, untracked: Path
    ) -> None:
        # Plan 00571 Task 2.7: the gate honours the same holds as running_holds, so a
        # record naming the WORKTREE (relative, trailing separator) hands over the
        # branch checked out there even when the record's branch field differs.
        _unpushed_branch(repo, "feat-b", agent="sub-1")
        _git(repo, "worktree", "add", "-q", str(repo.parent / "wt-feat-b"), "feat-b")
        add_record(
            untracked / WORK_QUEUE_FILENAME,
            "agent-for-wt",
            worktree="../wt-feat-b/",
            branch="renamed-since",
            brief="work",
            brief_file=None,
            last_sha="a" * 40,
            now=1.0,
        )
        decision = _decide(repo, untracked)
        assert decision.reason is None
        assert any("handed over" in line and "feat-b" in line for line in decision.context)

    def test_the_gate_delegates_to_running_holds(
        self, repo: Path, untracked: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unpushed_branch(repo, "feat-a", agent="sub-1")
        seen: list[tuple[Path, Path | None]] = []

        def holds(where: Path, project_root: Path | None = None) -> RunningHolds:
            seen.append((where, project_root))
            return RunningHolds(frozenset({"feat-a"}), frozenset())

        monkeypatch.setattr(branch_stop_gate, "running_holds", holds)
        assert _decide(repo, untracked).reason is None
        assert seen == [(untracked, repo)]

    def test_an_unreadable_queue_hands_nothing_over(self, repo: Path, untracked: Path) -> None:
        _unpushed_branch(repo, "feat-a", agent="sub-1")
        (untracked / WORK_QUEUE_FILENAME).write_text("not json", encoding="utf-8")
        assert _decide(repo, untracked).reason is not None
