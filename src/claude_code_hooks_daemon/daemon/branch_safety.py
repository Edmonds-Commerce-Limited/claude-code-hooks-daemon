"""Deterministic proof engine for safe local-branch deletion (Plan 00206).

``destructive_git`` blocks the force branch delete because it destroys a branch
without checking anything. Git's own safe delete refuses any branch whose tip is
not an ancestor of a protected ref — which, after a history rewrite, is *every*
branch. Between the two sits a large class of branches that legitimately need
deleting and have no route to it but escalation to a human.

This module supplies the missing route. It never relaxes the guard: it performs
strictly MORE verification than the flag it replaces, refuses by default, and
deletes only what it can positively prove is recoverable.

Four tiers, evaluated cheapest-first and short-circuiting on the first that
holds:

``merged``
    The tip is an ancestor of the protected ref. Nothing can be lost. This is
    what git's own safe delete proves.

``patch-equivalent``
    Every commit's diff is already upstream by patch-id, even though no sha
    matches. This is the shape a history rewrite produces, and it is the tier
    git has no built-in check for.

``content-preserved``
    Every file version on the branch is byte-identical to a blob still
    reachable from the protected ref. Commits and paths differ; bytes do not.
    This is the common shape of a genuinely stale branch, and neither of the
    tiers above detects it.

``unproven``
    Everything else. Reported with the files whose CONTENT exists nowhere else,
    so the decision is informed rather than blind.

The proof is deliberately blob identity and never path presence. A path
existing in the protected ref's history says nothing about the content at that
path, so a path-level tier could approve a deletion that destroys the only copy
of a file version. Path-level uniqueness is still reported, but only as context
— a new path whose bytes already exist upstream loses nothing, and conflating
the two makes an alarming path count look like data loss when it is not.
"""

from __future__ import annotations

import subprocess  # nosec B404 - trusted system tool (git), list form, no shell
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# Human gate for an ``unproven`` deletion: given the classifications and the
# stated reason, return whether a person consented. Injected rather than called
# directly so the policy is testable without a terminal.
ConfirmCallback = Callable[[Sequence["BranchClassification"], str], bool]

# Proof tiers, strongest first.
TIER_MERGED = "merged"
TIER_PATCH_EQUIVALENT = "patch-equivalent"
TIER_CONTENT_PRESERVED = "content-preserved"
TIER_UNPROVEN = "unproven"

# Blocking preconditions. A refusal is absolute — no tier is computed, and
# ``allow_unproven`` cannot override it.
REFUSAL_CURRENT_BRANCH = "current-branch"
REFUSAL_WORKTREE = "checked-out-in-worktree"
REFUSAL_PROTECTED = "protected-branch"
REFUSAL_NOT_A_BRANCH = "not-a-local-branch"

# Branch names never deletable by this command regardless of proof.
DEFAULT_PROTECTED_NAMES: tuple[str, ...] = ("main", "master", "develop", "trunk")

# The ref every proof is measured against.
DEFAULT_PROTECTED_REF = "main"

# ``git cherry`` marks a commit whose patch-id is absent upstream with this.
_CHERRY_UNIQUE_MARKER = "+"

# ``git ls-tree`` emits "<mode> <type> <sha>\t<path>" — three metadata fields
# before the tab.
_LS_TREE_META_FIELDS = 3


def delete_argv_for_tier(tier: str | None) -> tuple[str, ...]:
    """Git flags used to delete a branch proven at ``tier``.

    A ``merged`` branch is removed with the SAFE lowercase delete, never the
    force flag. Git then re-runs its own merged-ancestry check independently of
    ours, so a bug in ``classify_branch`` cannot cause a silent loss — git
    simply refuses and the command fails loudly. Prefer the battle-tested check
    wherever it is capable of doing the job.

    The remaining tiers describe branches git will always call unmerged
    (a rewrite or a squash merge severs ancestry), so there the force flag is
    unavoidable — and it is exactly there that our extra proof has to earn its
    keep, because nothing else is checking.
    """
    if tier == TIER_MERGED:
        return ("branch", "--delete")
    return ("branch", "--delete", "--force")


