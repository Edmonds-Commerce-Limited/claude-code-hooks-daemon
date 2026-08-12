"""Tests for the deterministic safe-branch-delete proof engine (Plan 00206).

`destructive_git` blocks the force branch delete outright, and git's own safe
delete refuses anything it considers unmerged. A branch that legitimately needs
deleting therefore has no route but escalation to a human — which is what
stalled the v3.52.0 release.

These tests drive a proof engine that EARNS a deletion rather than asserting
one. Every fixture builds a REAL git repository, because the subject under test
is git's own reachability and patch-identity semantics; a mock would assert
only that we called the functions we already believed in.

The proof is blob identity, never path presence. An earlier draft added a
"content-subsumed" tier that approved a branch when every path on it also
appeared somewhere in the protected ref's history — but a path existing says
nothing about the CONTENT at that path, so the branch's version could still be
the only copy. That tier could approve a lossy deletion, so it was replaced by
``content-preserved``, which compares blob shas and therefore proves the bytes
survive. ``test_a_path_main_knows_but_whose_content_differs_stays_unproven``
pins the difference.
"""

from __future__ import annotations

import subprocess  # nosec B404 - trusted system tool (git) for repo fixtures
from collections.abc import Sequence
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.branch_safety import (
    REFUSAL_CURRENT_BRANCH,
    REFUSAL_NOT_A_BRANCH,
    REFUSAL_PROTECTED,
    REFUSAL_WORKTREE,
    TIER_CONTENT_PRESERVED,
    TIER_MERGED,
    TIER_PATCH_EQUIVALENT,
    TIER_UNPROVEN,
    BranchClassification,
    classify_branch,
    delete_argv_for_tier,
    delete_branches,
    write_recovery_bundle,
)


def _approve(_classifications: Sequence[BranchClassification], _reason: str) -> bool:
    """Stand-in for a human who consented at the terminal."""
    return True


def _decline(_classifications: Sequence[BranchClassification], _reason: str) -> bool:
    """Stand-in for a human who was asked and said no."""
    return False


_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}


def _git(repo: Path, *args: str) -> str:
    """Run git in ``repo``, failing loudly, returning stdout."""
    result = subprocess.run(  # nosec B603 B607 - trusted system tool, list form
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    )
    return result.stdout


def _commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)


