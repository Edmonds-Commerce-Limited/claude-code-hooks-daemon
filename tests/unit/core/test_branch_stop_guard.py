"""Tests for the Stop and SubagentStop branch judgement (Plan 00558 Task 4.4)."""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.branch_inventory import build_inventory
from claude_code_hooks_daemon.core.branch_records import TOUCHED_KEY, touched_by_session
from claude_code_hooks_daemon.core.branch_stop_guard import (
    StopCheck,
    StopJudgement,
    judge_stop,
)

SESSION = "sess-1"
AGENT = "agent-1"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _touch(repo: Path, branch: str, agent: str = "") -> None:
    _git(repo, "config", "--add", f"branch.{branch}.{TOUCHED_KEY}", f"{SESSION}:{agent}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(remote), str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    # The inventory cache lives under untracked/, which a real checkout ignores.
    (root / ".git" / "info" / "exclude").write_text("untracked/\n")
    _git(root, "checkout", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _git(root, "push", "-q", "-u", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    return root


def _branch(repo: Path, name: str, *, push: bool = False, commit: bool = True) -> None:
    _git(repo, "branch", name, "main")
    if commit:
        tree = tmp_commit(repo, name)
        _git(repo, "update-ref", f"refs/heads/{name}", tree)
    if push:
        _git(repo, "push", "-q", "origin", name)


def tmp_commit(repo: Path, name: str) -> str:
    """A commit on top of ``name`` with an empty tree change (empty commit)."""
    tree = _git(repo, "rev-parse", f"{name}^{{tree}}").strip()
    parent = _git(repo, "rev-parse", name).strip()
    return _git(repo, "commit-tree", tree, "-p", parent, "-m", f"work on {name}").strip()


def _judge(
    repo: Path,
    *,
    agent: str | None = None,
    handoff: bool = False,
    config: BranchesConfig | None = None,
    budget: float = Timeout.GIT_STOP_GUARD_BUDGET,
) -> StopJudgement:
    cfg = config or BranchesConfig()
    inventory = build_inventory(repo, cfg)
    return judge_stop(
        repo,
        inventory,
        cfg,
        session_id=SESSION,
        agent_id=agent,
        handoff=handoff,
        budget=budget,
    )


def _checks(judgement: StopJudgement) -> set[tuple[str, StopCheck]]:
    return {(f.branch, f.check) for f in judgement.findings}


class TestTouchedBySession:
    def test_maps_branch_to_agent_ids(self, repo: Path) -> None:
        _branch(repo, "a")
        _touch(repo, "a")
        _touch(repo, "a", AGENT)
        assert touched_by_session(repo, SESSION) == {"a": {"", AGENT}}

    def test_other_session_ignored(self, repo: Path) -> None:
        _branch(repo, "a")
        _git(repo, "config", "--add", f"branch.a.{TOUCHED_KEY}", "other:")
        assert touched_by_session(repo, SESSION) == {}


class TestDirty:
    def test_untracked_file_in_branch_worktree_blocks(self, repo: Path, tmp_path: Path) -> None:
        _branch(repo, "work", push=True)
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", str(wt), "work")
        (wt / "new.txt").write_text("x")
        _touch(repo, "work")
        judgement = _judge(repo)
        assert (("work", StopCheck.DIRTY)) in _checks(judgement)

    def test_clean_pushed_branch_is_clean(self, repo: Path, tmp_path: Path) -> None:
        _branch(repo, "work", push=True)
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", str(wt), "work")
        _touch(repo, "work")
        assert _judge(repo).findings == ()

    def test_subagent_dirty_not_judged_for_coordinator(self, repo: Path, tmp_path: Path) -> None:
        _branch(repo, "work", push=True)
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", str(wt), "work")
        (wt / "new.txt").write_text("x")
        _touch(repo, "work", AGENT)
        assert _judge(repo).findings == ()
        assert (("work", StopCheck.DIRTY)) in _checks(_judge(repo, agent=AGENT))

    def test_an_unknown_worktree_listing_is_not_called_clean(self, repo: Path) -> None:
        _branch(repo, "work", push=True)
        _touch(repo, "work")
        cfg = BranchesConfig()
        inventory = build_inventory(repo, cfg)
        unknown = dataclasses.replace(
            inventory.records["work"], worktree=None, worktree_known=False
        )
        inventory = dataclasses.replace(inventory, records={**inventory.records, "work": unknown})
        judgement = judge_stop(
            repo, inventory, cfg, session_id=SESSION, agent_id=None, budget=Timeout.GIT_CONTEXT
        )
        assert judgement.incomplete is True


class TestUnpushed:
    def test_unpushed_commits_block_main_thread(self, repo: Path) -> None:
        _branch(repo, "work")
        _touch(repo, "work")
        judgement = _judge(repo)
        assert _checks(judgement) == {("work", StopCheck.UNPUSHED)}
        finding = judgement.findings[0]
        assert any("git push -u origin work" in c for c in finding.commands)
        assert not finding.advisory

    def test_a_branch_touched_then_switched_away_from_is_still_judged(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "work")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "unpushed work")
        _touch(repo, "work")
        _touch(repo, "work", AGENT)
        _git(repo, "checkout", "-q", "main")
        assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
        assert _checks(_judge(repo)) == {("work", StopCheck.UNPUSHED)}
        assert _checks(_judge(repo, agent=AGENT)) == {("work", StopCheck.UNPUSHED)}

    def test_pushed_branch_is_clean(self, repo: Path) -> None:
        _branch(repo, "work", push=True)
        _touch(repo, "work")
        assert _judge(repo).findings == ()

    def test_coordinator_owns_subagent_unpushed(self, repo: Path) -> None:
        _branch(repo, "work")
        _touch(repo, "work", AGENT)
        judgement = _judge(repo)
        assert _checks(judgement) == {("work", StopCheck.UNPUSHED)}
        assert not judgement.findings[0].advisory

    @pytest.mark.parametrize(
        ("mode", "expect"), [("block", False), ("advise", True), ("off", None)]
    )
    def test_subagent_unpushed_follows_config(
        self, repo: Path, mode: str, expect: bool | None
    ) -> None:
        _branch(repo, "work")
        _touch(repo, "work", AGENT)
        config = BranchesConfig.model_validate({"stop_guard": {"unpushed_subagent": mode}})
        judgement = _judge(repo, agent=AGENT, config=config)
        if expect is None:
            assert judgement.findings == ()
        else:
            assert judgement.findings[0].advisory is expect

    def test_branch_merged_locally_into_default_is_handed_over(self, repo: Path) -> None:
        _branch(repo, "work")
        _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "work")
        _touch(repo, "work", AGENT)
        # Merged but present: the merged check fires, the unpushed one does not.
        assert _checks(_judge(repo)) == {("work", StopCheck.MERGED)}


class TestMerged:
    def test_branch_only_fast_forwarded_is_not_merged_work(
        self, repo: Path, tmp_path: Path
    ) -> None:
        # A sub-agent's first step is often `git merge --ff-only main`: the
        # branch moves, but only onto commits main already has.
        _branch(repo, "fresh", push=True, commit=False)
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", str(wt), "fresh")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "main moves on")
        _git(wt, "merge", "-q", "--ff-only", "main")
        _touch(repo, "fresh")
        assert ("fresh", StopCheck.MERGED) not in _checks(_judge(repo))

    def test_branch_that_never_moved_is_not_merged_work(self, repo: Path, tmp_path: Path) -> None:
        # A worktree branch made for a sub-agent that has not committed yet sits
        # at the default tip, so ancestry calls it merged; nothing was merged.
        _branch(repo, "fresh", push=True, commit=False)
        _git(repo, "worktree", "add", "-q", str(tmp_path / "wt"), "fresh")
        _touch(repo, "fresh")
        assert ("fresh", StopCheck.MERGED) not in _checks(_judge(repo))

    def test_merged_not_deleted_blocks_with_commands(self, repo: Path) -> None:
        _branch(repo, "work", push=True)
        _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "work")
        _git(repo, "push", "-q", "origin", "main")
        _touch(repo, "work")
        judgement = _judge(repo)
        assert _checks(judgement) == {("work", StopCheck.MERGED)}
        commands = " ".join(judgement.findings[0].commands)
        assert "git branch -d work" in commands
        assert "git push origin --delete work" in commands

    def test_handoff_waives_merged_only(self, repo: Path) -> None:
        _branch(repo, "work", push=True)
        _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "work")
        _git(repo, "push", "-q", "origin", "main")
        _touch(repo, "work", AGENT)
        assert _judge(repo, agent=AGENT, handoff=True).findings == ()

    def test_handoff_keeps_unpushed_and_reports_tips(self, repo: Path) -> None:
        _branch(repo, "work")
        _touch(repo, "work", AGENT)
        judgement = _judge(repo, agent=AGENT, handoff=True, config=_advise())
        assert _checks(judgement) == {("work", StopCheck.UNPUSHED)}
        assert judgement.tips == {"work": _git(repo, "rev-parse", "work").strip()}


