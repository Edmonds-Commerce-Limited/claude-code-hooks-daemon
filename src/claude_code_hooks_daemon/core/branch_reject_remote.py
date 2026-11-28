"""The no-value route for a REMOTE branch whose pull request closed unmerged (ledger N763).

A remote branch the remote-delete proof refuses (its work is found nowhere else) is
otherwise deletable by no agent route. This module lets one go on the same two facts
the local route rests on (:mod:`branch_reject`): an independent reviewer's no-value
verdict for exactly the remote tip, and a recovery bundle the guard wrote and
verified. It adds what only a remote copy needs, every one re-read at request time
AND at delete time:

- the branch's pull request was CLOSED without being merged, and its head commit is
  the remote tip (commits pushed after closing were never judged by anyone);
- the remote tip and the remote's default are what ``refs/remotes/<remote>/`` records,
  on the fetch URL and on every push URL;
- the branch is not merged (the existing proven route deletes that) and no worktree
  has a local branch of that name checked out.

Every unreadable fact refuses. The delete is a ``--force-with-lease`` push on the
approved tip, made only after the ledger line and the single-use claim are written.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_cleanup
from claude_code_hooks_daemon.core.branch_reject import (
    IssuedRequest,
    RejectError,
    RejectRefusedError,
    RejectRoute,
    approve_removal,
    issue_requests,
    record_git_refusal,
    record_removal,
    restore_commands,
    subject_ref,
)
from claude_code_hooks_daemon.core.remote_branch_proof import (
    live_refs_problem,
    named_ref_problem,
    prove_remote_merged,
)
from claude_code_hooks_daemon.utils.git_repo import parse_worktree_porcelain, run_git
from claude_code_hooks_daemon.utils.git_sync import resolve_remote_default_branch
from claude_code_hooks_daemon.utils.github_issue_validity import GhError, GhRunner, make_gh_runner

#: ``gh pr list`` page size. A FULL page is unreadable: a PR past it could be open.
PR_PAGE_LIMIT = 20
_PR_FIELDS = "number,state,headRefName,headRefOid,isCrossRepository"
_STATE_CLOSED = "CLOSED"
_STATE_OPEN = "OPEN"
_STATE_MERGED = "MERGED"
_STATES = frozenset({_STATE_CLOSED, _STATE_OPEN, _STATE_MERGED})


def pr_runner(repo: Path) -> GhRunner:
    """The ``gh`` runner the CLI uses; tests replace this function, never the network."""
    return make_gh_runner(cwd=repo)


@dataclass(frozen=True)
class _Pr:
    number: int
    state: str
    head: str
    oid: str
    cross: bool


def _parse_prs(raw: str, name: str) -> list[_Pr]:
    """Every PR record of the answer; raises RejectRefusedError on any malformed one."""
    unreadable = f"the pull request state of `{name}` could not be read"
    try:
        data: Any = json.loads(raw)
    except ValueError as exc:
        raise RejectRefusedError(f"{unreadable}: gh did not answer JSON ({exc})") from exc
    if not isinstance(data, list):
        raise RejectRefusedError(f"{unreadable}: gh did not answer a list")
    if len(data) >= PR_PAGE_LIMIT:
        raise RejectRefusedError(f"{unreadable}: {len(data)} pull requests fill a page")
    prs: list[_Pr] = []
    for record in data:
        if not isinstance(record, Mapping):
            raise RejectRefusedError(f"{unreadable}: a record is not an object")
        number = record.get("number")
        fields = [record.get(key) for key in ("state", "headRefName", "headRefOid")]
        cross = record.get("isCrossRepository")
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or not all(isinstance(value, str) for value in fields)
            or not isinstance(cross, bool)
        ):
            raise RejectRefusedError(f"{unreadable}: a record lacks a typed field")
        state, head, oid = (str(value) for value in fields)
        prs.append(_Pr(number=number, state=state, head=head, oid=oid, cross=cross))
    return prs


def closed_pr(runner: GhRunner, name: str, tip: str) -> int:
    """The number of a CLOSED-unmerged pull request of ``name`` whose head is ``tip``.

    Raises RejectRefusedError unless gh answers, every same-repository PR headed by
    ``name`` is closed unmerged, and one of them has ``tip`` as its head commit. A PR
    from a fork (``isCrossRepository``) or with another head name is not this branch's.
    """
    args = ["pr", "list", "--head", name, "--state", "all", "--json", _PR_FIELDS]
    try:
        raw = runner([*args, "--limit", str(PR_PAGE_LIMIT)])
    except GhError as exc:
        raise RejectRefusedError(
            f"the pull request state of `{name}` could not be read ({exc}); nothing is "
            "removed while it is unknown"
        ) from exc
    prs = [pr for pr in _parse_prs(raw, name) if pr.head == name and not pr.cross]
    if not prs:
        raise RejectRefusedError(
            f"no pull request of this repository has `{name}` as its head; only work a "
            "closed, unmerged pull request carried takes this route"
        )
    for pr in prs:
        if pr.state not in _STATES:
            raise RejectRefusedError(f"pull request #{pr.number} has an unknown state {pr.state!r}")
        if pr.state == _STATE_OPEN:
            raise RejectRefusedError(f"pull request #{pr.number} for `{name}` is open")
        if pr.state == _STATE_MERGED:
            raise RejectRefusedError(
                f"pull request #{pr.number} for `{name}` was merged; the merged route applies "
                f"(hooks-daemon delete-branch --remote-only {name})"
            )
    matching = [pr.number for pr in prs if pr.oid == tip]
    if not matching:
        raise RejectRefusedError(
            f"no closed pull request of `{name}` has the remote tip {tip[:12]} as its head "
            "commit; commits pushed after it closed were never judged"
        )
    return max(matching)


@dataclass(frozen=True)
class RemoteSubject:
    """A remote branch every precondition of the route accepts, as read just now."""

    remote: str
    name: str
    tip: str
    default: str
    default_ref: str
    default_sha: str
    pr_number: int
    top: Path


def _git_top(repo: Path) -> Path:
    result = run_git(repo, "rev-parse", "--show-toplevel")
    if result.returncode != 0 or not result.stdout.strip():
        raise RejectError(f"{repo} is not inside a work tree: {result.stderr.strip()}")
    return Path(result.stdout.strip())


def _tracking_tip(top: Path, ref: str) -> str | None:
    """The commit ``ref`` resolves to; None when it does not exist; RejectError otherwise."""
    result = run_git(top, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
        return None
    raise RejectError(f"could not resolve {ref}: {result.stderr.strip() or 'no detail'}")


def _worktree_problem(top: Path, name: str) -> str | None:
    """Why a worktree holds ``name``; an unreadable worktree list raises RejectError."""
    listing = run_git(top, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        raise RejectError(f"git worktree list failed: {listing.stderr.strip() or 'no detail'}")
    for record in parse_worktree_porcelain(listing.stdout):
        if record.branch == name:
            return (
                f"a local `{name}` is checked out in the worktree {record.path}; work there "
                "can still push to the remote branch"
            )
    return None


def check_subject(
    repo: Path, branches: BranchesConfig, default: str, name: str, runner: GhRunner
) -> RemoteSubject:
    """Every precondition of the remote route, read NOW; raises on the first refusal.

    RejectRefusedError for a refusal, RejectError for a git fact that cannot be read.
    """
    remote = branches.remote
    problem = named_ref_problem(remote, name, default, branches)
    if problem is not None:
        raise RejectRefusedError(problem)
    ref = subject_ref(name, remote)
    top = _git_top(repo)
    remote_default = resolve_remote_default_branch(branches, top, remote=remote)
    if remote_default != default:
        known = f"`{remote_default}`" if remote_default else "unknown here"
        raise RejectRefusedError(
            f"`{default}` is not confirmed as {remote}'s default branch ({known}); run "
            f"`git remote set-head {remote} --auto` or set `branches.default`"
        )
    tip = _tracking_tip(top, ref)
    if tip is None:
        raise RejectRefusedError(
            f"`{remote}/{name}` does not exist here ({ref}); run `git fetch {remote}` if it "
            "was pushed since"
        )
    default_ref = subject_ref(default, remote)
    default_sha = _tracking_tip(top, default_ref)
    if default_sha is None:
        raise RejectRefusedError(f"{default_ref} does not exist; run `git fetch {remote}`")
    held = _worktree_problem(top, name)
    if held is not None:
        raise RejectRefusedError(held)
    proof = prove_remote_merged(top, remote, [name], default, branches)
    if name in proof.tips:
        raise RejectRefusedError(
            f"`{remote}/{name}` is proven ({proof.evidence.get(name, 'merged')}); nothing needs "
            f"a review. Run: hooks-daemon delete-branch --remote-only {name}"
        )
    live = live_refs_problem(top, remote, {name: tip, default: default_sha})
    if live is not None:
        raise RejectRefusedError(live)
    return RemoteSubject(
        remote=remote,
        name=name,
        tip=tip,
        default=default,
        default_ref=default_ref,
        default_sha=default_sha,
        pr_number=closed_pr(runner, name, tip),
        top=top,
    )


def issue_remote_requests(
    repo: Path,
    branches: BranchesConfig,
    default: str,
    name: str,
    route: RejectRoute,
    runner: GhRunner,
) -> tuple[RemoteSubject, list[IssuedRequest]]:
    """Check the subject, then admit a remote-scope review and store its requests."""
    subject = check_subject(repo, branches, default, name, runner)
    scoped = replace(route, default_ref=subject.default_ref)
    issued = issue_requests(
        subject.top, name, scoped, remote=subject.remote, pr_number=subject.pr_number
    )
    if issued[0].request.tip != subject.tip:
        raise RejectError(f"`{subject.remote}/{name}` moved while it was reviewed; run again")
    return subject, issued


@dataclass(frozen=True)
class RemoteRemoval:
    """A remote branch the route deleted, and the two lines that restore it."""

    remote: str
    name: str
    tip: str
    pr_number: int
    bundle: Path
    restore: tuple[str, str]


def delete_rejected_remote(
    repo: Path,
    branches: BranchesConfig,
    default: str,
    name: str,
    route: RejectRoute,
    runner: GhRunner,
) -> RemoteRemoval:
    """Re-check everything, then delete ``<remote>/<name>`` under a lease on the judged tip.

    In order: :func:`check_subject` (the PR state and the live tips re-read now);
    :func:`approve_removal` with verdicts of exactly this remote scope and tip (which
    writes and verifies the bundle); :func:`record_removal` (the ledger line and the
    exclusive single-use claim, before git); then the leased push. A git refusal is
    recorded with :func:`record_git_refusal` and raised as RejectRefusedError.
    """
    subject = check_subject(repo, branches, default, name, runner)
    scoped = replace(route, default_ref=subject.default_ref)
    approval = approve_removal(
        subject.top,
        name,
        subject.tip,
        scoped,
        default_ref=subject.default_ref,
        write=True,
        remote=subject.remote,
    )
    if approval.bundle is None:
        raise RejectError("the approval wrote no bundle")
    line = record_removal(subject.top, approval, scoped)
    gone, refusals = branch_cleanup.push_leased_deletes(
        subject.top, subject.remote, {name: approval.tip}
    )
    if name not in gone:
        detail = "; ".join(refusals) or "git refused the remote delete"
        try:
            record_git_refusal(line, detail, scoped)
        except RejectError as exc:
            raise RejectError(
                f"{detail}; AND the git-refused line could not be appended ({exc}); the "
                f"ledger {route.ledger_path} wrongly records this branch as removed"
            ) from exc
        raise RejectRefusedError(f"{detail}; the ledger records the refusal")
    return RemoteRemoval(
        remote=subject.remote,
        name=name,
        tip=approval.tip,
        pr_number=subject.pr_number,
        bundle=approval.bundle.path,
        restore=restore_commands(name, approval.tip, approval.bundle.path, remote=subject.remote),
    )


__all__ = [
    "PR_PAGE_LIMIT",
    "RemoteRemoval",
    "RemoteSubject",
    "check_subject",
    "closed_pr",
    "delete_rejected_remote",
    "issue_remote_requests",
    "pr_runner",
]
