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

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import branch_ref, run_git, strip_branch_ref

# Human gate for an ``unproven`` deletion: given the classifications and the
# stated reason, return whether a person consented. Injected rather than called
# directly so the policy is testable without a terminal.
ConfirmCallback = Callable[[Sequence["BranchClassification"], str], bool]

# Proof tiers, strongest first.
TIER_MERGED = "merged"
TIER_PATCH_EQUIVALENT = "patch-equivalent"
TIER_CONTENT_PRESERVED = "content-preserved"
TIER_UNPROVEN = "unproven"
#: Merged into the protected ref, but AHEAD of its own remote-tracking ref.
#: Same ancestry proof as ``merged``; a separate tier only because git's safe
#: delete refuses it, so it needs a different flag and a different explanation
#: (Plan 00249).
TIER_MERGED_UNPUSHED = "merged-unpushed"
#: Merged into the protected ref, has NO upstream, and is not an ancestor of
#: ``HEAD`` — so git measures it against HEAD and refuses. Same ancestry proof as
#: ``merged`` again; a THIRD name rather than a widened ``merged-unpushed``
#: because no push is involved and saying otherwise would be the kind of
#: inaccurate label this tier exists to remove (Plan 00253).
TIER_MERGED_NOT_IN_HEAD = "merged-not-in-head"

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

# The reference git's safe delete falls back to when a branch has no upstream.
# Named because `_tier_for_merged_branch` compares against it to decide WHICH
# refusal reason to report, and the two must not drift apart.
_HEAD_REF = "HEAD"

# `core.quotePath` defaults to ON, so `ls-tree` emits `"caf\303\251.txt"` while
# `rev-list --objects` emits the raw bytes. The two are set-differenced against
# each other, so for ANY non-ASCII path they could never match and the "N path(s)
# are new" count was wrong (Plan 00253 finding F). Disabling it on the `ls-tree`
# side makes both listings speak the same language. Verified by execution: the two
# outputs are byte-identical with this set.
_NO_QUOTE_PATH: tuple[str, ...] = ("-c", "core.quotePath=false")

#: Abbreviation width for shas quoted in a blocker. Full shas make the message
#: unreadable; git's own default short form is this long.
_SHA_DISPLAY_LEN = 7

#: Appended when a branch moved between its proof and its delete. Deliberately
#: NOT `_REFUSAL_DIAGNOSIS`: that one tells the reader our model of git's delete
#: rule disagreed with git and sends them to inspect the predicate. This is an
#: ordinary concurrent edit — the predicate was correct when it ran — so pointing
#: at the predicate would aim them at the wrong thing entirely.
#:
#: Says "changed", not "advanced": a peer that DELETES the branch mid-run reaches
#: this same path, and "advanced" would have been simply false there. Found by
#: exercising that branch of the guard rather than by reading it.
_MOVED_TIP_DIAGNOSIS = (
    "Another process changed this branch after it was proved safe, so the proof no "
    "longer describes it and the recovery bundle — written before the delete loop — "
    "does NOT cover the change. Nothing was deleted for this branch. Re-run to "
    "reclassify against the current tip; do not force the delete to get past it."
)

# Appended to every "git refused the delete" blocker. Once the predicate mirrors
# git's rule on BOTH axes (Plan 00249 upstream, Plan 00253 HEAD), a refusal at
# this point means our model of git's own rule disagreed with git — and there are
# exactly two ways that happens. Reporting the FACT without the DIAGNOSIS makes
# every occurrence a puzzle instead of a bug report, so the text names both causes
# and how to tell them apart.
#
# The concurrent case is REPRODUCED, not theorised: advancing a branch with an
# unmerged commit between `classify_branch` and the delete makes git refuse, and
# the bundle was written before that commit existed, so its head predates the
# peer's work. That is why the advice is to re-run rather than to force.
#
# Plan 00254 narrowed which causes can still reach here. `tip_moved_since_proof`
# now checks the BRANCH's own sha before git is asked, so a moved branch is
# normally refused earlier with `_MOVED_TIP_DIAGNOSIS` instead — it can only reach
# git's refusal by moving inside the residual window between that check and the
# delete. A moved UPSTREAM is not covered by that check at all (it compares the
# branch, not its remote-tracking ref), so it remains a live cause here.
_REFUSAL_DIAGNOSIS = (
    "This means our model of git's delete rule disagreed with git. Either its "
    "UPSTREAM moved since this branch was classified — or the branch itself did, in "
    "the moment between the tip re-check and this delete — which means a concurrent "
    "agent in this checkout, so re-run; note the recovery bundle predates that "
    "change, so it does NOT cover work added since. Otherwise this is a gap in the "
    "daemon's predicate and is worth reporting upstream. Do not force the delete to "
    "get past it."
)


