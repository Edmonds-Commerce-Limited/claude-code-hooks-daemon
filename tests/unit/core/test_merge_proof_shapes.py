"""Proof of merge for every way a branch reaches the default (Plan 00594 Task 3.1).

One real repository (with a bare remote) per shape: fast-forward, merge commit,
a squash of three commits, a renamed pull-request branch squashed, a
cherry-picked (patch-equivalent) branch, and a branch with one commit the default
never took. The evidence order is ancestry, then patch-id, then tree containment,
all offline; the remote's live tip is the only network read.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import (
    BranchesConfig,
    BranchMergedConfig,
    BranchWipConfig,
)
from claude_code_hooks_daemon.core.branch_creation import creation_verdict
from claude_code_hooks_daemon.core.branch_inventory import CACHE_RELATIVE_PATH
from claude_code_hooks_daemon.core.remote_branch_proof import prove_remote_merged
from claude_code_hooks_daemon.daemon.branch_safety import (
    TIER_CONTENT_PRESERVED,
    TIER_MERGED,
    TIER_PATCH_EQUIVALENT,
)

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}
_CONFIG = BranchesConfig(default="main")

#: Git calls one branch may cost the proof beyond the fixed per-call listings.
_CALLS_PER_BRANCH = 4

#: Index of the subcommand in ``git -C <dir> <subcommand> ...``.
_SUBCOMMAND_AT = 3


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    ).stdout


def _commit(repo: Path, filename: str) -> None:
    (repo / filename).write_text(f"{filename}\n", encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-q", "-m", f"Add {filename}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(bare))
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _commit(path, "base.txt")
    _git(path, "remote", "add", "origin", str(bare))
    _git(path, "push", "--quiet", "origin", "main")
    return path


def _topic(repo: Path, name: str, files: list[str]) -> None:
    """Push ``name`` holding one commit per file, then return to main."""
    _git(repo, "checkout", "-q", "-b", name, "main")
    for filename in files:
        _commit(repo, filename)
    _git(repo, "push", "--quiet", "origin", name)
    _git(repo, "checkout", "-q", "main")


def _publish_main(repo: Path) -> None:
    _git(repo, "push", "--quiet", "origin", "main")


def _land_fast_forward(repo: Path, name: str) -> None:
    _git(repo, "merge", "--ff-only", "-q", name)
    _publish_main(repo)


def _land_merge_commit(repo: Path, name: str) -> None:
    _git(repo, "merge", "--no-ff", "-q", "-m", f"Merge {name}", name)
    _publish_main(repo)


def _land_squash(repo: Path, name: str) -> None:
    _git(repo, "merge", "--squash", "-q", name)
    _git(repo, "commit", "-q", "-m", f"Squash {name}")
    _publish_main(repo)


def _land_cherry_picks(repo: Path, name: str) -> None:
    # An unrelated commit first, so the picks get new shas instead of reusing the branch's.
    _commit(repo, f"unrelated-{name}.txt")
    _git(repo, "cherry-pick", f"main..{name}")
    _publish_main(repo)


def _prove(repo: Path, names: list[str]) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    proof = prove_remote_merged(repo, "origin", names, "main", _CONFIG)
    return proof.tips, proof.problems, proof.evidence


def _git_subcommands_during(action: Callable[[], Any]) -> list[str]:
    """The git subcommand of every spawn while ``action`` runs."""
    spawned: list[str] = []
    real_run = subprocess.run

    def spy(argv: list[str], *args: Any, **kwargs: Any) -> Any:
        spawned.append(argv[_SUBCOMMAND_AT])
        return real_run(argv, *args, **kwargs)

    with patch("claude_code_hooks_daemon.utils.git_repo.subprocess.run", spy):
        action()
    return spawned


class TestShapes:
    def test_fast_forward_is_proven_by_ancestry(self, repo: Path) -> None:
        _topic(repo, "feat", ["a.txt"])
        _land_fast_forward(repo, "feat")
        tips, problems, evidence = _prove(repo, ["feat"])
        assert list(tips) == ["feat"]
        assert problems == {}
        assert evidence == {"feat": TIER_MERGED}

    def test_merge_commit_is_proven_by_ancestry(self, repo: Path) -> None:
        _topic(repo, "feat", ["a.txt"])
        _land_merge_commit(repo, "feat")
        tips, problems, evidence = _prove(repo, ["feat"])
        assert list(tips) == ["feat"]
        assert problems == {}
        assert evidence == {"feat": TIER_MERGED}

    def test_squash_of_three_commits_is_proven_by_tree_containment(self, repo: Path) -> None:
        _topic(repo, "feat", ["a.txt", "b.txt", "c.txt"])
        _land_squash(repo, "feat")
        tips, problems, evidence = _prove(repo, ["feat"])
        assert list(tips) == ["feat"]
        assert problems == {}
        assert evidence == {"feat": TIER_CONTENT_PRESERVED}

    def test_renamed_pull_request_branch_squashed_is_proven(self, repo: Path) -> None:
        # The branch that was merged is named differently from the one left on the remote.
        _topic(repo, "feat/original", ["a.txt", "b.txt"])
        _git(repo, "branch", "feat/renamed", "feat/original")
        _land_squash(repo, "feat/renamed")
        _git(repo, "branch", "-q", "-D", "feat/renamed")
        tips, problems, evidence = _prove(repo, ["feat/original"])
        assert list(tips) == ["feat/original"]
        assert problems == {}
        assert evidence == {"feat/original": TIER_CONTENT_PRESERVED}

    def test_cherry_picked_branch_is_proven_by_patch_id(self, repo: Path) -> None:
        _topic(repo, "feat", ["a.txt", "b.txt"])
        _land_cherry_picks(repo, "feat")
        tips, problems, evidence = _prove(repo, ["feat"])
        assert list(tips) == ["feat"]
        assert problems == {}
        assert evidence == {"feat": TIER_PATCH_EQUIVALENT}

    def test_a_branch_with_one_extra_commit_stays_unproven(self, repo: Path) -> None:
        _topic(repo, "feat", ["a.txt", "b.txt"])
        # Main takes only the first commit, squashed; b.txt exists nowhere in main.
        _git(repo, "merge", "--squash", "-q", "feat~1")
        _git(repo, "commit", "-q", "-m", "Squash the first commit")
        _publish_main(repo)
        tips, problems, evidence = _prove(repo, ["feat"])
        assert tips == {}
        assert "not merged" in problems["feat"]
        assert evidence == {}

    def test_a_park_branch_of_empty_commits_stays_unproven(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "parked", "main")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "Park it")
        _git(repo, "push", "--quiet", "origin", "parked")
        _git(repo, "checkout", "-q", "main")
        _commit(repo, "later.txt")
        _publish_main(repo)
        tips, problems, evidence = _prove(repo, ["parked"])
        assert tips == {}
        assert "not merged" in problems["parked"]
        assert evidence == {}


class TestCaching:
    def test_a_squash_proof_is_cached_by_tip_in_the_inventory_cache(self, repo: Path) -> None:
        _topic(repo, "feat", ["a.txt", "b.txt"])
        _land_squash(repo, "feat")
        tip = _git(repo, "rev-parse", "refs/heads/feat").strip()
        _prove(repo, ["feat"])
        document = json.loads((repo / CACHE_RELATIVE_PATH).read_text(encoding="utf-8"))
        assert any(
            key.startswith(f"{tip}:") and value == TIER_CONTENT_PRESERVED
            for key, value in document["proofs"].items()
        )

    def test_a_cached_proof_runs_no_walk_the_second_time(self, repo: Path) -> None:
        _topic(repo, "feat", ["a.txt", "b.txt"])
        _land_squash(repo, "feat")
        _prove(repo, ["feat"])
        subcommands = _git_subcommands_during(lambda: _prove(repo, ["feat"]))
        assert "cherry" not in subcommands
        assert "rev-list" not in subcommands
        assert "ls-tree" not in subcommands

    def test_a_negative_result_is_cached_too(self, repo: Path) -> None:
        _topic(repo, "feat", ["a.txt", "b.txt"])
        _git(repo, "merge", "--squash", "-q", "feat~1")
        _git(repo, "commit", "-q", "-m", "first only")
        _publish_main(repo)
        _prove(repo, ["feat"])
        subcommands = _git_subcommands_during(lambda: _prove(repo, ["feat"]))
        assert "cherry" not in subcommands
        assert "ls-tree" not in subcommands


class TestGuardPathCost:
    def test_git_calls_grow_by_a_bounded_amount_per_branch(self, repo: Path) -> None:
        # Every shape that needs a walk, several of each: the count may grow with the
        # number of branches only by a fixed per-branch allowance (no wall-clock assert).
        names: list[str] = []
        for index in range(4):
            name = f"squash-{index}"
            _topic(repo, name, [f"s{index}a.txt", f"s{index}b.txt"])
            _land_squash(repo, name)
            names.append(name)
        for index in range(3):
            name = f"pick-{index}"
            _topic(repo, name, [f"p{index}a.txt", f"p{index}b.txt"])
            _land_cherry_picks(repo, name)
            names.append(name)
        _topic(repo, "open", ["open.txt"])
        names.append("open")

        one = len(_git_subcommands_during(lambda: _prove(repo, names[:1])))
        (repo / CACHE_RELATIVE_PATH).unlink()
        cold = len(_git_subcommands_during(lambda: _prove(repo, names)))
        warm = len(_git_subcommands_during(lambda: _prove(repo, names)))

        assert warm <= one  # a warm cache: the listings only, whatever the count
        assert cold <= one + _CALLS_PER_BRANCH * (len(names) - 1)


class TestCreationReadsTheProof:
    def test_a_squash_merged_branch_stops_counting_as_open(self, repo: Path) -> None:
        config = BranchesConfig(
            default="main",
            wip=BranchWipConfig(cap=1, count_remote=True),
            merged=BranchMergedConfig(mode="off"),
        )
        _topic(repo, "feat", ["a.txt", "b.txt"])
        assert creation_verdict(repo, config, "fresh").decision == "deny"
        _land_squash(repo, "feat")
        # The proof is computed on an explicit command and read, offline, by the guard.
        prove_remote_merged(repo, "origin", ["feat"], "main", _CONFIG)
        assert creation_verdict(repo, config, "fresh").decision == "allow"