def _advise() -> BranchesConfig:
    return BranchesConfig.model_validate({"stop_guard": {"unpushed_subagent": "advise"}})


class TestExclusions:
    def test_default_branch_excluded(self, repo: Path) -> None:
        _git(repo, "commit", "-q", "--allow-empty", "-m", "ahead")
        _touch(repo, "main")
        assert _judge(repo).findings == ()

    def test_default_branch_included_on_request(self, repo: Path) -> None:
        _git(repo, "commit", "-q", "--allow-empty", "-m", "ahead")
        _touch(repo, "main")
        config = BranchesConfig.model_validate({"stop_guard": {"include_default": True}})
        assert _checks(_judge(repo, config=config)) == {("main", StopCheck.UNPUSHED)}

    def test_untouched_branch_never_judged(self, repo: Path) -> None:
        _branch(repo, "work")
        assert _judge(repo).findings == ()


class TestBudget:
    def test_exhausted_budget_is_incomplete_not_a_finding(self, repo: Path) -> None:
        _branch(repo, "work")
        _touch(repo, "work")
        judgement = _judge(repo, budget=0.0)
        assert judgement.incomplete
        assert judgement.findings == ()

    def test_budget_fits_inside_the_chain_deadline(self) -> None:
        assert Timeout.GIT_STOP_GUARD_BUDGET < Timeout.CHAIN_DEADLINE_DEFAULT
