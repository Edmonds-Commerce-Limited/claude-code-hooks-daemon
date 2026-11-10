"""Proof of merge for every way a branch reaches the default (Plan 00594 Task 3.1).

One real repository (with a bare remote) per shape: fast-forward, merge commit,
a squash of three commits, a renamed pull-request branch squashed, a
cherry-picked (patch-equivalent) branch, and a branch with one commit the default
never took. The evidence order is ancestry, then patch-id, then tree containment,
all offline; the remote's live tip is the only network read.
"""

from __future__ import annotations

import json
import os
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
from claude_code_hooks_daemon.core import remote_branch_proof
from claude_code_hooks_daemon.core.branch_creation import (
    _proven_refnames,
    _Ref,
    creation_verdict,
)
from claude_code_hooks_daemon.core.branch_inventory import (
    CACHE_RELATIVE_PATH,
    PROOF_ALGORITHM_VERSION,
    merge_proof_key,
    write_merge_proofs,
)
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
_CALLS_PER_BRANCH = 5

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
            key.startswith(f"{PROOF_ALGORITHM_VERSION}:{tip}:") and value == TIER_CONTENT_PRESERVED
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

    def test_a_branch_over_the_path_ceiling_is_unproven_without_walking_main(
        self, repo: Path
    ) -> None:
        # A branch touching very many paths costs git calls in proportion to them on
        # the hook path; past the ceiling the proof stops and the delete is refused.
        _topic(repo, "wide", ["w1.txt", "w2.txt", "w3.txt"])
        _land_squash(repo, "wide")
        with patch.object(remote_branch_proof, "MAX_PROOF_PATHS", 2):
            calls = _git_subcommands_during(lambda: _prove(repo, ["wide"]))
            tips, problems, _evidence = _prove(repo, ["wide"])
        assert tips == {}
        assert "wide" in problems
        assert "log" not in calls and "ls-tree" not in calls

    def test_a_branch_at_the_path_ceiling_is_still_proven(self, repo: Path) -> None:
        _topic(repo, "narrow", ["n1.txt", "n2.txt"])
        _land_squash(repo, "narrow")
        with patch.object(remote_branch_proof, "MAX_PROOF_PATHS", 2):
            tips, problems, _evidence = _prove(repo, ["narrow"])
        assert list(tips) == ["narrow"]
        assert problems == {}


class TestCreationReadsTheProof:
    def test_a_squash_merged_branch_stops_counting_as_open(self, repo: Path) -> None:
        config = BranchesConfig(
            default="main",
            wip=BranchWipConfig(cap=1, count_remote=True, creation_grace=0),
            merged=BranchMergedConfig(mode="off"),
        )
        _topic(repo, "feat", ["a.txt", "b.txt"])
        assert creation_verdict(repo, config, "fresh").decision == "deny"
        _land_squash(repo, "feat")
        # The proof is computed on an explicit command and read, offline, by the guard.
        prove_remote_merged(repo, "origin", ["feat"], "main", _CONFIG)
        assert creation_verdict(repo, config, "fresh").decision == "allow"

    def test_a_line_sharing_a_proven_feature_tip_is_never_read_as_merged(self, repo: Path) -> None:
        config = BranchesConfig(default="main", integration_lines=["release/*"])
        _topic(repo, "feat", ["a.txt", "b.txt"])
        _git(repo, "branch", "release/1", "feat")
        _git(repo, "push", "--quiet", "origin", "release/1")
        _land_squash(repo, "feat")
        prove_remote_merged(repo, "origin", ["feat"], "main", _CONFIG)
        tip = _git(repo, "rev-parse", "refs/heads/feat").strip()
        main = _git(repo, "rev-parse", "refs/heads/main").strip()
        refs = [
            _Ref("main", main, 0.0, True, "refs/heads/main"),
            _Ref("feat", tip, 0.0, True, "refs/heads/feat"),
            _Ref("release/1", tip, 0.0, True, "refs/heads/release/1"),
        ]
        proven = _proven_refnames(repo, config, refs, ["refs/heads/main"], set())
        assert proven == {"refs/heads/feat"}


def _on_branch(repo: Path, name: str) -> None:
    _git(repo, "checkout", "-q", "-b", name, "main")


def _push_back_to_main(repo: Path, name: str) -> None:
    _git(repo, "push", "--quiet", "origin", name)
    _git(repo, "checkout", "-q", "main")


def _assert_unproven(repo: Path, name: str) -> None:
    tips, problems, evidence = _prove(repo, [name])
    assert tips == {}
    assert "not merged" in problems[name]
    assert evidence == {}


def _overwrite(repo: Path, content: str, message: str) -> None:
    (repo / "keep.txt").write_text(content, encoding="utf-8")
    _git(repo, "commit", "-q", "-am", message)