def _local_branches(repo: Path) -> set[str]:
    out = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    return {line for line in out.splitlines() if line}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on ``main`` with one commit."""
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    _commit(path, "base.txt", "base\n", "Initial commit")
    return path


def _merged_branch(repo: Path, name: str) -> None:
    _git(repo, "checkout", "-b", name)
    _commit(repo, f"{name}.txt", f"{name}\n", f"Add {name}")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--ff-only", name)


def _unproven_branch(repo: Path, name: str) -> None:
    _git(repo, "checkout", "-b", name)
    _commit(repo, f"{name}-only.txt", f"{name}\n", f"Unique work on {name}")
    _git(repo, "checkout", "main")


class TestBlockingPreconditions:
    """A refusal is absolute: no tier is computed and nothing is deleted."""

    def test_current_branch_is_refused(self, repo: Path) -> None:
        result = classify_branch(repo, "main")
        assert result.refusal == REFUSAL_CURRENT_BRANCH
        assert result.is_safe is False

    def test_protected_branch_name_is_refused(self, repo: Path) -> None:
        _git(repo, "branch", "develop")
        _git(repo, "checkout", "-b", "scratch")
        assert classify_branch(repo, "develop").refusal == REFUSAL_PROTECTED

    def test_unknown_branch_is_refused(self, repo: Path) -> None:
        assert classify_branch(repo, "no-such-branch").refusal == REFUSAL_NOT_A_BRANCH

    def test_branch_checked_out_in_a_worktree_is_refused(self, repo: Path) -> None:
        _git(repo, "branch", "wt-branch")
        _git(repo, "worktree", "add", str(repo.parent / "wt"), "wt-branch")
        assert classify_branch(repo, "wt-branch").refusal == REFUSAL_WORKTREE

    def test_a_refused_branch_is_never_deleted(self, repo: Path) -> None:
        report = delete_branches(repo, ["main"])
        assert report.refused is True
        assert report.deleted == ()

    def test_refusal_outranks_allow_unproven(self, repo: Path) -> None:
        """``--allow-unproven`` relaxes the TIER, never a blocking precondition."""
        report = delete_branches(repo, ["main"], allow_unproven=True, reason="trying to force it")
        assert report.refused is True
        assert report.deleted == ()


class TestProofTiers:
    """Each tier is proven independently, cheapest first."""

    def test_merged_branch_reaches_merged_tier(self, repo: Path) -> None:
        _merged_branch(repo, "feature")
        assert classify_branch(repo, "feature").tier == TIER_MERGED

    def test_patch_equivalent_branch_is_proven_without_ancestry(self, repo: Path) -> None:
        """The post-rewrite shape: same diff, different sha, not an ancestor."""
        _git(repo, "checkout", "-b", "feature")
        _commit(repo, "shared.txt", "shared\n", "Add shared on branch")
        _git(repo, "checkout", "main")
        _git(repo, "cherry-pick", "feature")
        _git(repo, "commit", "--amend", "-m", "Add shared, reworded on main")

        result = classify_branch(repo, "feature")
        assert result.tier == TIER_PATCH_EQUIVALENT
        assert result.is_safe is True

    def test_branch_with_novel_content_is_unproven(self, repo: Path) -> None:
        _unproven_branch(repo, "novel")
        result = classify_branch(repo, "novel")
        assert result.tier == TIER_UNPROVEN
        assert result.is_safe is False

    def test_unproven_branch_names_the_paths_unique_to_it(self, repo: Path) -> None:
        _unproven_branch(repo, "novel")
        assert "novel-only.txt" in classify_branch(repo, "novel").unique_paths

    def test_unproven_branch_reports_its_unique_commit_count(self, repo: Path) -> None:
        _git(repo, "checkout", "-b", "novel")
        _commit(repo, "a.txt", "a\n", "One")
        _commit(repo, "b.txt", "b\n", "Two")
        _git(repo, "checkout", "main")
        assert classify_branch(repo, "novel").unique_commits == 2

    def test_a_path_main_knows_but_whose_content_differs_stays_unproven(self, repo: Path) -> None:
        """Why the proof is blob identity and not path presence.

        ``doomed.txt`` exists in main's history, so a PATH-level check would
        call this branch subsumed — but the branch holds the only copy of this
        particular version of it, so a path-level tier would approve a lossy
        deletion.
        """
        _commit(repo, "doomed.txt", "original\n", "Add doomed")
        _git(repo, "checkout", "-b", "revives")
        _commit(repo, "doomed.txt", "a different version\n", "Rewrite doomed")
        _git(repo, "checkout", "main")
        _git(repo, "rm", "doomed.txt")
        _git(repo, "commit", "-m", "Delete doomed")

        result = classify_branch(repo, "revives")
        assert result.tier == TIER_UNPROVEN
        assert "doomed.txt" in result.content_unique_paths


class TestContentPreservedTier:
    """Blob identity: every file version on the branch also exists in main.

    This is the tier that matters for real stale branches. Their files are
    typically byte-identical to main's, merely sitting at paths main has since
    moved away from — so a path-level comparison screams and a content-level
    one correctly stays quiet.
    """

    @staticmethod
    def _branch_duplicating_main_content(repo: Path, name: str) -> None:
        """Build a branch that is NOT an ancestor and NOT patch-equivalent, yet
        introduces no new bytes: it copies a file main already has.

        Ancestry and patch-id both fail here, so only blob identity can prove
        this branch safe — which is exactly the tier under test.
        """
        _commit(repo, "doc.md", "durable content\n", "Add doc")
        _git(repo, "checkout", "-b", name)
        # Same bytes as doc.md, so the blob already exists in main.
        _commit(repo, "copy.md", "durable content\n", "Duplicate existing content")
        _git(repo, "checkout", "main")
        _commit(repo, "later.txt", "later\n", "Diverge so the branch is no ancestor")

    def test_branch_introducing_no_new_bytes_is_content_preserved(self, repo: Path) -> None:
        self._branch_duplicating_main_content(repo, "dup")
        result = classify_branch(repo, "dup")
        assert result.tier == TIER_CONTENT_PRESERVED
        assert result.is_safe is True
        assert result.unique_commits > 0

    def test_content_preserved_branch_deletes_without_flags(self, repo: Path) -> None:
        self._branch_duplicating_main_content(repo, "dup")
        report = delete_branches(repo, ["dup"], bundle_path=None)
        assert report.refused is False
        assert report.deleted == ("dup",)

    def test_unproven_separates_path_uniqueness_from_content_uniqueness(self, repo: Path) -> None:
        """The distinction that stops a scary path count reading as data loss."""
        _commit(repo, "shared.md", "same bytes\n", "Add shared")
        _git(repo, "checkout", "-b", "mixed")
        _git(repo, "mv", "shared.md", "renamed.md")
        _git(repo, "commit", "-m", "Rename on branch only")
        _commit(repo, "novel.txt", "genuinely new\n", "Add novel content")
        _git(repo, "checkout", "main")

        result = classify_branch(repo, "mixed")
        assert result.tier == TIER_UNPROVEN
        # 'renamed.md' is a new PATH but its bytes are main's.
        assert "renamed.md" in result.unique_paths
        assert "renamed.md" not in result.content_unique_paths
        # 'novel.txt' is unique both ways — this is the only real risk.
        assert "novel.txt" in result.content_unique_paths


class TestDeletion:
    """Deletion is all-or-nothing and reversible by default."""

    def test_provably_safe_branch_is_deleted(self, repo: Path) -> None:
        _merged_branch(repo, "done")
        report = delete_branches(repo, ["done"], bundle_path=repo.parent / "b.bundle")
        assert report.refused is False
        assert report.deleted == ("done",)
        assert "done" not in _local_branches(repo)

    def test_one_unproven_branch_blocks_the_whole_batch(self, repo: Path) -> None:
        _merged_branch(repo, "safe-one")
        _unproven_branch(repo, "risky")

        report = delete_branches(repo, ["safe-one", "risky"])
        assert report.refused is True
        assert report.deleted == ()
        assert {"safe-one", "risky"} <= _local_branches(repo)

    def test_allow_unproven_requires_a_reason(self, repo: Path) -> None:
        _unproven_branch(repo, "risky")
        with pytest.raises(ValueError, match="reason"):
            delete_branches(repo, ["risky"], allow_unproven=True, confirm=_approve)

    def test_allow_unproven_with_a_reason_deletes(self, repo: Path) -> None:
        _unproven_branch(repo, "risky")
        report = delete_branches(
            repo,
            ["risky"],
            allow_unproven=True,
            reason="content is deliberately being destroyed",
            bundle_path=repo.parent / "r.bundle",
            confirm=_approve,
        )
        assert report.deleted == ("risky",)
        assert "risky" not in _local_branches(repo)


class TestAbandonmentIsHumanGated:
    """Discarding unmerged work is a human's call, never an agent's.

    Every other tier is a *proof* — checkable mechanically. ``unproven`` is the
    one path where real work is knowingly destroyed, so it must not be reachable
    by an agent that simply passes another flag. A declared reason is an
    assertion of intent, not a gate; only a human is a gate.
    """

    def test_unproven_deletion_without_a_confirmer_is_refused(self, repo: Path) -> None:
        _unproven_branch(repo, "risky")
        report = delete_branches(repo, ["risky"], allow_unproven=True, reason="I would like to")
        assert report.refused is True
        assert report.deleted == ()
        assert "risky" in _local_branches(repo)

    def test_a_declined_confirmation_deletes_nothing(self, repo: Path) -> None:
        _unproven_branch(repo, "risky")
        report = delete_branches(
            repo,
            ["risky"],
            allow_unproven=True,
            reason="asked but refused",
            confirm=_decline,
        )
        assert report.refused is True
        assert report.deleted == ()
        assert "risky" in _local_branches(repo)

    def test_the_confirmer_receives_the_branches_and_the_reason(self, repo: Path) -> None:
        """A human cannot consent to something they were not shown."""
        _unproven_branch(repo, "risky")
        shown: list[BranchClassification] = []
        stated: list[str] = []

        def _spy(classifications: Sequence[BranchClassification], reason: str) -> bool:
            shown.extend(classifications)
            stated.append(reason)
            return True

        delete_branches(
            repo,
            ["risky"],
            allow_unproven=True,
            reason="the stated rationale",
            bundle_path=None,
            confirm=_spy,
        )
        assert stated == ["the stated rationale"]
        assert [c.name for c in shown] == ["risky"]

    def test_provably_safe_branches_never_ask_for_confirmation(self, repo: Path) -> None:
        """The gate exists for abandonment, not for proven-safe cleanup."""
        _merged_branch(repo, "done")

        def _explode(_classifications: Sequence[BranchClassification], _reason: str) -> bool:
            raise AssertionError("a proven-safe deletion must not prompt a human")

        report = delete_branches(repo, ["done"], bundle_path=None, confirm=_explode)
        assert report.deleted == ("done",)

    def test_dry_run_classifies_but_deletes_nothing(self, repo: Path) -> None:
        _merged_branch(repo, "done")
        report = delete_branches(repo, ["done"], dry_run=True)
        assert report.deleted == ()
        assert "done" in _local_branches(repo)
        assert report.classifications[0].tier == TIER_MERGED

    def test_dry_run_writes_no_bundle(self, repo: Path) -> None:
        _merged_branch(repo, "done")
        bundle = repo.parent / "unwanted.bundle"
        delete_branches(repo, ["done"], dry_run=True, bundle_path=bundle)
        assert bundle.exists() is False

    def test_recovery_bundle_restores_a_deleted_branch(self, repo: Path) -> None:
        _merged_branch(repo, "done")
        bundle = repo.parent / "recovery.bundle"
        delete_branches(repo, ["done"], bundle_path=bundle)
        assert bundle.is_file()

        _git(repo, "fetch", str(bundle), "done:restored")
        assert "restored" in _local_branches(repo)

    def test_no_bundle_skips_the_bundle(self, repo: Path) -> None:
        _merged_branch(repo, "done")
        report = delete_branches(repo, ["done"], bundle_path=None)
        assert report.bundle is None
        assert report.deleted == ("done",)


class TestPrefersGitsOwnCheck:
    """Plain ``-d`` is battle-tested; our proof is not. Use ours only when
    git's cannot do the job at all."""

    def test_merged_tier_uses_the_safe_delete_not_force(self) -> None:
        assert delete_argv_for_tier(TIER_MERGED) == ("branch", "--delete")

    @pytest.mark.parametrize("tier", [TIER_PATCH_EQUIVALENT, TIER_CONTENT_PRESERVED, TIER_UNPROVEN])
    def test_tiers_git_cannot_verify_must_force(self, tier: str) -> None:
        """A rewrite or squash merge severs ancestry, so git always calls these
        unmerged and the safe delete cannot succeed."""
        assert delete_argv_for_tier(tier) == ("branch", "--delete", "--force")

    def test_a_merged_deletion_really_goes_through_gits_own_check(self, repo: Path) -> None:
        """End-to-end: if our ancestry proof were wrong, git would refuse and
        this would raise rather than silently destroying the branch."""
        _merged_branch(repo, "done")
        report = delete_branches(repo, ["done"], bundle_path=None)
        assert report.deleted == ("done",)
        assert "done" not in _local_branches(repo)


class TestRecoveryBundle:
    """The bundle is written BEFORE any ref is removed."""

    def test_bundle_contains_every_requested_branch(self, repo: Path) -> None:
        for name in ("one", "two"):
            _git(repo, "checkout", "main")
            _git(repo, "checkout", "-b", name)
            _commit(repo, f"{name}.txt", f"{name}\n", f"Add {name}")
        _git(repo, "checkout", "main")

        bundle = repo.parent / "multi.bundle"
        write_recovery_bundle(repo, ["one", "two"], bundle)

        listing = subprocess.run(  # nosec B603 B607 - trusted system tool, list form
            ["git", "bundle", "list-heads", str(bundle)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "one" in listing
        assert "two" in listing