_REFUSAL_DETAIL = {
    REFUSAL_CURRENT_BRANCH: "is the currently checked-out branch",
    REFUSAL_WORKTREE: "is checked out in a linked worktree",
    REFUSAL_PROTECTED: "is a protected branch name",
    REFUSAL_NOT_A_BRANCH: "does not resolve to a local branch",
}

_TIER_DETAIL = {
    TIER_MERGED: "tip is an ancestor of the protected ref — nothing can be lost",
    TIER_PATCH_EQUIVALENT: (
        "every commit is already upstream by patch-id — the shape a history " "rewrite produces"
    ),
    TIER_CONTENT_PRESERVED: (
        "every file version on this branch is byte-identical to one still "
        "reachable from the protected ref — only the arrangement differs"
    ),
}


@dataclass(frozen=True)
class BranchClassification:
    """The verdict for one branch, carrying the evidence behind it."""

    name: str
    tier: str | None = None
    refusal: str | None = None
    unique_paths: tuple[str, ...] = ()
    content_unique_paths: tuple[str, ...] = ()
    unique_commits: int = 0
    detail: str = ""

    @property
    def is_safe(self) -> bool:
        """True only when a proof tier was reached and nothing refused it."""
        return self.refusal is None and self.tier in (
            TIER_MERGED,
            TIER_PATCH_EQUIVALENT,
            TIER_CONTENT_PRESERVED,
        )


@dataclass(frozen=True)
class DeletionReport:
    """The outcome of a delete request across every requested branch."""

    classifications: tuple[BranchClassification, ...] = ()
    deleted: tuple[str, ...] = ()
    bundle: Path | None = None
    refused: bool = False
    blockers: tuple[str, ...] = field(default_factory=tuple)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git in ``repo``.

    SECURITY: fixed argv list, never a shell string, and the binary is the
    trusted system git. Branch names arrive as separate argv entries so a name
    containing shell metacharacters cannot be interpreted.
    """
    return subprocess.run(  # nosec B603 B607 - trusted system tool, list form
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def current_branch(repo: Path) -> str | None:
    """Return the checked-out branch name, or None on a detached HEAD."""
    result = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    name = result.stdout.strip()
    return name or None


def local_branches(repo: Path) -> set[str]:
    """Every local branch name in ``repo``."""
    result = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    return {line for line in result.stdout.splitlines() if line}


def worktree_branches(repo: Path) -> set[str]:
    """Branch names checked out in any linked worktree (including the main one).

    A branch checked out elsewhere cannot be deleted, and discovering that by
    letting git fail would conflate it with every other failure.
    """
    result = _git(repo, "worktree", "list", "--porcelain")
    names: set[str] = set()
    for line in result.stdout.splitlines():
        if line.startswith("branch "):
            ref = line.split(" ", 1)[1].strip()
            names.add(ref.removeprefix("refs/heads/"))
    return names


def _unique_commit_count(repo: Path, name: str, protected_ref: str) -> int:
    """Commits on ``name`` whose patch-id is not already upstream."""
    result = _git(repo, "cherry", protected_ref, name, check=False)
    return sum(1 for line in result.stdout.splitlines() if line.startswith(_CHERRY_UNIQUE_MARKER))


def _paths_in_tree(repo: Path, ref: str) -> set[str]:
    """Every path present in ``ref``'s tip tree."""
    result = _git(repo, "ls-tree", "-r", "--name-only", ref, check=False)
    return {line for line in result.stdout.splitlines() if line}


