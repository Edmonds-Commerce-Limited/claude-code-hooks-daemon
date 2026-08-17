"""Upstream-sync git operations (Plan 00178).

A focused, independently-testable home for the git operations the
``git_upstream_checker`` SessionStart handler needs. The handler owns *policy*
(which mode, what to say); this module owns the *mechanism* (talking to git):

- :func:`current_branch` / :func:`upstream_ref` — resolve where we are.
- :func:`upstream_status` — ahead/behind vs ``@{upstream}`` as a typed value.
- :func:`working_tree_clean` — is it safe to auto-pull?
- :func:`fetch_all` — an additive ``git fetch --all`` (never ``--prune``).
- :func:`gone_branches` — local branches whose upstream was deleted on the
  remote (detected non-destructively, classified merged/not-merged).
- :func:`pull_ff_only` — a safe, deterministic fast-forward-only pull.

Every function is **fail-silent** on a missing/broken git (returns ``None`` /
``False`` / a not-ok :class:`PullResult`) — feature-detection, not error hiding:
"not a repo" / "no upstream" IS the answer. Network calls run non-interactively
(``GIT_TERMINAL_PROMPT=0`` + SSH batch mode) so they can never hang on
credentials, and are bounded by explicit timeouts.

SOLID: this mirrors :mod:`claude_code_hooks_daemon.utils.git_repo` (the
config-read home) — callers express intent and never own argv, timeouts, env, or
the fail-silent convention.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 — CompletedProcess typing only; run_git owns the spawn
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import run_git

# Non-interactive fetch/pull env (identical intent to the status-line git_branch
# background fetch): never block on credentials, never open an interactive
# prompt. Kept local to this module so it stays the single source of truth for
# the sync path (git_branch owns its own copy for the status render path).
_GIT_TERMINAL_PROMPT_ENV = "GIT_TERMINAL_PROMPT"
_GIT_TERMINAL_PROMPT_DISABLED = "0"
_GIT_SSH_COMMAND_ENV = "GIT_SSH_COMMAND"
_GIT_SSH_BATCH_MODE = "ssh -oBatchMode=yes"

# rev-list --left-right --count A...B prints "<left>\t<right>": left = commits in
# A not in B, right = commits in B not in A. With ``@{upstream}...HEAD`` that is
# (behind, ahead).
_LEFT_RIGHT_FIELD_COUNT = 2

_PULL_FAILED_DEFAULT_DETAIL = "git pull --ff-only failed (non-fast-forward or git unavailable)"

# `git remote prune <remote> --dry-run` reports each ref it WOULD remove on a
# line containing this marker, e.g. " * [would prune] origin/foo".
_WOULD_PRUNE_MARKER = "[would prune]"
# for-each-ref field separator (a char that never appears in a git ref name).
_REF_FIELD_SEP = "\x1f"

# Peeling suffix that resolves any commit-ish to the TREE object it points at.
# Comparing trees (not commits) is what tells a history rewrite apart from
# ordinary divergence — see ``upstream_tree_matches``.
_TREE_PEEL_SUFFIX = "^{tree}"
_HEAD_REF = "HEAD"


@dataclass(frozen=True)
class UpstreamStatus:
    """Ahead/behind state of the current branch versus its upstream."""

    branch: str
    upstream: str
    behind: int
    ahead: int


@dataclass(frozen=True)
class PullResult:
    """Outcome of a fast-forward-only pull."""

    ok: bool
    detail: str


@dataclass(frozen=True)
class GoneBranch:
    """A local branch whose upstream branch was deleted on the remote.

    ``merged`` is True when the branch is fully merged into the default branch,
    i.e. deleting it with ``git branch -d`` loses no unique commits. When False
    the branch carries commits not on the default branch — removal needs human
    confirmation.
    """

    name: str
    upstream: str
    merged: bool


def _run_git(
    cwd: Path,
    *args: str,
    timeout: float,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Run ``git -C <cwd> <args>`` via the daemon's single spawn point.

    Delegates to :func:`claude_code_hooks_daemon.utils.git_repo.run_git`, THE
    place the daemon spawns git (Plan 00246) — declining the optional index
    lock and enforcing a timeout hold by construction rather than per module.
    ``run_git`` never raises: an absent git binary or a timeout comes back as a
    non-zero ``returncode`` with the reason in ``stderr`` instead of ``None``,
    so every caller here — already written to branch on ``returncode != 0`` —
    treats it identically to "not a repo" / "no upstream" / "non-fast-forward".
    The ``| None`` stays in the return type only so a test double can still
    stand in for an undetermined answer.
    """
    return run_git(cwd, *args, timeout=timeout, env=env)