def tip_moved_since_proof(repo: Path, classification: BranchClassification) -> str | None:
    """A blocker if the branch no longer points where its proof was made, else None.

    A tier is a statement about a COMMIT, not about a name, so it expires the
    instant the branch moves. Between the two there is a real window: one recovery
    bundle is written for the whole batch before the delete loop, and
    ``git bundle create`` PACKS objects — the reason that call carries a 300 s
    budget — so on a large repository the exposure is the length of a pack. A
    commit arriving inside it is covered by neither the proof nor the bundle, and
    on the four tiers that force the delete git checks nothing, so the loss is
    silent (Plan 00254).

    Applied to EVERY tier rather than only the forcing ones. "Never delete a ref
    whose value differs from the one the proof was made against" needs no reader to
    know which tiers force, and on ``merged`` it replaces git's generic "not fully
    merged" with a message naming both shas.

    This narrows the window to a single git invocation; it does not close it.
    ``git update-ref -d <ref> <expected-sha>`` would, being a compare-and-swap, but
    it bypasses the checks git's own branch deletes make at DELETE time — notably
    the refusal to remove a branch checked out in a linked worktree, which a peer
    can create after classification WITHOUT moving the tip, making it invisible to
    this check. Keeping git's own delete keeps every such check; see Plan 00254
    Decision 1.
    """
    if not classification.tip:
        return None
    current = _git(repo, "rev-parse", branch_ref(classification.name), check=False)
    now = current.stdout.strip() if current.returncode == 0 else ""
    if now == classification.tip:
        return None
    return (
        f"{classification.name}: the branch moved after it was proved safe — "
        f"classified against {classification.tip[:_SHA_DISPLAY_LEN]}, "
        f"now at {now[:_SHA_DISPLAY_LEN] or '(no longer a branch)'}"
        f"\n      {_MOVED_TIP_DIAGNOSIS}"
    )


