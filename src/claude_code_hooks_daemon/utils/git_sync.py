"""Upstream-sync git operations (Plan 00178).

A focused, independently-testable home for the git operations the
``git_upstream_checker`` SessionStart handler needs. The handler owns *policy*
(which mode, what to say); this module owns the *mechanism* (talking to git):

- :func:`current_branch` / :func:`upstream_ref` — resolve where we are.
- :func:`upstream_status` — ahead/behind vs ``@{upstream}`` as a typed value.
- :func:`working_tree_clean` — is it safe to auto-pull?
- :func:`fetch_all_prune` — the full ``git fetch --all --prune``.
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
    result = _run_git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD", timeout=Timeout.GIT_CONTEXT)
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


def fetch_all_prune(cwd: Path, timeout: float = Timeout.GIT_FETCH_SESSION) -> bool:
    """Run a full ``git fetch --all --prune`` non-interactively.

    Returns ``True`` only when git ran and exited 0. Offline / auth / timeout /
    not-a-repo all return ``False`` (fail-silent): the caller still reports
    staleness from whatever remote-tracking refs already exist.
    """
    result = _run_git(
        cwd,
        "fetch",
        "--all",
        "--prune",
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