def _noninteractive_env() -> dict[str, str]:
    """Return an environment that prevents git from prompting for credentials."""
    env = os.environ.copy()
    env[_GIT_TERMINAL_PROMPT_ENV] = _GIT_TERMINAL_PROMPT_DISABLED
    env.setdefault(_GIT_SSH_COMMAND_ENV, _GIT_SSH_BATCH_MODE)
    return env


def current_branch(cwd: Path) -> str | None:
    """Return the current branch name, or ``None`` when detached / not a repo."""
    result = _run_git(
        cwd, "symbolic-ref", "--quiet", "--short", "HEAD", timeout=Timeout.GIT_CONTEXT
    )
    if result is None or result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def upstream_ref(cwd: Path) -> str | None:
    """Return the upstream ref (e.g. ``origin/main``), or ``None`` when unset."""
    result = _run_git(
        cwd,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        timeout=Timeout.GIT_CONTEXT,
    )
    if result is None or result.returncode != 0:
        return None
    ref = result.stdout.strip()
    return ref or None


def _tree_of(cwd: Path, rev: str) -> str | None:
    """Resolve ``rev`` to its tree object sha, or ``None`` when unresolvable."""
    result = _run_git(cwd, "rev-parse", f"{rev}{_TREE_PEEL_SUFFIX}", timeout=Timeout.GIT_CONTEXT)
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip() or None


def upstream_tree_matches(cwd: Path) -> bool:
    """True when ``HEAD`` and its upstream resolve to the SAME tree object.

    Read this together with :func:`upstream_status`. Ahead/behind counts cannot
    tell an ordinary divergence apart from an upstream HISTORY REWRITE — both
    report "N ahead, M behind" — yet the correct response is opposite. Merging
    is right for the first and destructive for the second: a rewrite replays
    the same content under new shas, so every local commit is a pre-rewrite
    duplicate and a merge drags all of them back in, re-publishing exactly what
    the rewrite existed to destroy.

    The tree is the discriminator. A rewrite changes commit metadata and leaves
    content untouched, so the trees match while the commit shas differ. Real
    divergence changes content, so the trees differ too.

    Conservative by design: anything unresolvable (no upstream, not a repo, git
    unavailable) returns ``False``, so a caller falls back to the ordinary
    divergence advice rather than suppressing it on a guess.
    """
    upstream = upstream_ref(cwd)
    if upstream is None:
        return False
    head_tree = _tree_of(cwd, _HEAD_REF)
    upstream_tree = _tree_of(cwd, upstream)
    if head_tree is None or upstream_tree is None:
        return False
    return head_tree == upstream_tree


def _cherry_counts(cwd: Path) -> tuple[int, int] | None:
    """Return ``(duplicated, unique)`` counts for local commits versus upstream.

    ``--cherry-pick`` compares by PATCH ID, so a commit replayed under a new sha
    with the same change counts as duplicated. That is exactly what a history
    rewrite produces, and it is why this beats comparing shas.

    ``None`` when the counts cannot be established (no upstream, not a repo, git
    unavailable, or the probe timed out on a very large history).
    """
    upstream = upstream_ref(cwd)
    if upstream is None:
        return None
    ahead = _run_git(cwd, "rev-list", "--count", f"{upstream}..HEAD", timeout=Timeout.GIT_CONTEXT)
    # Patch-id computation over every diverged commit — a fetch-scale budget,
    # not a context-scale one. Only ever reached on an already-diverged branch.
    unique = _run_git(
        cwd,
        "rev-list",
        "--count",
        "--left-only",
        "--cherry-pick",
        f"HEAD...{upstream}",
        timeout=Timeout.GIT_FETCH_SESSION,
    )
    if ahead is None or unique is None:
        return None
    if ahead.returncode != 0 or unique.returncode != 0:
        return None
    # Validated rather than caught: `--count` always prints a bare integer, so
    # anything else means git did not answer the question we asked. Checking up
    # front keeps that an explicit branch instead of a swallowed exception.
    ahead_text = ahead.stdout.strip()
    unique_text = unique.stdout.strip()
    if not ahead_text.isdigit() or not unique_text.isdigit():
        return None
    unique_count = int(unique_text)
    return int(ahead_text) - unique_count, unique_count


