"""Tests for the Stop and SubagentStop decision (Plan 00558 Task 4.4)."""

from __future__ import annotations

import itertools
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.core import branch_stop_gate
from claude_code_hooks_daemon.core.agent_ownership import RunningHolds, ownership_refusal
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

    def test_line_states_intent_and_the_action_for_each_branch(
        self, repo: Path, untracked: Path, stale: None
    ) -> None:
        decision = _decide(repo, untracked)
        text = "\n".join(decision.context)
        assert BRANCH_LIMIT_PRINCIPLE in text
        assert "branch-park old-idle --reason" in text
        assert "delete-branch old-idle" in text
        assert "merge" in text
        assert "take this work on" in text

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


class TestHandedOverToHarnessWorktrees:
    """A background sub-agent outside the work queue is told by its worktree.

    For a branch the stopping thread did not touch, the harness directory and git's
    lock are the signals ``agent_ownership`` already uses to leave a live agent's
    worktree alone, and the coordinator stop honours them too.
    """

    def _worktree(self, repo: Path, branch: str, where: Path, *, lock: bool = False) -> None:
        _unpushed_branch(repo, branch, agent="sub-1")
        where.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "add", "-q", str(where), branch)
        if lock:
            _git(repo, "worktree", "lock", "--reason", "claude agent", str(where))

    def test_a_locked_harness_worktree_branch_is_handed_over_not_abandoned(
        self, repo: Path, untracked: Path
    ) -> None:
        where = repo / ".claude" / "worktrees" / "agent-abc123"
        self._worktree(repo, "agent-abc123", where, lock=True)
        decisions = [_decide(repo, untracked) for _ in range(MAX_STOP_BLOCKS + 1)]
        for decision in decisions:
            assert decision.reason is None
            assert not any("abandoned at stop" in line for line in decision.context)
        last = decisions[-1]
        assert any("handed over" in line and "agent-abc123" in line for line in last.context)

    def test_a_locked_worktree_branch_is_handed_over(self, repo: Path, untracked: Path) -> None:
        self._worktree(repo, "feat-l", repo.parent / "wt-locked", lock=True)
        decision = _decide(repo, untracked)
        assert decision.reason is None
        assert any("handed over" in line and "feat-l" in line for line in decision.context)

    def test_an_unlocked_harness_worktree_branch_is_handed_over_not_abandoned(
        self, repo: Path, untracked: Path
    ) -> None:
        # Plan 00618 B-2 rework (review F1): a plain `isolation: worktree` sub-agent has
        # no lock and no queue record; judging it spent the coordinator's block budget.
        self._worktree(repo, "agent-abc123", repo / ".claude" / "worktrees" / "agent-abc123")
        decisions = [_decide(repo, untracked) for _ in range(MAX_STOP_BLOCKS + 1)]
        for decision in decisions:
            assert decision.reason is None
            assert not any("abandoned at stop" in line for line in decision.context)
        last = decisions[-1]
        assert any("handed over" in line and "agent-abc123" in line for line in last.context)

    def test_an_ordinary_unlocked_worktree_is_still_held(self, repo: Path, untracked: Path) -> None:
        self._worktree(repo, "feat-p", repo.parent / "wt-plain")
        assert _decide(repo, untracked).reason is not None

    def test_the_sub_agent_itself_is_still_judged(self, repo: Path, untracked: Path) -> None:
        self._worktree(repo, "agent-def456", repo / ".claude" / "worktrees" / "agent-def456")
        config = BranchesConfig.model_validate({"stop_guard": {"unpushed_subagent": "block"}})
        assert _decide(repo, untracked, agent="sub-1", config=config).reason is not None

    def test_an_unlistable_worktree_set_hands_nothing_over(
        self, repo: Path, untracked: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unpushed_branch(repo, "feat-a", agent="sub-1")

        def broken(_repo: Path) -> object:
            raise RuntimeError("git worktree list failed")

        monkeypatch.setattr(branch_stop_gate, "linked_worktree_records", broken)
        assert _decide(repo, untracked).reason is not None


class TestTheSessionsOwnBranchIsHandedOverOnlyOnAHold:
    """Plan 00618 B-2: a branch the stopping thread touched is handed over only on a hold.

    A running work-queue record or a git lock still hands it over, the holds
    ``worktree-reap`` honours. Sitting under the harness's ``.claude/worktrees/``
    directory does not: the stopping thread worked on that branch itself, so it is judged.
    """

    def _own_harness_worktree(self, repo: Path, name: str, *, lock: bool = False) -> Path:
        """The review's reproduction: touched by the main thread, checked out under the
        harness directory, a commit no remote holds and a dirty file."""
        _unpushed_branch(repo, name)
        where = repo / ".claude" / "worktrees" / name
        where.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "add", "-q", str(where), name)
        if lock:
            _git(repo, "worktree", "lock", str(where))
        (where / "work.txt").write_text("more work\n", encoding="utf-8")
        _git(where, "add", "work.txt")
        _git(where, "commit", "-q", "-m", "more work")
        (where / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
        return where

    def test_the_reviewers_reproduction_is_judged(self, repo: Path, untracked: Path) -> None:
        self._own_harness_worktree(repo, "x")
        decision = _decide(repo, untracked)
        assert decision.reason is not None
        assert "x: dirty worktree" in decision.reason
        assert "x: commits no remote holds" in decision.reason
        assert not any("handed over" in line for line in decision.context)

    def test_a_lock_on_its_worktree_hands_it_over(self, repo: Path, untracked: Path) -> None:
        self._own_harness_worktree(repo, "x", lock=True)
        decision = _decide(repo, untracked)
        assert decision.reason is None
        assert _handed(decision) == {"x"}

    def test_a_running_queue_record_hands_it_over(self, repo: Path, untracked: Path) -> None:
        _unpushed_branch(repo, "feat-own")
        _queue(untracked, "feat-own")
        decision = _decide(repo, untracked)
        assert decision.reason is None
        assert _handed(decision) == {"feat-own"}

    def test_a_queue_record_hands_it_over_when_worktrees_cannot_be_listed(
        self, repo: Path, untracked: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unpushed_branch(repo, "feat-own")
        _queue(untracked, "feat-own")

        def broken(_repo: Path) -> object:
            raise RuntimeError("git worktree list failed")

        monkeypatch.setattr(branch_stop_gate, "linked_worktree_records", broken)
        assert _decide(repo, untracked).reason is None

    def test_a_branch_both_threads_touched_under_the_harness_is_judged(
        self, repo: Path, untracked: Path
    ) -> None:
        _unpushed_branch(repo, "feat-both", agent="sub-1")
        _git(repo, "config", "--add", f"branch.feat-both.{TOUCHED_KEY}", f"{SESSION}:")
        where = repo / ".claude" / "worktrees" / "feat-both"
        where.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "add", "-q", str(where), "feat-both")
        decision = _decide(repo, untracked)
        assert decision.reason is not None
        assert "feat-both" in decision.reason

    def test_a_branch_both_threads_touched_with_a_queue_record_is_handed_over(
        self, repo: Path, untracked: Path
    ) -> None:
        _unpushed_branch(repo, "feat-both", agent="sub-1")
        _git(repo, "config", "--add", f"branch.feat-both.{TOUCHED_KEY}", f"{SESSION}:")
        _queue(untracked, "feat-both")
        assert _decide(repo, untracked).reason is None


_HANDED_PREFIX = "Branches handed over to running agents (not abandoned): "


def _handed(decision: StopDecision) -> set[str]:
    """The branch names on the decision's "handed over to running agents" line."""
    for line in decision.context:
        if line.startswith(_HANDED_PREFIX):
            return set(line[len(_HANDED_PREFIX) :].split(", "))
    return set()


def _origin_main_owned(repo: Path, untracked: Path, **_: object) -> frozenset[str]:
    """origin/main's ``_owned_branches`` (before Plan 00618 B-2), the differential baseline."""
    holds = branch_stop_gate.running_holds(untracked, repo)
    try:
        records = branch_stop_gate.linked_worktree_records(repo)
    except RuntimeError:
        return holds.branches
    owned = {
        name
        for name, record in records.items()
        if ownership_refusal(name, record.path, locked=record.locked, holds=holds) is not None
    }
    return holds.branches | owned


def _first_stop(repo: Path, untracked: Path) -> StopDecision:
    """A stop judged with the session's block count cleared first."""
    state_path(untracked, SESSION, STATE_KIND, "main").unlink(missing_ok=True)
    return _decide(repo, untracked)


def _baseline_stop(repo: Path, untracked: Path, monkeypatch: pytest.MonkeyPatch) -> StopDecision:
    """The same stop as origin/main's gate would decide it."""
    with monkeypatch.context() as patch:
        patch.setattr(branch_stop_gate, "_owned_branches", _origin_main_owned)
        return _decide(repo, untracked)


_TOUCHES: dict[str, tuple[str, ...]] = {"sub": ("sub-1",), "main": ("",), "both": ("sub-1", "")}
_PLACES = ("harness", "plain", "none")


def _combinations() -> list[tuple[str, str, bool, bool, bool]]:
    return [
        (touch, place, lock, queued, dirty)
        for touch, place, lock, queued, dirty in itertools.product(
            _TOUCHES, _PLACES, (False, True), (False, True), (False, True)
        )
        if place != "none" or not (lock or dirty)
    ]


class TestDifferentialAgainstOriginMain:
    """Plan 00618 B-2 rework: every stop origin/main refused is still refused, and the
    handed-over set loses only own-touched branches that no queue record or lock holds."""

    @pytest.mark.parametrize(("touch", "place", "lock", "queued", "dirty"), _combinations())
    def test_refusals_are_a_superset_and_only_unheld_own_branches_stop_being_handed_over(
        self,
        repo: Path,
        untracked: Path,
        monkeypatch: pytest.MonkeyPatch,
        touch: str,
        place: str,
        lock: bool,
        queued: bool,
        dirty: bool,
    ) -> None:
        name = "feat-d"
        _unpushed_branch(repo, name, agent=_TOUCHES[touch][0])
        for agent in _TOUCHES[touch][1:]:
            _git(repo, "config", "--add", f"branch.{name}.{TOUCHED_KEY}", f"{SESSION}:{agent}")
        if place != "none":
            parent = repo / ".claude" / "worktrees" if place == "harness" else repo.parent
            where = parent / f"wt-{name}"
            where.parent.mkdir(parents=True, exist_ok=True)
            _git(repo, "worktree", "add", "-q", str(where), name)
            if lock:
                _git(repo, "worktree", "lock", str(where))
            if dirty:
                (where / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
        if queued:
            _queue(untracked, name)

        current = _first_stop(repo, untracked)
        state_path(untracked, SESSION, STATE_KIND, "main").unlink(missing_ok=True)
        baseline = _baseline_stop(repo, untracked, monkeypatch)

        if baseline.reason is not None:
            assert current.reason is not None
        own_touched = "" in _TOUCHES[touch]
        dropped = {name} if own_touched and not queued and not lock else set()
        assert _handed(current) == _handed(baseline) - dropped


class TestReviewScenarioOne:
    """Review F1 (probe_stop.py scenario 1): sub-agent branches cannot spend the budget."""

    def test_sub_agent_stops_block_no_more_than_origin_main_and_own_work_is_still_held(
        self, repo: Path, untracked: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = repo / ".claude" / "worktrees" / "agent-x"
        _unpushed_branch(repo, "agent-x", agent="sub-1")
        agent.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "add", "-q", str(agent), "agent-x")
        baseline_untracked = untracked.parent / "untracked-baseline"
        baseline_untracked.mkdir()
        current: list[StopDecision] = []
        baseline: list[StopDecision] = []
        for stop in range(MAX_STOP_BLOCKS + 2):
            if stop == MAX_STOP_BLOCKS:
                _unpushed_branch(repo, "own-b")
                own = repo.parent / "wt-own-b"
                _git(repo, "worktree", "add", "-q", str(own), "own-b")
                (own / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
            current.append(_decide(repo, untracked))
            baseline.append(_baseline_stop(repo, baseline_untracked, monkeypatch))

        assert [d.reason is not None for d in current] == [d.reason is not None for d in baseline]
        assert [d.reason is not None for d in current] == [False, False, False, True, True]
        for number, decision in enumerate(current[MAX_STOP_BLOCKS:], start=1):
            assert decision.reason is not None
            assert "own-b: dirty worktree" in decision.reason
            assert "agent-x" not in decision.reason
            assert f"Block {number} of {MAX_STOP_BLOCKS}" in decision.reason
        assert all(_handed(decision) == {"agent-x"} for decision in current)
