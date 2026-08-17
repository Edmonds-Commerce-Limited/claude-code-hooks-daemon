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
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.daemon.branch_safety import (
    REFUSAL_CURRENT_BRANCH,
    REFUSAL_NOT_A_BRANCH,
    REFUSAL_PROTECTED,
    REFUSAL_WORKTREE,
    TIER_CONTENT_PRESERVED,
    TIER_MERGED,
    TIER_MERGED_NOT_IN_HEAD,
    TIER_MERGED_UNPUSHED,
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


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A real bare repository to push to.

    Module-level because two test classes had byte-identical copies of it
    (Plan 00253). A real remote is not a convenience here: without
    `remote.origin.url` git cannot resolve `<name>@{upstream}` at all, falls back
    to comparing against HEAD, and the upstream fixtures silently stop reproducing
    the bug they exist for.
    """
    bare = tmp_path / "remote.git"
    subprocess.run(  # nosec B603 B607 - trusted system tool, list form
        ["git", "init", "--quiet", "--bare", str(bare)],
        check=True,
        capture_output=True,
        env={**_ENV, "HOME": str(tmp_path)},
    )
    return bare


def _merged_branch(repo: Path, name: str) -> None:
    _git(repo, "checkout", "-b", name)
    _commit(repo, f"{name}.txt", f"{name}\n", f"Add {name}")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--ff-only", name)


def _merged_but_head_is_elsewhere(repo: Path, name: str) -> None:
    """Merged into ``main``, no upstream, and HEAD left on ANOTHER branch.

    The state every existing fixture in this module structurally cannot produce:
    each returns to ``main`` before classifying, so ``HEAD`` always contains the
    branch under test and git's HEAD fallback is never exercised. Leaving HEAD on
    a branch that does NOT contain it is the whole point (Plan 00253).
    """
    _git(repo, "checkout", "-b", name)
    _commit(repo, f"{name}.txt", f"{name}\n", f"Add {name}")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "-m", f"Merge {name}", name)
    # A sibling branch rooted BEFORE the merge, so it cannot contain `name`.
    _git(repo, "checkout", "-b", f"{name}-elsewhere", "HEAD~1")


def _unproven_branch(repo: Path, name: str) -> None:
    _git(repo, "checkout", "-b", name)
    _commit(repo, f"{name}-only.txt", f"{name}\n", f"Unique work on {name}")
    _git(repo, "checkout", "main")


def _add_origin(repo: Path, remote: Path) -> None:
    """Register ``remote`` as ``origin``, idempotently."""
    if "origin" not in _git(repo, "remote").split():
        _git(repo, "remote", "add", "origin", str(remote))


def _merged_but_ahead_of_its_upstream(repo: Path, remote: Path, name: str) -> None:
    """Build the field-reported shape: in ``main``, ahead of ``origin/<name>``.

    A real remote and a real push, because the condition under test is one git
    evaluates against ``refs/remotes/origin/<name>`` — there is no way to
    synthesise that honestly. The branch is pushed (so it HAS an upstream), then
    given one further commit that is not pushed, then merged into ``main``
    locally. Every commit is therefore reachable from ``main`` while the
    remote-tracking ref sits one behind.
    """
    _add_origin(repo, remote)
    _git(repo, "checkout", "-b", name)
    _commit(repo, f"{name}.txt", f"{name}\n", f"Add {name}")
    # A real `push -u` through a real named remote. Hand-writing
    # `branch.<name>.remote` and the remote-tracking ref is NOT equivalent:
    # without `remote.origin.url` git cannot resolve `<name>@{upstream}` at all,
    # falls back to comparing against HEAD, and allows the delete — so the
    # fixture silently stops reproducing the bug. `test_the_fixture_reproduces_
    # gits_refusal` caught exactly that.
    _git(repo, "push", "--quiet", "--set-upstream", "origin", name)
    _commit(repo, f"{name}.txt", f"{name}\nsecond, unpushed\n", "Second commit, never pushed")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "-m", f"Merge {name}", name)


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


class TestMergedButAheadOfItsOwnUpstream:
    """Plan 00249: git's ``-d`` enforces a DIFFERENT predicate from ours.

    We prove *the tip is an ancestor of the protected ref* — a statement about
    recoverability. ``git branch -d`` enforces *merged into its upstream if it has
    one* — a statement about whether a push happened. Git's own refusal says so
    outright: "not yet merged to 'refs/remotes/origin/<name>', even though it is
    merged to HEAD".

    The consequence was the worst kind: ``--dry-run`` reported "nothing can be
    lost" and the real run then failed, so the two halves of the tool
    contradicted each other in front of a user.

    Nothing here is at risk. A commit ahead of the upstream AND absent from the
    protected ref would fail the ancestry test and never reach this tier, so
    within it every commit is reachable from the protected ref by construction.
    """

    def test_the_fixture_reproduces_gits_refusal(self, repo: Path, remote: Path) -> None:
        """Precondition. Without this the rest could pass on the wrong shape.

        Asserts BOTH halves of the contradiction on a real repository: our
        ancestry proof holds, and git's safe delete refuses anyway.
        """
        _merged_but_ahead_of_its_upstream(repo, remote, "shipped")

        ancestry = subprocess.run(  # nosec B603 B607 - trusted system tool, list form
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", "shipped", "main"],
            check=False,
            capture_output=True,
            env={**_ENV, "HOME": str(repo)},
        )
        refusal = subprocess.run(  # nosec B603 B607 - trusted system tool, list form
            ["git", "-C", str(repo), "branch", "--delete", "shipped"],
            check=False,
            capture_output=True,
            text=True,
            env={**_ENV, "HOME": str(repo)},
        )

        assert ancestry.returncode == 0, "fixture must be merged into the protected ref"
        assert refusal.returncode != 0, (
            "fixture no longer reproduces git's refusal, so every assertion "
            "below is about a shape that does not exist: " + refusal.stderr
        )
        assert "not yet merged to" in refusal.stderr

    def test_it_is_not_classified_as_plain_merged(self, repo: Path, remote: Path) -> None:
        """`merged` promises the SAFE delete will work. Here it will not."""
        _merged_but_ahead_of_its_upstream(repo, remote, "shipped")

        classification = classify_branch(repo, "shipped")

        assert classification.tier == TIER_MERGED_UNPUSHED

    def test_it_is_still_safe_to_delete(self, repo: Path, remote: Path) -> None:
        """The ancestry proof is unchanged, so the verdict must stay `safe`."""
        _merged_but_ahead_of_its_upstream(repo, remote, "shipped")

        assert classify_branch(repo, "shipped").is_safe is True

    def test_the_detail_names_the_condition_and_the_remedy(self, repo: Path, remote: Path) -> None:
        """A dry run has to say what the real run will do, and why."""
        _merged_but_ahead_of_its_upstream(repo, remote, "shipped")

        detail = classify_branch(repo, "shipped").detail

        assert "upstream" in detail
        assert "push" in detail.lower()

    def test_the_delete_actually_succeeds(self, repo: Path, remote: Path) -> None:
        """The bug the report opened with: the real run must not fail."""
        _merged_but_ahead_of_its_upstream(repo, remote, "shipped")

        report = delete_branches(repo, ["shipped"], bundle_path=None)

        assert report.refused is False, report.blockers
        assert report.deleted == ("shipped",)
        assert "shipped" not in _local_branches(repo)

    def test_a_branch_with_no_upstream_is_still_plain_merged(self, repo: Path) -> None:
        """The common case must not change: no upstream, no extra condition.

        Git's rule falls back to HEAD when a branch has no upstream, which our
        ancestry proof already covers — so this must keep delegating to the safe
        delete rather than quietly escalating every branch to a force delete.
        """
        _merged_branch(repo, "ordinary")

        assert classify_branch(repo, "ordinary").tier == TIER_MERGED
        assert delete_argv_for_tier(TIER_MERGED) == ("branch", "--delete")

    def test_a_branch_level_with_its_upstream_is_still_plain_merged(
        self, repo: Path, remote: Path
    ) -> None:
        """Having an upstream is not the condition — being AHEAD of it is."""
        _add_origin(repo, remote)
        _git(repo, "checkout", "-b", "level")
        _commit(repo, "level.txt", "level\n", "Add level")
        _git(repo, "push", "--quiet", "--set-upstream", "origin", "level")
        _git(repo, "checkout", "main")
        _git(repo, "merge", "--ff-only", "level")

        assert classify_branch(repo, "level").tier == TIER_MERGED


class TestNonAsciiPathsAreCountedCorrectly:
    """Plan 00253 finding F: two git commands were speaking different languages.

    `_paths_in_tree` reads `ls-tree` and `_paths_in_history` reads
    `rev-list --objects`, and the two are set-differenced against each other.
    `core.quotePath` defaults to ON, so `ls-tree` emitted `"caf\303\251.txt"`
    where `rev-list` emitted the raw bytes — for ANY non-ASCII path the difference
    could never be empty, and the "N path(s) are new" count in the message a human
    reads before abandoning work was wrong.

    Pre-existing, but it used to abort loudly (`UnicodeDecodeError` is a
    `ValueError`, which the CLI catches) and had become a silent miscount.
    """

    def test_the_two_listings_agree_on_a_non_ascii_path(self, repo: Path) -> None:
        """The set difference must be empty for a path present in both."""
        _commit(repo, "café.txt", "accented\n", "Add an accented path")

        in_tree = branch_safety._paths_in_tree(repo, "main")
        in_history = branch_safety._paths_in_history(repo, "main")

        assert "café.txt" in in_tree, f"ls-tree must not quote the path: {in_tree}"
        assert in_tree - in_history == set(), (
            "a path present in both listings must cancel out, or every "
            "unique-path count involving it is wrong: "
            f"tree={in_tree} history={in_history}"
        )

    def test_a_branch_adding_only_a_non_ascii_path_reports_exactly_one(self, repo: Path) -> None:
        """End to end: the COUNT the human reads has to be right."""
        _git(repo, "checkout", "-b", "accents")
        _commit(repo, "naïve.txt", "unique\n", "Add a genuinely new accented path")
        _git(repo, "checkout", "main")

        classification = classify_branch(repo, "accents")

        assert classification.unique_paths == ("naïve.txt",), classification.unique_paths

    def test_blob_paths_are_unquoted_too(self, repo: Path) -> None:
        """These paths are printed to a human, so they must be readable.

        The blob SHA is what the safety proof rests on, so quoting could never
        change the verdict — but a deny message listing `"caf\303\251.txt"` asks
        someone to recognise a file they have never seen spelled that way.
        """
        _commit(repo, "café.txt", "accented\n", "Add an accented path")

        assert "café.txt" in branch_safety._blobs_in_tree(repo, "main")


class TestMergedWhileHeadIsElsewhere:
    """Plan 00253: git's OTHER reference, and the axis Plan 00249 left open.

    Git applies one rule with two references, and the choice is exclusive: an
    upstream that resolves is used alone, and ``HEAD`` is the sole reference when
    none does. Plan 00249 closed the upstream axis and returned "git will accept
    it" for every upstream-less branch, on the grounds that git falls back to
    ``HEAD`` and our ancestry proof already covers that.

    It does not. Our proof is against ``protected_ref``, which is not ``HEAD``
    whenever another branch is checked out — an ordinary workflow, since tidying a
    merged branch usually happens from somewhere else. So ``--dry-run`` reported
    "nothing can be lost" and the real run failed: the same contradiction, on the
    other axis.

    Every reference in these assertions was established by executing real git, not
    read off the documentation.
    """

    def test_the_fixture_reproduces_gits_refusal(self, repo: Path) -> None:
        """Precondition. Without it the rest asserts a shape that does not exist."""
        _merged_but_head_is_elsewhere(repo, "done")

        ancestry = subprocess.run(  # nosec B603 B607 - trusted system tool, list form
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", "done", "main"],
            check=False,
            capture_output=True,
            env={**_ENV, "HOME": str(repo)},
        )
        refusal = subprocess.run(  # nosec B603 B607 - trusted system tool, list form
            ["git", "-C", str(repo), "branch", "--delete", "done"],
            check=False,
            capture_output=True,
            text=True,
            env={**_ENV, "HOME": str(repo)},
        )

        assert ancestry.returncode == 0, "fixture must be merged into the protected ref"
        assert refusal.returncode != 0, (
            "fixture no longer reproduces git's refusal, so every assertion "
            "below is about a shape that does not exist: " + refusal.stderr
        )
        assert "not fully merged" in refusal.stderr

    def test_it_is_not_classified_as_plain_merged(self, repo: Path) -> None:
        """`merged` promises the SAFE delete will work. Here it will not."""
        _merged_but_head_is_elsewhere(repo, "done")

        assert classify_branch(repo, "done").tier == TIER_MERGED_NOT_IN_HEAD

    def test_it_is_still_safe_to_delete(self, repo: Path) -> None:
        """The ancestry proof is untouched, so the verdict must stay `safe`."""
        _merged_but_head_is_elsewhere(repo, "done")

        assert classify_branch(repo, "done").is_safe is True

    def test_the_detail_blames_head_and_not_a_missing_push(self, repo: Path) -> None:
        """A wrong explanation is the defect, not a rounding error.

        Reusing `merged-unpushed` here would tell the user to push commits that
        have nothing to do with the refusal — and there is no upstream to push to.
        """
        _merged_but_head_is_elsewhere(repo, "done")

        detail = classify_branch(repo, "done").detail

        assert "HEAD" in detail
        assert "no upstream" in detail
        assert "push" not in detail.lower()

    def test_the_delete_actually_succeeds(self, repo: Path) -> None:
        """The dry run and the real run must now agree."""
        _merged_but_head_is_elsewhere(repo, "done")

        report = delete_branches(repo, ["done"], bundle_path=None)

        assert report.refused is False, report.blockers
        assert report.deleted == ("done",)
        assert "done" not in _local_branches(repo)

    def test_a_detached_head_is_the_same_case(self, repo: Path) -> None:
        """Verified against git: a detached HEAD refuses exactly as an attached one.

        `HEAD` resolves to the detached commit, so one expression covers both — but
        only a test proves the code did not special-case `symbolic-ref`.
        """
        _git(repo, "checkout", "-b", "done")
        _commit(repo, "done.txt", "done\n", "Add done")
        _git(repo, "checkout", "main")
        _git(repo, "merge", "--no-ff", "-m", "Merge done", "done")
        _git(repo, "checkout", "--detach", "HEAD~1")

        classification = classify_branch(repo, "done")

        assert classification.tier == TIER_MERGED_NOT_IN_HEAD
        assert classification.is_safe is True

    def test_an_upstream_takes_precedence_over_head(self, repo: Path, remote: Path) -> None:
        """When an upstream resolves, git ignores HEAD entirely.

        Executed against real git: a branch level with `origin/<name>` is deleted
        with only a "has been merged to" warning even while absent from HEAD. So
        this must stay plain `merged` — escalating it to a force delete would give
        up git's independent re-check for no reason.
        """
        _add_origin(repo, remote)
        _git(repo, "checkout", "-b", "level")
        _commit(repo, "level.txt", "level\n", "Add level")
        _git(repo, "push", "--quiet", "--set-upstream", "origin", "level")
        _git(repo, "checkout", "main")
        _git(repo, "merge", "--no-ff", "-m", "Merge level", "level")
        _git(repo, "checkout", "-b", "elsewhere", "HEAD~1")

        assert classify_branch(repo, "level").tier == TIER_MERGED
        assert delete_argv_for_tier(TIER_MERGED) == ("branch", "--delete")

    def test_the_common_case_is_untouched(self, repo: Path) -> None:
        """HEAD on the protected ref must still delegate to git's safe delete."""
        _merged_branch(repo, "ordinary")

        assert classify_branch(repo, "ordinary").tier == TIER_MERGED

    def test_an_upstream_that_tracks_head_is_resolved_at_classification_time(
        self, repo: Path
    ) -> None:
        """`branch.<name>.merge = HEAD` means "whatever HEAD points at NOW".

        Found while probing this fix and worth pinning, because it briefly looked
        like a residual disagreement: resolving the upstream BEFORE moving HEAD
        gives one answer and resolving it after gives another. Git evaluates it at
        delete time, so this code must evaluate it at classification time — which it
        does, since `_safe_delete_reference` asks git rather than caching. Once both
        are read at the same moment they agree, and git refuses exactly when the
        predicate is False.
        """
        _git(repo, "config", "--local", "branch.tracks-head.remote", ".")
        _git(repo, "checkout", "-b", "tracks-head")
        _commit(repo, "tracks-head.txt", "x\n", "Add tracks-head")
        _git(repo, "checkout", "main")
        _git(repo, "merge", "--no-ff", "-m", "Merge tracks-head", "tracks-head")
        _git(repo, "config", "--local", "branch.tracks-head.merge", "HEAD")
        _git(repo, "checkout", "-b", "elsewhere", "HEAD~1")

        classification = classify_branch(repo, "tracks-head")
        refusal = subprocess.run(  # nosec B603 B607 - trusted system tool, list form
            ["git", "-C", str(repo), "branch", "--delete", "tracks-head"],
            check=False,
            capture_output=True,
            text=True,
            env={**_ENV, "HOME": str(repo)},
        )

        assert refusal.returncode != 0, "git must refuse the safe delete here"
        assert classification.tier != TIER_MERGED, (
            "so the classifier must NOT promise the safe delete will work: "
            f"{classification.tier}"
        )
        assert classification.is_safe is True, "the ancestry proof is unaffected"


class TestAGitRefusalMidBatchIsReportedNotRaised:
    """Plan 00249: git can refuse on grounds this engine does not model.

    The engine cannot enumerate every condition a future git might enforce, so
    the requirement is not "never be refused" — it is "when refused, say so
    accurately". Previously the refusal raised out of the loop, past a CLI that
    caught only ``ValueError``, and reached the user as a stack trace.

    The refusal here is provoked with REAL git rather than a mock: patching
    ``delete_argv_for_tier`` back to the safe delete for a merged-unpushed branch
    reproduces exactly the pre-fix argv, and git refuses it for its own reasons.
    """

    @staticmethod
    def _force_the_safe_delete() -> Any:
        """Make the engine use the argv git will refuse, as it did before."""
        return patch.object(
            branch_safety, "delete_argv_for_tier", lambda _tier: ("branch", "--delete")
        )

    def test_the_refusal_is_reported_with_gits_own_words(self, repo: Path, remote: Path) -> None:
        _merged_but_ahead_of_its_upstream(repo, remote, "shipped")

        with self._force_the_safe_delete():
            report = delete_branches(repo, ["shipped"], bundle_path=None)

        assert report.refused is True
        assert report.deleted == ()
        assert "shipped" in _local_branches(repo), "a refused delete must change nothing"
        assert any("not yet merged to" in blocker for blocker in report.blockers), report.blockers

    def test_the_blocker_names_the_tier_that_was_proven(self, repo: Path, remote: Path) -> None:
        """Without the tier the message says only that git said no."""
        _merged_but_ahead_of_its_upstream(repo, remote, "shipped")

        with self._force_the_safe_delete():
            report = delete_branches(repo, ["shipped"], bundle_path=None)

        assert any(TIER_MERGED_UNPUSHED in blocker for blocker in report.blockers), report.blockers

    def test_a_partial_batch_reports_exactly_what_went(self, repo: Path, remote: Path) -> None:
        """The docstring used to promise all-or-nothing; a ref cannot be un-deleted.

        So the requirement is an honest report: whatever was removed is listed,
        the rest is a blocker, and ``refused`` is set.
        """
        _merged_branch(repo, "ordinary")
        _merged_but_ahead_of_its_upstream(repo, remote, "shipped")

        with self._force_the_safe_delete():
            report = delete_branches(repo, ["ordinary", "shipped"], bundle_path=None)

        assert report.deleted == ("ordinary",)
        assert report.refused is True
        assert "ordinary" not in _local_branches(repo)
        assert "shipped" in _local_branches(repo)

    def test_a_bundle_is_removed_when_nothing_was_deleted(self, repo: Path, remote: Path) -> None:
        """An orphaned bundle reads as evidence a branch is gone.

        The field report found a real 1.9 MB one left behind by the crash.
        """
        _merged_but_ahead_of_its_upstream(repo, remote, "shipped")
        bundle_path = repo.parent / "recovery.bundle"

        with self._force_the_safe_delete():
            report = delete_branches(repo, ["shipped"], bundle_path=bundle_path)

        assert report.refused is True
        assert not bundle_path.exists(), "a run that deleted nothing must leave no bundle"
        assert report.bundle is None, "the report must not name a bundle that is gone"

    def test_a_bundle_that_cannot_be_removed_is_reported_not_swallowed(
        self, repo: Path, remote: Path
    ) -> None:
        """A failed tidy-up must reach the person running the command.

        Logging it and continuing would hide it in a log nobody opens — and the
        stale file is exactly the thing the field report says a later reader
        misinterprets. This module reports outcomes through ``blockers``, so that
        is where it goes.
        """
        _merged_but_ahead_of_its_upstream(repo, remote, "shipped")
        bundle_path = repo.parent / "recovery.bundle"

        with self._force_the_safe_delete():
            with patch.object(Path, "unlink", side_effect=OSError("read-only file system")):
                report = delete_branches(repo, ["shipped"], bundle_path=bundle_path)

        assert report.refused is True
        assert any(
            "read-only file system" in blocker for blocker in report.blockers
        ), report.blockers
        assert any(
            "NOT evidence of a deletion" in blocker for blocker in report.blockers
        ), report.blockers
        assert report.bundle == bundle_path, "the bundle is still there, so still report it"

    def test_a_bundle_is_KEPT_when_something_was_deleted(self, repo: Path, remote: Path) -> None:
        """A partial deletion is exactly when the recovery route matters."""
        _merged_branch(repo, "ordinary")
        _merged_but_ahead_of_its_upstream(repo, remote, "shipped")
        bundle_path = repo.parent / "recovery.bundle"

        with self._force_the_safe_delete():
            report = delete_branches(repo, ["ordinary", "shipped"], bundle_path=bundle_path)

        assert report.deleted == ("ordinary",)
        assert bundle_path.exists(), "the deleted branch's only recovery route was removed"
        assert report.bundle == bundle_path


class TestBudgetsSuitTheWorkNotTheHookContext:
    """Plan 00248 F1: this module must not run on a hook-context budget.

    Its runner passed NO timeout before the Plan 00246 migration, deliberately:
    ``bundle create`` packs objects, ``cherry`` computes a patch-id per commit,
    and ``rev-list --objects`` walks every tree and blob in a ref. Migrating it
    to the central runner silently imposed the CENTRE's default —
    ``GIT_CONTEXT``, five seconds, a budget named for gathering context during a
    hook — on all of them.

    The consequence is not a slow command but a broken one: past the budget
    ``run_git`` returns 127, ``_git`` raises ``CalledProcessError``, and the
    human-gated delete refuses nothing and explains nothing, it traces back. No
    existing test could see it, because every fixture repo here is tiny.

    These assert the BUDGET rather than provoking a real timeout: manufacturing a
    repository big enough to exceed five seconds would add minutes to the suite
    to prove something a constant states exactly.
    """

    def test_the_module_runner_does_not_use_the_hook_context_budget(self) -> None:
        from unittest.mock import patch

        with patch(
            "claude_code_hooks_daemon.daemon.branch_safety.run_git",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ) as spawn:
            branch_safety._git(Path("/nonexistent"), "for-each-ref", check=False)

        budget = spawn.call_args.kwargs["timeout"]
        assert budget != Timeout.GIT_CONTEXT, (
            "branch_safety inherited the 5s hook-context budget for operations "
            "that pack objects and walk every blob in a ref — see Plan 00248 F1"
        )
        assert budget >= Timeout.GIT_BRANCH_SAFETY

    def test_the_bundle_call_actually_receives_the_larger_budget(self, repo: Path) -> None:
        """The bundle is the heaviest call AND the one that must not be killed.

        It is written before any ref is removed, so it is the only copy of the
        work if the delete proceeds. A budget that kills it mid-pack leaves a
        truncated bundle where a recovery is supposed to be.

        This SPIES ON THE CALL rather than comparing the two constants. The
        original asserted only ``GIT_BUNDLE_CREATE > GIT_BRANCH_SAFETY``, which
        held no matter what the call site passed — verified by execution:
        downgrading the ``timeout=`` at the bundle call left 64 tests passing while
        the docstring there called it the one call "that must not be killed
        part-way" (Plan 00253 finding C). Same spy shape as
        ``tests/unit/core/test_claude_md_injector.py``.
        """
        _merged_branch(repo, "spent")
        real = branch_safety.run_git
        timeouts: dict[str, float] = {}

        def spy(
            cwd: Path, *args: str, timeout: float = Timeout.GIT_BRANCH_SAFETY
        ) -> subprocess.CompletedProcess[str]:
            if args:
                timeouts[args[0]] = timeout
            return real(cwd, *args, timeout=timeout)

        with patch.object(branch_safety, "run_git", spy):
            write_recovery_bundle(repo, ["spent"], repo.parent / "budget.bundle")

        assert "bundle" in timeouts, (
            "precondition: the bundle call must reach run_git, or this test "
            "proves nothing: " + repr(timeouts)
        )
        assert timeouts["bundle"] == Timeout.GIT_BUNDLE_CREATE, (
            "the bundle PACKS objects and is the only copy of the work once the "
            "delete proceeds, so it must not inherit the read budget: " + repr(timeouts)
        )
        assert (
            Timeout.GIT_BUNDLE_CREATE > Timeout.GIT_BRANCH_SAFETY
        ), "and that budget must actually be the larger of the two"

    def test_a_timed_out_bundle_raises_for_the_cli_to_convert(self, repo: Path) -> None:
        """A budget overrun must reach the CLI as an exception it can catch.

        Renamed from "...is_reported_as_a_refusal", which described something this
        test does not assert (Plan 00253 finding D): the refusal conversion lives at
        the CLI boundary, and deleting that ``except`` clause left this test green.
        What it does assert — and what the CLI's contract depends on — is that
        ``run_git``'s returncode 127 arrives here as ``CalledProcessError`` rather
        than as a silent success. The conversion itself is covered by
        ``tests/unit/daemon/test_cli_delete_branch.py``'s
        ``TestAGitFailureIsARefusalNotATraceback``.
        """
        _merged_branch(repo, "spent")
        timed_out = subprocess.CompletedProcess(["git"], 127, "", "timed out")

        with patch(
            "claude_code_hooks_daemon.daemon.branch_safety.run_git",
            return_value=timed_out,
        ):
            with pytest.raises(subprocess.CalledProcessError):
                write_recovery_bundle(repo, ["spent"], repo.parent / "x.bundle")