def upstream_was_rewritten(cwd: Path) -> bool:
    """True when the upstream looks REWRITTEN rather than merely diverged.

    Read with :func:`upstream_status`. Ahead/behind counts cannot separate the
    two, yet the right response is opposite: merging is correct for ordinary
    divergence and destructive after a rewrite, where every local commit is a
    pre-rewrite duplicate and a merge drags the whole contaminated history back
    in — republishing exactly what the rewrite existed to destroy.

    Two signals, cheapest first:

    1. Identical trees (:func:`upstream_tree_matches`) — a pure rewrite with no
       local work on top. O(1), exact.
    2. Most local commits have a patch-identical twin upstream. This is the
       realistic case: a rewrite plus a handful of genuinely new local commits,
       which signal 1 misses entirely because any local commit changes the tree.

    Note what is NOT used: a missing merge base. ``filter-repo`` only rewrites
    commits from the first modified one onward, so untouched early history keeps
    its shas and a common ancestor usually still exists.

    Conservative: anything unresolvable returns ``False``, so the caller falls
    back to ordinary divergence advice rather than suppressing it on a guess.
    """
    if upstream_tree_matches(cwd):
        return True
    counts = _cherry_counts(cwd)
    if counts is None:
        return False
    duplicated, unique = counts
    # Strictly greater: a tie is not evidence, and "no duplicates at all" is
    # the ordinary-divergence signature.
    return duplicated > 0 and duplicated > unique


def upstream_status(cwd: Path) -> UpstreamStatus | None:
    """Return ahead/behind vs upstream, or ``None`` when not applicable.

    ``None`` covers: not a git repo, detached HEAD (no branch), or the branch
    has no configured upstream — in every case there is nothing to compare.
    """
    branch = current_branch(cwd)
    if branch is None:
        return None
    upstream = upstream_ref(cwd)
    if upstream is None:
        return None

    result = _run_git(
        cwd,
        "rev-list",
        "--left-right",
        "--count",
        "@{upstream}...HEAD",
        timeout=Timeout.GIT_CONTEXT,
    )
    if result is None or result.returncode != 0:
        return None

    fields = result.stdout.split()
    if len(fields) != _LEFT_RIGHT_FIELD_COUNT:
        return None
    try:
        behind = int(fields[0])
        ahead = int(fields[1])
    except ValueError:
        return None

    return UpstreamStatus(branch=branch, upstream=upstream, behind=behind, ahead=ahead)


def working_tree_clean(cwd: Path) -> bool:
    """Return ``True`` when the working tree has no changes (nor untracked files).

    A non-repo / git failure returns ``False`` — an unknown tree is treated as
    unsafe to auto-pull.
    """
    result = _run_git(cwd, "status", "--porcelain", timeout=Timeout.GIT_CONTEXT)
    if result is None or result.returncode != 0:
        return False
    return result.stdout.strip() == ""


def fetch_all(cwd: Path, timeout: float = Timeout.GIT_FETCH_SESSION) -> bool:
    """Run an additive ``git fetch --all --no-prune`` non-interactively.

    Plan 00179: the automatic session-start fetch is deliberately additive — it
    can never remove a remote-tracking ref (and therefore never surprises a local
    branch into a ``gone`` upstream). ``--no-prune`` is passed **explicitly** so
    the additive guarantee holds even when the user has ``fetch.prune = true`` in
    their git config (a common setting that would otherwise make a bare
    ``git fetch`` prune). Deleted remote branches are surfaced separately and
    non-destructively by :func:`gone_branches`.

    Returns ``True`` only when git ran and exited 0. Offline / auth / timeout /
    not-a-repo all return ``False`` (fail-silent): the caller still reports
    staleness from whatever remote-tracking refs already exist.
    """
    result = _run_git(
        cwd,
        "fetch",
        "--all",
        "--no-prune",
        "--quiet",
        timeout=timeout,
        env=_noninteractive_env(),
    )
    return result is not None and result.returncode == 0


