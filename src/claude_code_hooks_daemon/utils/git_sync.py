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
import subprocess  # nosec B404 — only ever runs the trusted system ``git`` binary
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout

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
    """Run ``git -C <cwd> <args>``; return the completed process, or ``None``.

    ``None`` means git was unavailable (OSError/SubprocessError) or the call
    timed out — the caller then treats it as "no answer" and fails silently.
    A non-zero return code is NOT ``None``: it is a valid answer (e.g. "not a
    repo", "no upstream", "non-fast-forward") the caller inspects.
    """
    try:
        return subprocess.run(  # nosec B603 B607 — fixed argv, no shell, trusted binary
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None


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