class TestNetChangeMustBeHeldByTheDefaultTip:
    """A false "merged" lets an agent delete a remote branch with no bundle."""

    def test_a_branch_that_only_deletes_a_file_main_still_has_is_unproven(self, repo: Path) -> None:
        _commit(repo, "keep.txt")
        _publish_main(repo)
        _on_branch(repo, "rm")
        _git(repo, "rm", "-q", "keep.txt")
        _git(repo, "commit", "-q", "-m", "Remove keep")
        _push_back_to_main(repo, "rm")
        _assert_unproven(repo, "rm")

    def test_a_branch_that_reverts_mains_change_to_an_older_version_is_unproven(
        self, repo: Path
    ) -> None:
        _commit(repo, "keep.txt")
        _overwrite(repo, "v2\n", "v2")
        _publish_main(repo)
        _on_branch(repo, "fix")
        _git(repo, "revert", "--no-edit", "HEAD")
        _push_back_to_main(repo, "fix")
        _assert_unproven(repo, "fix")

    def test_a_rename_only_branch_is_unproven(self, repo: Path) -> None:
        _on_branch(repo, "mv")
        _git(repo, "mv", "base.txt", "moved.txt")
        _git(repo, "commit", "-q", "-m", "Rename")
        _push_back_to_main(repo, "mv")
        _assert_unproven(repo, "mv")

    def test_a_copy_only_branch_is_unproven(self, repo: Path) -> None:
        _on_branch(repo, "cp")
        (repo / "copy.txt").write_text("base.txt\n", encoding="utf-8")
        _git(repo, "add", "copy.txt")
        _git(repo, "commit", "-q", "-m", "Copy")
        _push_back_to_main(repo, "cp")
        _assert_unproven(repo, "cp")

    def test_a_chmod_only_branch_is_unproven(self, repo: Path) -> None:
        _on_branch(repo, "chmod")
        (repo / "base.txt").chmod(0o755)
        _git(repo, "commit", "-q", "-a", "-m", "Make executable")
        _push_back_to_main(repo, "chmod")
        _assert_unproven(repo, "chmod")

    def test_a_park_branch_is_unproven_while_main_has_an_empty_commit(self, repo: Path) -> None:
        _on_branch(repo, "parked")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "Park it")
        _push_back_to_main(repo, "parked")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "An empty commit on main")
        _publish_main(repo)
        _assert_unproven(repo, "parked")

    def test_branch_work_that_main_later_reverted_is_proven(self, repo: Path) -> None:
        """Round 1 called this a false positive; under the first-parent rule it is intended.

        The cherry-pick commit on main's first-parent line held the branch's exact net
        change, so the content is permanently in main's history. Deleting the remote
        branch loses nothing, even though main's tip has since dropped the file.
        """
        _topic(repo, "feat", ["a.txt"])
        _land_cherry_picks(repo, "feat")
        _git(repo, "rm", "-q", "a.txt")
        _git(repo, "commit", "-q", "-m", "Revert a")
        _publish_main(repo)
        tips, _problems, _evidence = _prove(repo, ["feat"])
        assert list(tips) == ["feat"]

    def test_an_old_base_branch_whose_change_main_overwrote_with_other_content_is_unproven(
        self, repo: Path
    ) -> None:
        _commit(repo, "keep.txt")
        _publish_main(repo)
        _on_branch(repo, "old")
        _overwrite(repo, "v2\n", "v2")
        _push_back_to_main(repo, "old")
        _overwrite(repo, "v2-different\n", "other v2 on main")
        _overwrite(repo, "v3\n", "v3")
        _publish_main(repo)
        _assert_unproven(repo, "old")

    def test_an_old_base_branch_whose_exact_change_a_main_commit_held_is_proven(
        self, repo: Path
    ) -> None:
        _commit(repo, "keep.txt")
        _publish_main(repo)
        _on_branch(repo, "old")
        _overwrite(repo, "v2\n", "v2")
        _push_back_to_main(repo, "old")
        _overwrite(repo, "v2\n", "v2 on main")
        _overwrite(repo, "v3\n", "v3")
        _publish_main(repo)
        tips, _problems, _evidence = _prove(repo, ["old"])
        assert list(tips) == ["old"]

    def test_a_squash_several_main_commits_ago_stays_proven(self, repo: Path) -> None:
        _topic(repo, "feat", ["a.txt", "b.txt"])
        _land_squash(repo, "feat")
        for index in range(4):
            _commit(repo, f"later{index}.txt")
        _publish_main(repo)
        tips, _problems, evidence = _prove(repo, ["feat"])
        assert list(tips) == ["feat"]
        assert evidence == {"feat": TIER_CONTENT_PRESERVED}

    def test_a_squashed_file_main_changed_again_stays_proven(self, repo: Path) -> None:
        _topic(repo, "feat", ["a.txt", "b.txt"])
        _land_squash(repo, "feat")
        (repo / "a.txt").write_text("changed later\n", encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "Edit a")
        _publish_main(repo)
        tips, _problems, _evidence = _prove(repo, ["feat"])
        assert list(tips) == ["feat"]

    def test_more_candidates_than_the_cap_is_unproven_not_proven(self, repo: Path) -> None:
        _topic(repo, "feat", ["a.txt"])
        _land_squash(repo, "feat")
        for index in range(3):
            (repo / "a.txt").write_text(f"edit {index}\n", encoding="utf-8")
            _git(repo, "commit", "-q", "-am", f"Edit {index}")
        _publish_main(repo)
        with patch.object(remote_branch_proof, "MAX_PROOF_CANDIDATES", 2):
            _assert_unproven(repo, "feat")

    def test_a_delete_only_branch_run_from_a_subdirectory_is_unproven(self, repo: Path) -> None:
        _commit(repo, "keep.txt")
        (repo / "sub").mkdir()
        _commit(repo, "sub/inner.txt")
        _publish_main(repo)
        _on_branch(repo, "rm")
        _git(repo, "rm", "-q", "keep.txt")
        _git(repo, "commit", "-q", "-m", "Remove keep")
        _push_back_to_main(repo, "rm")
        proof = prove_remote_merged(repo / "sub", "origin", ["rm"], "main", _CONFIG)
        assert proof.tips == {}
        assert "not merged" in proof.problems["rm"]

    def test_the_guard_denies_a_delete_only_branch_typed_from_a_subdirectory(
        self, repo: Path
    ) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
            DestructiveGitHandler,
        )

        _commit(repo, "keep.txt")
        (repo / "sub").mkdir()
        _commit(repo, "sub/inner.txt")
        _publish_main(repo)
        _on_branch(repo, "rm")
        _git(repo, "rm", "-q", "keep.txt")
        _git(repo, "commit", "-q", "-m", "Remove keep")
        _push_back_to_main(repo, "rm")
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin --delete rm"},
            "cwd": str(repo / "sub"),
        }
        result = DestructiveGitHandler().handle(hook_input)
        assert result.decision == "deny"

    def test_a_squash_is_proven_from_a_subdirectory(self, repo: Path) -> None:
        (repo / "sub").mkdir()
        _commit(repo, "sub/inner.txt")
        _publish_main(repo)
        _topic(repo, "feat", ["a.txt", "sub/b.txt"])
        _land_squash(repo, "feat")
        proof = prove_remote_merged(repo / "sub", "origin", ["feat"], "main", _CONFIG)
        assert list(proof.tips) == ["feat"]

    def test_deleting_a_non_utf8_file_name_is_unproven(self, repo: Path) -> None:
        name = os.fsdecode(b"caf\xe9.txt")
        (repo / name).write_text("x\n", encoding="utf-8")
        _git(repo, "add", name)
        _git(repo, "commit", "-q", "-m", "Latin-1 name")
        _publish_main(repo)
        _on_branch(repo, "rm")
        _git(repo, "rm", "-q", name)
        _git(repo, "commit", "-q", "-m", "Remove it")
        _push_back_to_main(repo, "rm")
        _assert_unproven(repo, "rm")

    def test_old_version_proof_entries_are_dropped_on_save(self, repo: Path) -> None:
        cache = repo / CACHE_RELATIVE_PATH
        write_merge_proofs(repo, {merge_proof_key("tip0", ["m"]): TIER_MERGED})
        document = json.loads(cache.read_text(encoding="utf-8"))
        document["proofs"] = {"v1:abc:def": TIER_CONTENT_PRESERVED}
        cache.write_text(json.dumps(document), encoding="utf-8")
        write_merge_proofs(repo, {merge_proof_key("tip1", ["m"]): TIER_MERGED})
        proofs = json.loads(cache.read_text(encoding="utf-8"))["proofs"]
        assert list(proofs) == [merge_proof_key("tip1", ["m"])]

    def test_a_branch_whose_deletion_main_also_made_is_proven(self, repo: Path) -> None:
        _commit(repo, "keep.txt")
        _publish_main(repo)
        _on_branch(repo, "rm")
        _git(repo, "rm", "-q", "keep.txt")
        _git(repo, "commit", "-q", "-m", "Remove keep")
        _push_back_to_main(repo, "rm")
        _git(repo, "rm", "-q", "keep.txt")
        _git(repo, "commit", "-q", "-m", "Remove keep on main")
        _publish_main(repo)
        tips, _problems, evidence = _prove(repo, ["rm"])
        assert list(tips) == ["rm"]
        assert evidence == {"rm": TIER_PATCH_EQUIVALENT}


class TestProofKeyVersion:
    def test_the_key_carries_an_algorithm_version_prefix(self) -> None:
        assert merge_proof_key("abc", ["def"]).startswith(f"{PROOF_ALGORITHM_VERSION}:")

    def test_a_proof_cached_by_the_old_algorithm_is_ignored(self, repo: Path) -> None:
        _on_branch(repo, "rm")
        _git(repo, "mv", "base.txt", "moved.txt")
        _git(repo, "commit", "-q", "-m", "Rename")
        _push_back_to_main(repo, "rm")
        tip = _git(repo, "rev-parse", "refs/heads/rm").strip()
        main = _git(repo, "rev-parse", "refs/heads/main").strip()
        cache = repo / CACHE_RELATIVE_PATH
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps({"proofs": {f"{tip}:{main}": TIER_CONTENT_PRESERVED}}), encoding="utf-8"
        )
        _assert_unproven(repo, "rm")