def _blobs_in_tree(repo: Path, ref: str) -> dict[str, str]:
    """Map every path in ``ref``'s tip tree to its blob sha.

    Blob sha IS content identity in git: two files with the same sha are
    byte-identical no matter where they sit or how they got there.
    """
    result = _git(repo, "ls-tree", "-r", ref, check=False)
    blobs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) == _LS_TREE_META_FIELDS and parts[1] == "blob" and path:
            blobs[path] = parts[2]
    return blobs


def _reachable_object_shas(repo: Path, ref: str) -> set[str]:
    """Every object sha reachable from ``ref``, including long-deleted blobs."""
    result = _git(repo, "rev-list", "--objects", ref, check=False)
    shas: set[str] = set()
    for line in result.stdout.splitlines():
        sha = line.partition(" ")[0]
        if sha:
            shas.add(sha)
    return shas


def _paths_in_history(repo: Path, ref: str) -> set[str]:
    """Every path that has EVER existed anywhere in ``ref``'s history.

    ``rev-list --objects`` emits ``<sha> <path>`` for every tree and blob
    reachable from the ref, which covers paths deleted long ago — the tip tree
    alone would report them as unique to the branch.
    """
    result = _git(repo, "rev-list", "--objects", ref, check=False)
    paths: set[str] = set()
    for line in result.stdout.splitlines():
        _, _, path = line.partition(" ")
        if path:
            paths.add(path)
    return paths


def classify_branch(
    repo: Path,
    name: str,
    *,
    protected_ref: str = DEFAULT_PROTECTED_REF,
    protected_names: Sequence[str] = DEFAULT_PROTECTED_NAMES,
) -> BranchClassification:
    """Classify one branch, returning its tier or the reason it is refused."""
    if name not in local_branches(repo):
        return BranchClassification(
            name=name,
            refusal=REFUSAL_NOT_A_BRANCH,
            detail=_REFUSAL_DETAIL[REFUSAL_NOT_A_BRANCH],
        )
    if name == current_branch(repo):
        return BranchClassification(
            name=name,
            refusal=REFUSAL_CURRENT_BRANCH,
            detail=_REFUSAL_DETAIL[REFUSAL_CURRENT_BRANCH],
        )
    if name in protected_names:
        return BranchClassification(
            name=name,
            refusal=REFUSAL_PROTECTED,
            detail=_REFUSAL_DETAIL[REFUSAL_PROTECTED],
        )
    if name in worktree_branches(repo):
        return BranchClassification(
            name=name,
            refusal=REFUSAL_WORKTREE,
            detail=_REFUSAL_DETAIL[REFUSAL_WORKTREE],
        )

    ancestor = _git(repo, "merge-base", "--is-ancestor", name, protected_ref, check=False)
    if ancestor.returncode == 0:
        return BranchClassification(name=name, tier=TIER_MERGED, detail=_TIER_DETAIL[TIER_MERGED])

    unique_commits = _unique_commit_count(repo, name, protected_ref)
    if unique_commits == 0:
        return BranchClassification(
            name=name,
            tier=TIER_PATCH_EQUIVALENT,
            detail=_TIER_DETAIL[TIER_PATCH_EQUIVALENT],
        )

    # Commit-level uniqueness does not imply content loss: a stale branch is
    # usually byte-identical to the protected ref and merely arranged
    # differently. Compare blob shas, which ARE content identity in git.
    branch_blobs = _blobs_in_tree(repo, name)
    reachable = _reachable_object_shas(repo, protected_ref)
    content_unique_paths = tuple(
        sorted(path for path, sha in branch_blobs.items() if sha not in reachable)
    )
    if not content_unique_paths:
        return BranchClassification(
            name=name,
            tier=TIER_CONTENT_PRESERVED,
            unique_commits=unique_commits,
            detail=_TIER_DETAIL[TIER_CONTENT_PRESERVED],
        )

    unique_paths = tuple(
        sorted(_paths_in_tree(repo, name) - _paths_in_history(repo, protected_ref))
    )
    return BranchClassification(
        name=name,
        tier=TIER_UNPROVEN,
        unique_paths=unique_paths,
        content_unique_paths=content_unique_paths,
        unique_commits=unique_commits,
        detail=(
            f"{unique_commits} commit(s) not upstream by patch-id; "
            f"{len(content_unique_paths)} file(s) hold content found nowhere "
            f"in {protected_ref} ({len(unique_paths)} path(s) are new, but a "
            f"new path whose bytes already exist in {protected_ref} loses "
            f"nothing)"
        ),
    )


