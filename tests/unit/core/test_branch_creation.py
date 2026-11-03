"""Tests for the branch-creation verdict (Plan 00558 Task 4.2)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Literal

import pytest

from claude_code_hooks_daemon.config.models import (
    BranchDormancyConfig,
    BranchDuplicatesConfig,
    BranchesConfig,
    BranchWipConfig,
)
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.branch_creation import (
    DENY_LIST_LIMIT,
    creation_verdict,
    number_tokens,
    read_labels,
    stem,
    write_labels,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    return root


def _branch(repo: Path, name: str, *, own_commit: bool = True) -> None:
    _git(repo, "branch", name, "main")
    if own_commit:
        tree = _git(repo, "rev-parse", "main^{tree}").strip()
        sha = _git(repo, "commit-tree", tree, "-p", "main", "-m", name).strip()
        _git(repo, "update-ref", f"refs/heads/{name}", sha)


def _config(
    cap: int = 2,
    mode: Literal["block", "warn", "off"] = "block",
    dup: Literal["warn", "off"] = "warn",
) -> BranchesConfig:
    return BranchesConfig(
        default="main",
        wip=BranchWipConfig(cap=cap, mode=mode, count_remote=True),
        duplicates=BranchDuplicatesConfig(mode=dup),
    )


class TestCap:
    def test_under_cap_allows_silently(self, repo: Path) -> None:
        _branch(repo, "one")
        verdict = creation_verdict(repo, _config(cap=2), "fresh")
        assert verdict.decision == "allow"
        assert verdict.lines == ()

    def test_at_cap_denies_listing_branches_and_principle(self, repo: Path) -> None:
        _branch(repo, "one")
        _branch(repo, "two")
        verdict = creation_verdict(repo, _config(cap=2), "fresh")
        assert verdict.decision == "deny"
        text = "\n".join(verdict.lines)
        assert "one" in text and "two" in text
        assert "2" in text
        assert verdict.lines[-1] == BRANCH_LIMIT_PRINCIPLE

    def test_warn_mode_warns(self, repo: Path) -> None:
        _branch(repo, "one")
        _branch(repo, "two")
        assert creation_verdict(repo, _config(cap=2, mode="warn"), "fresh").decision == "warn"

    def test_off_mode_allows(self, repo: Path) -> None:
        _branch(repo, "one")
        _branch(repo, "two")
        verdict = creation_verdict(repo, _config(cap=2, mode="off", dup="off"), "fresh")
        assert verdict.decision == "allow"

    def test_existing_name_is_not_a_creation(self, repo: Path) -> None:
        _branch(repo, "one")
        _branch(repo, "two")
        verdict = creation_verdict(repo, _config(cap=2), "one")
        assert verdict.decision == "allow"
        assert verdict.lines == ()

    def test_protected_and_default_names_are_not_counted(self, repo: Path) -> None:
        _branch(repo, "one")
        _branch(repo, "develop")
        assert creation_verdict(repo, _config(cap=2), "fresh").decision == "allow"

    def test_same_tip_branches_count_once(self, repo: Path) -> None:
        _branch(repo, "one")
        _git(repo, "branch", "one-copy", "one")
        assert creation_verdict(repo, _config(cap=2), "fresh").decision == "allow"

    def test_remote_and_local_of_same_name_count_once(self, repo: Path) -> None:
        _branch(repo, "one")
        sha = _git(repo, "rev-parse", "main").strip()
        _git(repo, "update-ref", "refs/remotes/origin/one", sha)
        assert creation_verdict(repo, _config(cap=2), "fresh").decision == "allow"

    def test_remote_only_branch_counts(self, repo: Path) -> None:
        _branch(repo, "one")
        tree = _git(repo, "rev-parse", "main^{tree}").strip()
        sha = _git(repo, "commit-tree", tree, "-p", "main", "-m", "r").strip()
        _git(repo, "update-ref", "refs/remotes/origin/remote-only", sha)
        assert creation_verdict(repo, _config(cap=2), "fresh").decision == "deny"

    def test_auto_default_reads_remote_head(self, repo: Path) -> None:
        _branch(repo, "one")
        _branch(repo, "trunkish")
        sha = _git(repo, "rev-parse", "trunkish").strip()
        _git(repo, "update-ref", "refs/remotes/origin/trunkish", sha)
        _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunkish")
        config = _config(cap=2)
        config = config.model_copy(update={"default": "auto"})
        assert creation_verdict(repo, config, "fresh").decision == "allow"

    def test_git_failure_allows_with_could_not_judge(self, tmp_path: Path) -> None:
        verdict = creation_verdict(tmp_path / "missing", _config(), "fresh")
        assert verdict.decision == "allow"
        assert any("could not judge" in line for line in verdict.lines)

    def test_deny_list_is_truncated(self, repo: Path) -> None:
        for index in range(DENY_LIST_LIMIT + 3):
            _branch(repo, f"b{index:02d}x")
        verdict = creation_verdict(repo, _config(cap=2, dup="off"), "fresh")
        assert any("and 3 more" in line for line in verdict.lines)

    def test_labels_order_merged_first_with_action(self, repo: Path) -> None:
        _branch(repo, "alpha")
        _branch(repo, "zulu")
        labels = {"zulu": {"group": "merged", "action": "bin/hooks-daemon delete-branch zulu"}}
        verdict = creation_verdict(repo, _config(cap=2), "fresh", labels=labels)
        listed = [line for line in verdict.lines if line.startswith("  - ")]
        assert "zulu" in listed[0]
        assert "delete-branch zulu" in listed[0]

    def test_worktree_is_named(self, repo: Path, tmp_path: Path) -> None:
        _branch(repo, "one")
        _branch(repo, "two")
        _git(repo, "worktree", "add", "-q", str(tmp_path / "wt"), "one")
        verdict = creation_verdict(repo, _config(cap=2), "fresh")
        assert any("wt" in line and "one" in line for line in verdict.lines)


class TestDuplicates:
    def test_duplicate_stem_warns(self, repo: Path) -> None:
        _branch(repo, "fix-login")
        verdict = creation_verdict(repo, _config(cap=5), "fix-login-2")
        assert verdict.decision == "warn"
        assert any("fix-login" in line and "continue there" in line for line in verdict.lines)

    def test_shared_issue_number_warns(self, repo: Path) -> None:
        _branch(repo, "worktree-558-create")
        verdict = creation_verdict(repo, _config(cap=5), "558-force")
        assert verdict.decision == "warn"

    def test_duplicates_off(self, repo: Path) -> None:
        _branch(repo, "fix-login")
        assert creation_verdict(repo, _config(cap=5, dup="off"), "fix-login-2").decision == "allow"

    def test_no_name_skips_duplicates(self, repo: Path) -> None:
        _branch(repo, "fix-login")
        assert creation_verdict(repo, _config(cap=5), None).decision == "allow"

    def test_agent_name_that_exists_still_counts_cap(self, repo: Path) -> None:
        _branch(repo, "one")
        _branch(repo, "two")
        verdict = creation_verdict(repo, _config(cap=2), "one", name_is_branch=False)
        assert verdict.decision == "deny"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("fix-login-2", "fix-login"),
        ("worktree-fix-login-retry2-old", "fix-login"),
        ("origin/agent-x-deadbeef", "x"),
        ("Feature_v2", "feature"),
    ],
)
def test_stem(name: str, expected: str) -> None:
    assert stem(name, "origin") == expected


def test_number_tokens() -> None:
    assert number_tokens("558-create-issue-7.x") == frozenset({"558", "7"})
    assert number_tokens("a-1-123456") == frozenset()


def _dormancy_config(mode: Literal["block", "warn", "off"] = "block") -> BranchesConfig:
    return BranchesConfig(
        default="main",
        wip=BranchWipConfig(cap=50, mode="block", count_remote=True),
        duplicates=BranchDuplicatesConfig(mode="off"),
        dormancy=BranchDormancyConfig(mode=mode),
    )


class TestDormancy:
    def test_block_stage_denies_with_rule_and_ways_out(self, repo: Path) -> None:
        _branch(repo, "stale")
        labels = {"stale": {"group": "dormant", "action": None, "stage": "block"}}
        verdict = creation_verdict(repo, _dormancy_config(), "fresh", labels=labels)
        assert verdict.decision == "deny"
        assert verdict.rule_id == RuleID.BRANCH_DORMANT
        text = "\n".join(verdict.lines)
        assert "stale" in text
        assert "branch-park" in text and "delete-branch" in text
        assert verdict.lines[-1] == BRANCH_LIMIT_PRINCIPLE

    def test_warn_mode_stops_at_noisy(self, repo: Path) -> None:
        _branch(repo, "stale")
        labels = {"stale": {"group": "dormant", "action": None, "stage": "block"}}
        verdict = creation_verdict(repo, _dormancy_config("warn"), "fresh", labels=labels)
        assert verdict.decision == "allow"
        assert "stale" in "\n".join(verdict.lines)

    def test_noisy_stage_adds_context_line_to_allow(self, repo: Path) -> None:
        _branch(repo, "slow")
        labels = {"slow": {"group": "dormant", "action": None, "stage": "noisy"}}
        verdict = creation_verdict(repo, _dormancy_config(), "fresh", labels=labels)
        assert verdict.decision == "allow"
        assert "slow" in "\n".join(verdict.lines)

    def test_advisory_stage_is_silent(self, repo: Path) -> None:
        _branch(repo, "young")
        labels = {"young": {"group": "dormant", "action": None, "stage": "advisory"}}
        verdict = creation_verdict(repo, _dormancy_config(), "fresh", labels=labels)
        assert verdict.lines == ()

    def test_parked_branch_never_trips(self, repo: Path) -> None:
        _branch(repo, "parked")
        labels = {"parked": {"group": "parked", "action": None, "stage": None}}
        verdict = creation_verdict(repo, _dormancy_config(), "fresh", labels=labels)
        assert verdict.decision == "allow"
        assert verdict.lines == ()

    def test_off_mode_ignores_stages(self, repo: Path) -> None:
        _branch(repo, "stale")
        labels = {"stale": {"group": "dormant", "action": None, "stage": "block"}}
        verdict = creation_verdict(repo, _dormancy_config("off"), "fresh", labels=labels)
        assert verdict.lines == ()

    def test_labels_round_trip_stage(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.json"
        write_labels(path, [{"name": "a", "group": "dormant", "dormancy_stage": "noisy"}])
        assert read_labels(path)["a"]["stage"] == "noisy"


class TestLabels:
    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "x" / "labels.json"
        write_labels(path, [{"name": "a", "group": "merged", "action": "do"}])
        assert read_labels(path) == {"a": {"group": "merged", "action": "do", "stage": None}}

    def test_absent_is_empty(self, tmp_path: Path) -> None:
        assert read_labels(tmp_path / "none.json") == {}

    def test_invalid_is_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.json"
        path.write_text("{not json")
        assert read_labels(path) == {}
        path.write_text(json.dumps([1, 2]))
        assert read_labels(path) == {}