def delete_argv_for_tier(tier: str | None) -> tuple[str, ...]:
    """Git flags used to delete a branch proven at ``tier``.

    A ``merged`` branch is removed with the SAFE lowercase delete, never the
    force flag. Git then re-runs its own merged-ancestry check independently of
    ours, so a bug in ``classify_branch`` cannot cause a silent loss — git
    simply refuses and the command fails loudly. Prefer the battle-tested check
    wherever it is capable of doing the job.

    ``merged-unpushed`` and ``merged-not-in-head`` are the two cases where it is
    NOT capable of doing the job, and the distinction is worth stating precisely.
    Git's ``-d`` does not run our check: it measures the branch against its
    upstream when one RESOLVES, and against ``HEAD`` when none does. So it refuses
    a branch fully contained in the protected ref that is either ahead of its own
    remote-tracking ref — its warning says so, "even though it is merged to HEAD"
    (Plan 00249) — or absent from the checked-out ``HEAD`` while having no
    upstream at all (Plan 00253). Those are statements about whether a PUSH
    happened and about where ``HEAD`` is standing; neither is about whether
    anything can be lost. The ancestry proof for both tiers is identical to
    ``merged``: every commit is reachable from the protected ref, so a commit
    absent from it would have failed that test and never arrived here.

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
    TIER_MERGED_UNPUSHED: (
        "tip is an ancestor of the protected ref — nothing can be lost — but the "
        "branch is ahead of its own upstream, so git's safe delete refuses it "
        "until those commits are pushed; deleting is still lossless because they "
        "are already in the protected ref"
    ),
    TIER_MERGED_NOT_IN_HEAD: (
        "tip is an ancestor of the protected ref — nothing can be lost — but it "
        "has no upstream and is not an ancestor of the checked-out HEAD, which is "
        "what git's safe delete measures it against, so git refuses it; deleting "
        "is still lossless because every commit is already in the protected ref"
    ),
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
    #: The sha this verdict was proved against, "" when the branch does not
    #: resolve. A proof is a statement about a COMMIT, so it expires the moment
    #: the branch moves — `delete_branches` re-reads this before deleting.
    tip: str = ""

    @property
    def is_safe(self) -> bool:
        """True only when a proof tier was reached and nothing refused it."""
        return self.refusal is None and self.tier in (
            TIER_MERGED,
            TIER_MERGED_UNPUSHED,
            TIER_MERGED_NOT_IN_HEAD,
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


def _git(
    repo: Path,
    *args: str,
    check: bool = True,
    timeout: float = Timeout.GIT_BRANCH_SAFETY,
) -> subprocess.CompletedProcess[str]:
    """Run git in ``repo`` on a budget sized for object walks.

    SECURITY: fixed argv list, never a shell string, and the binary is the
    trusted system git. Branch names arrive as separate argv entries so a name
    containing shell metacharacters cannot be interpreted.

    The budget is NOT ``run_git``'s default. Everything here walks objects —
    ``cherry`` computes a patch-id per commit, ``rev-list --objects`` and
    ``ls-tree -r`` enumerate every tree and blob in a ref — so the cost scales
    with the repository, and a five-second hook-context budget turns a large repo
    into a ``CalledProcessError`` (Plan 00248 F1). ``timeout`` is overridable per
    call so the bundle, which packs rather than reads, can have more still.
    """
    result = run_git(repo, *args, timeout=timeout)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )
    return result


def current_branch(repo: Path) -> str | None:
    """Return the checked-out branch name, or None on a detached HEAD."""
    result = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    name = result.stdout.strip()
    return name or None


def local_branches(repo: Path) -> set[str]:
    """Every local branch name in ``repo``.

    Uses the FULL refname and strips the prefix, never ``%(refname:short)``.
    ``:short`` yields the shortest UNAMBIGUOUS name, so a branch that shares its
    name with a tag comes back as ``heads/<name>`` — the caller then fails to find
    ``<name>``, and ``delete-branch`` reports "does not resolve to a local branch"
    about a branch that plainly exists. Fail-safe but false, and it made the
    command unusable for such a branch (found by executing the ambiguity, Plan
    00254; ``worktree_branches`` below already read the full refname).
    """
    result = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads")
    return {strip_branch_ref(line) for line in result.stdout.splitlines() if line}


def _safe_delete_reference(repo: Path, name: str) -> str:
    """The ref ``git branch -d`` will measure ``name`` against.

    Git applies ONE rule with two references, and which one it picks is not a
    preference — it is exclusive. Established by executing real git rather than
    read off the documentation (Plan 00253):

    - an upstream that RESOLVES is used on its own, and ``HEAD`` is then
      irrelevant: a branch level with ``origin/<name>`` is deleted with only a
      "has been merged to" warning even when it is absent from ``HEAD``;
    - with no resolvable upstream, ``HEAD`` is the sole reference — including a
      DETACHED ``HEAD``, which refuses exactly as an attached one does.

    Returning the ref rather than a boolean keeps that choice in one place, so
    the caller cannot accidentally answer a different question from git's.
    """
    upstream = _git(
        repo,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        f"{name}@{{upstream}}",
        check=False,
    )
    tracking = upstream.stdout.strip() if upstream.returncode == 0 else ""
    # `HEAD` resolves on a detached HEAD too, so one expression covers both.
    return tracking or "HEAD"


def _tier_for_merged_branch(repo: Path, name: str) -> str:
    """Which ``merged`` tier applies, given what git's safe delete will accept.

    Ancestry to the protected ref has already settled SAFETY. This settles only
    which FLAG git will accept, so the dry run can state what the real run will
    do — the whole point of Plan 00249, extended in Plan 00253 to the reference
    git actually uses.

    The uncovered case that made this necessary: a branch merged into ``main``
    with no upstream, while ``HEAD`` sits on another branch. The previous code
    returned "git will accept it" for every upstream-less branch, reasoning that
    git falls back to ``HEAD`` and the caller's ancestry proof covers that. It
    does not — the caller's proof is against ``protected_ref``, which is not
    ``HEAD`` whenever another branch is checked out. So ``--dry-run`` promised a
    delete the real run could not perform, which is precisely the contradiction
    Plan 00249 existed to remove, on the other axis of git's single rule.
    """
    reference = _safe_delete_reference(repo, name)
    accepted = _git(repo, "merge-base", "--is-ancestor", branch_ref(name), reference, check=False)
    if accepted.returncode == 0:
        return TIER_MERGED
    # Name the ACTUAL reason git will refuse. "unpushed" is true only when an
    # upstream exists; claiming it for the HEAD case would put a wrong
    # explanation in front of a user, which is the defect, not a rounding error.
    return TIER_MERGED_UNPUSHED if reference != _HEAD_REF else TIER_MERGED_NOT_IN_HEAD


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
    result = _git(repo, "cherry", protected_ref, branch_ref(name), check=False)
    return sum(1 for line in result.stdout.splitlines() if line.startswith(_CHERRY_UNIQUE_MARKER))


def _paths_in_tree(repo: Path, ref: str) -> set[str]:
    """Every path present in ``ref``'s tip tree.

    Emitted UNQUOTED so it is comparable with :func:`_paths_in_history`, which
    reads ``rev-list --objects`` — see :data:`_NO_QUOTE_PATH`.
    """
    result = _git(repo, *_NO_QUOTE_PATH, "ls-tree", "-r", "--name-only", ref, check=False)
    return {line for line in result.stdout.splitlines() if line}


def _blobs_in_tree(repo: Path, ref: str) -> dict[str, str]:
    """Map every path in ``ref``'s tip tree to its blob sha.

    Blob sha IS content identity in git: two files with the same sha are
    byte-identical no matter where they sit or how they got there. The sha is what
    the safety proof rests on, so quoting cannot affect the VERDICT — but these
    paths are also printed to a human deciding whether to abandon work, so they
    are emitted unquoted too (:data:`_NO_QUOTE_PATH`).
    """
    result = _git(repo, *_NO_QUOTE_PATH, "ls-tree", "-r", ref, check=False)
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

    # Read AFTER the refusal checks (the branch is known to resolve here) and
    # BEFORE any proof is computed, so the recorded sha is the one every tier below
    # is actually reasoning about.
    tip = _git(repo, "rev-parse", branch_ref(name)).stdout.strip()

    ancestor = _git(
        repo, "merge-base", "--is-ancestor", branch_ref(name), protected_ref, check=False
    )
    if ancestor.returncode == 0:
        # Ancestry to the protected ref settles SAFETY. It does not settle which
        # flag git will accept: `-d` measures against the branch's own upstream if
        # one resolves and against HEAD otherwise, so a branch fully contained in
        # the protected ref is still refused when it is ahead of `origin/<name>`
        # (Plan 00249) or when HEAD is on another branch (Plan 00253). Splitting
        # the tier here keeps the dry run honest — it can say what the real run
        # will do, and say why.
        tier = _tier_for_merged_branch(repo, name)
        return BranchClassification(name=name, tier=tier, detail=_TIER_DETAIL[tier], tip=tip)

    unique_commits = _unique_commit_count(repo, name, protected_ref)
    if unique_commits == 0:
        return BranchClassification(
            name=name,
            tier=TIER_PATCH_EQUIVALENT,
            detail=_TIER_DETAIL[TIER_PATCH_EQUIVALENT],
            tip=tip,
        )

    # Commit-level uniqueness does not imply content loss: a stale branch is
    # usually byte-identical to the protected ref and merely arranged
    # differently. Compare blob shas, which ARE content identity in git.
    branch_blobs = _blobs_in_tree(repo, branch_ref(name))
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
            tip=tip,
        )

    unique_paths = tuple(
        sorted(_paths_in_tree(repo, branch_ref(name)) - _paths_in_history(repo, protected_ref))
    )
    return BranchClassification(
        name=name,
        tier=TIER_UNPROVEN,
        unique_paths=unique_paths,
        content_unique_paths=content_unique_paths,
        unique_commits=unique_commits,
        tip=tip,
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

    Gets the largest budget of anything here: it PACKS objects rather than
    reading them, and a bundle killed part-way is a lost recovery, not a slow
    one.
    """
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    _git(
        repo,
        "bundle",
        "create",
        str(bundle_path),
        *(branch_ref(n) for n in names),
        timeout=Timeout.GIT_BUNDLE_CREATE,
    )
    return bundle_path