def write_recovery_bundle(repo: Path, names: Sequence[str], bundle_path: Path) -> Path:
    """Bundle every named branch so a deletion can be undone.

    Written BEFORE any ref is removed, so a failure here aborts the deletion
    rather than leaving branches gone and no way back.
    """
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "bundle", "create", str(bundle_path), *names)
    return bundle_path


def delete_branches(
    repo: Path,
    names: Sequence[str],
    *,
    protected_ref: str = DEFAULT_PROTECTED_REF,
    protected_names: Sequence[str] = DEFAULT_PROTECTED_NAMES,
    allow_unproven: bool = False,
    reason: str | None = None,
    bundle_path: Path | None = None,
    dry_run: bool = False,
    confirm: ConfirmCallback | None = None,
) -> DeletionReport:
    """Classify every branch, then delete all of them or none.

    All-or-nothing is deliberate: a partial deletion leaves the caller unsure
    which half happened, and the batch is normally one logical cleanup.

    Args:
        allow_unproven: permit ``unproven`` branches. Never overrides a blocking
            precondition — those refuse regardless.
        reason: mandatory when ``allow_unproven`` is set, so an unproven
            deletion always carries its rationale.
        confirm: HUMAN gate, required before any ``unproven`` branch is deleted.
            Receives the classifications and the stated reason, and returns
            whether to proceed. Absent or returning False, the deletion is
            refused. Every other tier is a proof that can be checked
            mechanically; ``unproven`` is the one path that knowingly destroys
            unmerged work, so it must not be reachable by an agent passing
            another flag. A declared reason asserts intent — it does not gate.

    Raises:
        ValueError: if ``allow_unproven`` is set without a reason.
    """
    if allow_unproven and not (reason or "").strip():
        raise ValueError(
            "allow_unproven requires a reason explaining why the unique content "
            "on these branches may be destroyed"
        )

    classifications = tuple(
        classify_branch(repo, name, protected_ref=protected_ref, protected_names=protected_names)
        for name in names
    )

    blockers = tuple(
        f"{c.name}: {c.detail}"
        for c in classifications
        if c.refusal is not None or (c.tier == TIER_UNPROVEN and not allow_unproven)
    )
    if blockers:
        return DeletionReport(classifications=classifications, refused=True, blockers=blockers)

    if dry_run:
        return DeletionReport(classifications=classifications)

    # Abandonment is a human's call. Reaching here with an ``unproven`` branch
    # means an agent asserted intent, and asserting intent is not consenting.
    abandoning = [c for c in classifications if c.tier == TIER_UNPROVEN]
    if abandoning:
        if confirm is None:
            return DeletionReport(
                classifications=classifications,
                refused=True,
                blockers=(
                    f"deleting unmerged work on {len(abandoning)} branch(es) needs a "
                    "human, and no confirmation channel was available — ask the user "
                    "to run this command themselves in a terminal",
                ),
            )
        if not confirm(classifications, reason or ""):
            return DeletionReport(
                classifications=classifications,
                refused=True,
                blockers=("a human was asked and declined the deletion",),
            )

    bundle: Path | None = None
    if bundle_path is not None:
        bundle = write_recovery_bundle(repo, [c.name for c in classifications], bundle_path)

    for classification in classifications:
        # Defer to git's own check whenever it is capable of making it.
        _git(repo, *delete_argv_for_tier(classification.tier), classification.name)

    return DeletionReport(
        classifications=classifications,
        deleted=tuple(c.name for c in classifications),
        bundle=bundle,
    )
