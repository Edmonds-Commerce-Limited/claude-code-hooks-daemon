"""Park a branch: an empty trailer commit at its tip (Plan 00558 Task 4.3, DESIGN section 5).

``git commit-tree`` writes a commit with the tip's own tree plus the
``Parked-Reason``/``Parked-By`` trailers (``Unparked`` to clear), and
``git update-ref <ref> <new> <old>`` moves the branch only if its tip has not
moved meanwhile. No checkout is needed. The branch is then pushed with a plain
fast-forward ``git push``; a failed push leaves the local park standing and
is reported with the command to retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import run_git

_HEADS = "refs/heads/"
_REMOTES = "refs/remotes/"


class BranchParkError(Exception):
    """The park could not be written; nothing changed."""


@dataclass(frozen=True)
class ParkResult:
    """The new tip and whether the fast-forward push landed."""

    sha: str
    pushed: bool
    push_error: str | None
    retry_command: str | None


def _git_out(repo: Path, *args: str) -> str:
    result = run_git(repo, *args)
    if result.returncode != 0:
        raise BranchParkError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _message(reason: str | None, user: str, *, clear: bool) -> str:
    if clear:
        return f"Unpark branch\n\nUnparked: {user}\n"
    return f"Park branch: {reason}\n\nParked-Reason: {reason}\nParked-By: {user}\n"


def _write_park_commit(repo: Path, parent: str, reason: str, *, clear: bool) -> str:
    """A trailer commit on ``parent``'s own tree; returns its sha."""
    tree = _git_out(repo, "rev-parse", f"{parent}^{{tree}}")
    user = run_git(repo, "config", "user.name").stdout.strip() or "unknown"
    return _git_out(
        repo, "commit-tree", tree, "-p", parent, "-m", _message(reason, user, clear=clear)
    )


def _park_remote_only(
    repo: Path,
    name: str,
    remote: str,
    remote_ref: str,
    old: str,
    reason: str,
    *,
    clear: bool,
) -> ParkResult:
    """Park a branch only ``remote`` holds, with no local branch.

    The park commit is pushed as a plain fast-forward; no local ref holds it, so
    a failed push parks nothing. On success the remote-tracking ref follows the
    push so the inventory sees the park without a fetch.
    """
    new = _write_park_commit(repo, old, reason, clear=clear)
    pushed = run_git(
        repo,
        "push",
        remote,
        f"{new}:{_HEADS}{name}",
        timeout=Timeout.GIT_FETCH_SESSION,
    )
    if pushed.returncode != 0:
        raise BranchParkError(
            f"push of {name} to {remote} failed, so nothing is parked: "
            f"{pushed.stderr.strip() or 'git push failed'}"
        )
    # ``git push`` already advances the tracking ref when the remote has the default
    # fetch refspec; setting it to ``new`` is idempotent and covers a remote without one.
    moved = run_git(repo, "update-ref", remote_ref, new)
    if moved.returncode != 0:
        raise BranchParkError(
            f"{name} was parked on {remote} but {remote_ref} could not follow: "
            f"{moved.stderr.strip()}"
        )
    return ParkResult(new, True, None, None)


def park_branch(
    repo: Path,
    name: str,
    *,
    reason: str | None,
    remote: str,
    clear: bool = False,
) -> ParkResult:
    """Park (or, with ``clear``, unpark) branch ``name`` and push it.

    A branch with no local ref but a ``<remote>/<name>`` tracking ref is parked on
    the remote alone (no local branch is created).

    Raises:
        BranchParkError: The reason is unusable, the branch is missing, the
            tip moved while the park commit was written, or a remote-only
            park could not be pushed.
    """
    stripped = reason.strip() if reason is not None else ""
    if not clear and (not stripped or "\n" in stripped):
        raise BranchParkError("a single-line, non-empty reason is required (--reason)")
    ref = f"{_HEADS}{name}"
    verified = run_git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    remote_ref = f"{_REMOTES}{remote}/{name}"
    if verified.returncode != 0:
        remote_tip = run_git(repo, "rev-parse", "--verify", "--quiet", f"{remote_ref}^{{commit}}")
        if remote_tip.returncode != 0:
            raise BranchParkError(f"no local branch {name} and no {remote}/{name}")
        return _park_remote_only(
            repo, name, remote, remote_ref, remote_tip.stdout.strip(), stripped, clear=clear
        )
    old = verified.stdout.strip()
    new = _write_park_commit(repo, old, stripped, clear=clear)
    moved = run_git(repo, "update-ref", ref, new, old)
    if moved.returncode != 0:
        raise BranchParkError(
            f"{name} moved while parking; nothing changed: {moved.stderr.strip()}"
        )
    retry = f"git push {remote} {name}"
    pushed = run_git(repo, "push", remote, name, timeout=Timeout.GIT_FETCH_SESSION)
    if pushed.returncode != 0:
        return ParkResult(new, False, pushed.stderr.strip() or "git push failed", retry)
    return ParkResult(new, True, None, None)