def _discard_unused_bundle(bundle: Path) -> str | None:
    """Remove a recovery bundle for a run that deleted nothing.

    Returns ``None`` when it is gone, or a message describing why it could not be
    removed. The failure is RETURNED rather than logged: this module reports
    outcomes through ``DeletionReport.blockers``, so surfacing it there puts it in
    front of the person running the command instead of in a log they have no
    reason to open. Raising instead would be worse — it runs on a path that is
    already reporting a refusal, and a failure to tidy up a scratch file must not
    bury the refusal the user actually needs to read.
    """
    try:
        bundle.unlink()
    except OSError as exc:
        return (
            f"could not remove the unused recovery bundle at {bundle}: {exc} — "
            f"nothing was deleted, so this bundle is NOT evidence of a deletion "
            f"and is safe to remove by hand"
        )
    return None


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
    """Classify every branch, then delete the batch.

    Nothing is deleted until EVERY branch has been classified and every blocker
    resolved, so a batch containing one unsafe branch removes none of the others.
    That is the all-or-nothing property worth having, and it is the one this
    function can actually guarantee.

    What it cannot guarantee is atomicity across the deletes themselves: git may
    refuse an individual branch on grounds this engine does not model, and a ref
    already removed cannot be un-removed by unwinding. When that happens the
    report says so — ``refused`` is set, ``deleted`` lists exactly the branches
    that went, and ``blockers`` carries git's own words for each that did not
    (Plan 00249). A docstring promising more than the code delivers is worse than
    an honest one, and the recovery bundle exists precisely for this case.

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

    deleted: list[str] = []
    failures: list[str] = []
    for classification in classifications:
        # Re-read the tip BEFORE the delete: the proof above was made against a
        # sha, and the bundle was written against the same one, so a branch that
        # moved since is covered by neither (Plan 00254).
        moved = tip_moved_since_proof(repo, classification)
        if moved is not None:
            failures.append(moved)
            continue
        # Defer to git's own check whenever it is capable of making it — and
        # ACCEPT a refusal rather than raising on it (Plan 00249). git's `-d`
        # refuses on conditions this engine does not model, and a refusal from
        # the tool whose whole job is to refuse clearly must not arrive as a
        # traceback. `check=False` keeps git's own words available to say why.
        result = _git(
            repo,
            *delete_argv_for_tier(classification.tier),
            classification.name,
            check=False,
        )
        if result.returncode == 0:
            deleted.append(classification.name)
            continue
        failures.append(
            f"{classification.name}: git refused the delete "
            f"(proven {classification.tier}) — {result.stderr.strip() or 'no detail'}"
            f"\n      {_REFUSAL_DIAGNOSIS}"
        )

    if failures:
        # Report what ACTUALLY happened. The all-or-nothing intent is enforced by
        # classifying everything before touching anything, but git can still
        # refuse a single branch mid-loop, and claiming a clean batch then would
        # be a lie about the repository's state.
        #
        # A bundle for a run that deleted NOTHING is worse than no bundle: the
        # field report found a 1.9 MB one left behind by this crash, and anyone
        # finding it later would reasonably read it as evidence the branch was
        # gone. Where something WAS deleted the bundle is the recovery route, so
        # it stays.
        if bundle is not None and not deleted:
            problem = _discard_unused_bundle(bundle)
            if problem is None:
                bundle = None
            else:
                failures.append(problem)
        return DeletionReport(
            classifications=classifications,
            deleted=tuple(deleted),
            bundle=bundle,
            refused=True,
            blockers=tuple(failures),
        )

    return DeletionReport(
        classifications=classifications,
        deleted=tuple(deleted),
        bundle=bundle,
    )
