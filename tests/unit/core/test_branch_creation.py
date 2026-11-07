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
    Config,
    handler_options,
)
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.branch_cleanup import sweep_clean_command
from claude_code_hooks_daemon.core.branch_creation import (
    DENY_LIST_LIMIT,
    creation_verdict,
    number_tokens,
    read_labels,
    stem,
    write_labels,
)
from claude_code_hooks_daemon.core.branch_sweep import effective_wip_cap


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

    def test_auto_default_resolves_without_counting_remote_refs(self, repo: Path) -> None:
        """The default resolves the same way the inventory does, whatever wip.count_remote is."""
        _branch(repo, "one")
        _branch(repo, "trunkish")
        sha = _git(repo, "rev-parse", "trunkish").strip()
        _git(repo, "update-ref", "refs/remotes/origin/trunkish", sha)
        _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunkish")
        config = BranchesConfig(
            default="auto", wip=BranchWipConfig(cap=2, mode="block", count_remote=False)
        )
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

    def test_labels_order_contained_nowhere_first_with_action(self, repo: Path) -> None:
        _branch(repo, "alpha")
        _branch(repo, "zulu")
        labels = {"zulu": {"group": "contained-nowhere", "action": "git push -u origin zulu"}}
        verdict = creation_verdict(repo, _config(cap=2), "fresh", labels=labels)
        listed = [line for line in verdict.lines if line.startswith("  - ")]
        assert "zulu" in listed[0]
        assert "git push -u origin zulu" in listed[0]

    def test_worktree_is_named(self, repo: Path, tmp_path: Path) -> None:
        _branch(repo, "one")
        _branch(repo, "two")
        _git(repo, "worktree", "add", "-q", str(tmp_path / "wt"), "one")
        verdict = creation_verdict(repo, _config(cap=2), "fresh")
        assert any("wt" in line and "one" in line for line in verdict.lines)


class TestLegacyCap:
    """With only the retired ``max_open_branches`` set, the report and the guard share one cap."""

    @staticmethod
    def _legacy_config() -> Config:
        return Config.model_validate(
            {
                "handlers": {
                    "session_start": {
                        "branch_sweep": {"enabled": True, "options": {"max_open_branches": 2}}
                    }
                },
                "branches": {"default": "main", "duplicates": {"mode": "off"}},
            }
        )

    def test_report_and_guard_agree_on_the_legacy_cap(self, repo: Path) -> None:
        config = self._legacy_config()
        legacy = handler_options(config.handlers.session_start.get("branch_sweep"))
        assert effective_wip_cap(config.branches, legacy) == 2
        assert config.branches.effective_wip_cap() == 2
        _branch(repo, "one")
        _branch(repo, "two")
        verdict = creation_verdict(repo, config.branches, "fresh")
        assert verdict.decision == "deny"
        assert "cap 2" in "\n".join(verdict.lines)

    def test_an_explicit_cap_beats_the_legacy_value(self, repo: Path) -> None:
        config = Config.model_validate(
            {
                "handlers": {
                    "session_start": {"branch_sweep": {"options": {"max_open_branches": 2}}}
                },
                "branches": {"default": "main", "wip": {"cap": 5}},
            }
        )
        assert config.branches.effective_wip_cap() == 5

    def test_nothing_set_is_the_default(self) -> None:
        assert Config.model_validate({}).branches.effective_wip_cap() == 10


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
        assert read_labels(path) == {
            "a": {"group": "merged", "action": "do", "stage": None, "stale": None}
        }

    def test_absent_is_empty(self, tmp_path: Path) -> None:
        assert read_labels(tmp_path / "none.json") == {}

    def test_invalid_is_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.json"
        path.write_text("{not json")
        assert read_labels(path) == {}
        path.write_text(json.dumps([1, 2]))
        assert read_labels(path) == {}


class TestWipCapLeavesMergedToItsOwnPool:
    """A merged branch is in the merged pool, not the WIP count (Plan 00571 DESIGN.md s1)."""

    def test_a_merged_label_takes_the_branch_out_of_the_wip_count(self, repo: Path) -> None:
        _branch(repo, "alpha")
        _branch(repo, "zulu")
        labels = {"zulu": {"group": "merged", "action": "bin/hooks-daemon delete-branch zulu"}}
        verdict = creation_verdict(repo, _config(cap=2), "fresh", labels=labels)
        assert verdict.rule_id != RuleID.BRANCH_WIP_CAP
        assert sweep_clean_command() not in "\n".join(
            line for line in verdict.lines if "Open work branches" in line
        )

    def test_no_merged_branch_no_clean_line(self, repo: Path) -> None:
        _branch(repo, "alpha")
        _branch(repo, "zulu")
        verdict = creation_verdict(repo, _config(cap=2), "fresh")
        assert "--clean" not in "\n".join(verdict.lines)