def pull_ff_only(cwd: Path, timeout: float = Timeout.GIT_PULL_SESSION) -> PullResult:
    """Run a safe, deterministic ``git pull --ff-only``.

    Fast-forward-only never creates a merge commit and refuses (non-zero) when
    the history has diverged, so it can never leave a conflicted tree. Any
    failure — non-fast-forward, dirty tree, git unavailable — yields
    ``PullResult(ok=False, detail=<reason>)``.
    """
    result = _run_git(
        cwd,
        "pull",
        "--ff-only",
        "--quiet",
        timeout=timeout,
        env=_noninteractive_env(),
    )
    if result is None:
        return PullResult(ok=False, detail=_PULL_FAILED_DEFAULT_DETAIL)
    if result.returncode == 0:
        return PullResult(ok=True, detail=result.stdout.strip() or "fast-forwarded")
    detail = result.stderr.strip() or result.stdout.strip() or _PULL_FAILED_DEFAULT_DETAIL
    return PullResult(ok=False, detail=detail)


def default_branch(cwd: Path) -> str | None:
    """Return the repo's default branch name (e.g. ``main``), or ``None``.

    Prefers ``origin/HEAD`` (``refs/remotes/origin/HEAD`` → ``origin/main`` →
    ``main``); falls back to a local ``main``/``master`` if present.
    """
    result = _run_git(
        cwd,
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
        timeout=Timeout.GIT_CONTEXT,
    )
    if result is not None and result.returncode == 0:
        ref = result.stdout.strip()  # e.g. "origin/main"
        if ref:
            return ref.split("/", 1)[1] if "/" in ref else ref

    for candidate in ("main", "master"):
        probe = _run_git(
            cwd,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{candidate}",
            timeout=Timeout.GIT_CONTEXT,
        )
        if probe is not None and probe.returncode == 0:
            return candidate
    return None


def _remotes(cwd: Path) -> list[str]:
    """Return configured remote names (empty on failure / no remotes)."""
    result = _run_git(cwd, "remote", timeout=Timeout.GIT_CONTEXT)
    if result is None or result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _stale_remote_tracking_refs(cwd: Path) -> set[str]:
    """Remote-tracking refs that WOULD be pruned (deleted on remote).

    Uses ``git remote prune <remote> --dry-run`` per remote — a read-only probe
    that removes nothing. Fail-silent per remote (offline / auth → skipped).
    """
    stale: set[str] = set()
    for remote in _remotes(cwd):
        result = _run_git(
            cwd,
            "remote",
            "prune",
            remote,
            "--dry-run",
            timeout=Timeout.GIT_FETCH_SESSION,
            env=_noninteractive_env(),
        )
        if result is None or result.returncode != 0:
            continue
        text = f"{result.stdout}\n{result.stderr}"
        for raw in text.splitlines():
            line = raw.strip()
            if _WOULD_PRUNE_MARKER in line:
                ref = line.split(_WOULD_PRUNE_MARKER, 1)[1].strip()
                if ref:
                    stale.add(ref)
    return stale


def _local_branch_upstreams(cwd: Path) -> dict[str, str]:
    """Map each local branch to its configured upstream short name (if any)."""
    result = _run_git(
        cwd,
        "for-each-ref",
        f"--format=%(refname:short){_REF_FIELD_SEP}%(upstream:short)",
        "refs/heads",
        timeout=Timeout.GIT_CONTEXT,
    )
    if result is None or result.returncode != 0:
        return {}
    mapping: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if _REF_FIELD_SEP not in line:
            continue
        name, upstream = line.split(_REF_FIELD_SEP, 1)
        name, upstream = name.strip(), upstream.strip()
        if name and upstream:
            mapping[name] = upstream
    return mapping


def _merged_branch_names(cwd: Path, base: str) -> set[str]:
    """Return local branch names fully merged into ``base``."""
    result = _run_git(
        cwd,
        "branch",
        "--merged",
        base,
        "--format=%(refname:short)",
        timeout=Timeout.GIT_CONTEXT,
    )
    if result is None or result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def gone_branches(cwd: Path) -> list[GoneBranch]:
    """Return local branches whose upstream was deleted on the remote.

    Read-only: detects deletions via a ``--dry-run`` prune probe (see
    :func:`_stale_remote_tracking_refs`) and classifies each affected local
    branch merged/not-merged vs the default branch. Never mutates anything.
    Empty list when nothing was deleted, not a repo, or git is unavailable.
    """
    stale = _stale_remote_tracking_refs(cwd)
    if not stale:
        return []

    gone = {
        name: upstream
        for name, upstream in _local_branch_upstreams(cwd).items()
        if upstream in stale
    }
    if not gone:
        return []

    base = default_branch(cwd)
    merged = _merged_branch_names(cwd, base) if base else set()

    return [
        GoneBranch(name=name, upstream=gone[name], merged=name in merged) for name in sorted(gone)
    ]
