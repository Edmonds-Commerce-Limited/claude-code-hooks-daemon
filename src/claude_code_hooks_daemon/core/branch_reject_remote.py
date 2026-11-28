"""The no-value route for a REMOTE branch whose pull request closed unmerged (ledger N763).

A remote branch the remote-delete proof refuses (its work is found nowhere else) is
otherwise deletable by no agent route. This module lets one go on the same two facts
the local route rests on (:mod:`branch_reject`): an independent reviewer's no-value
verdict for exactly the remote tip, and a recovery bundle the guard wrote and
verified. It adds what only a remote copy needs, every one re-read at request time
AND at delete time:

- the branch's pull request was CLOSED without being merged, and its head commit is
  the remote tip (commits pushed after closing were never judged by anyone);
- no OPEN pull request uses the branch as its BASE (deleting it would close them);
- every gh call names the repository of the remote's configured URL (``gh -R``);
- the remote tip and the remote's default are what ``refs/remotes/<remote>/`` records,
  on the fetch URL and on every push URL;
- the branch is not merged (the existing proven route deletes that) and no worktree
  has a local branch of that name checked out.

Every unreadable fact refuses. The delete is a ``--force-with-lease`` push on the
approved tip, made only after the ledger line and the single-use claim are written.
"""

from __future__ import annotations

import json
import re
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
from claude_code_hooks_daemon.utils.github_ssh_alias import (
    GITHUB_SSH_OVER_HTTPS_HOST,
    GITHUB_SSH_OVER_HTTPS_PORT,
    resolve_ssh_host_alias,
)

#: ``gh pr list`` page size. A FULL page is unreadable: a PR past it could be open.
PR_PAGE_LIMIT = 20
_PR_FIELDS = "number,state,headRefName,headRefOid,isCrossRepository"
_STATE_CLOSED = "CLOSED"
_STATE_OPEN = "OPEN"
_STATE_MERGED = "MERGED"
_STATES = frozenset({_STATE_CLOSED, _STATE_OPEN, _STATE_MERGED})
_GIT_SUFFIX = ".git"
#: ``_`` is admitted for ssh config aliases (``github.com-my_key``); a real host that
#: carries one is passed to gh unchanged and fails closed there.
_HOST = r"(?P<host>[A-Za-z0-9][A-Za-z0-9._-]*)"
_SSH_SCHEME = "ssh"
#: ``(scheme, host, port)`` of GitHub's ssh-over-443 address: the only accepted pair of a
#: host and a non-default port, as that port reaches github.com itself.
_SSH_OVER_HTTPS = (_SSH_SCHEME, GITHUB_SSH_OVER_HTTPS_HOST, GITHUB_SSH_OVER_HTTPS_PORT)
_PATH = r"(?P<owner>[^/:@\s]+)/(?P<repo>[^/:@\s]+?)/?"
_URL_FORM = re.compile(
    rf"(?P<scheme>https|http|ssh|git)://(?:[^@/\s]+@)?{_HOST}(?::(?P<port>[0-9]+))?/{_PATH}"
)
#: The only port each scheme may name: ``gh -R`` takes no port, so any other one
#: would be dropped and the PR state read from a different server.
_DEFAULT_PORTS = {"https": "443", "http": "80", "ssh": "22", "git": "9418"}
_SCP_FORM = re.compile(rf"(?:[A-Za-z0-9._-]+@)?{_HOST}:{_PATH}")
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")
_REPO = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_.-]*")


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


def repository_slug(url: str) -> str:
    """``host/owner/repo`` of a GitHub-style remote URL, the form ``gh -R`` takes.

    Accepts ``https://[user@]host[:port]/owner/repo[.git]`` (the port only when it is the
    scheme's default, as ``gh -R`` carries none), the same with ``ssh://`` or
    ``git://``, and ``[user@]host:owner/repo[.git]``. The one non-default port accepted
    is 443 on ``ssh://ssh.github.com``, GitHub's documented ssh-over-443 address. The
    host is lowercased, as gh lowercases it. In the two ssh-style forms (scp and
    ``ssh://``) a ``github.com-<suffix>`` ssh config alias and ``ssh.github.com`` name
    ``github.com`` (:mod:`github_ssh_alias`); every other host is kept, and gh fails
    closed on an unknown one. Anything else (a local path, a
    ``file://`` URL, a missing or extra path part, an option-like or dot-only part)
    raises RejectRefusedError: gh must never be left to choose the repository itself.
    """
    match = _URL_FORM.fullmatch(url) or _SCP_FORM.fullmatch(url)
    if match is None:
        raise RejectRefusedError(
            "the remote URL names no GitHub-style repository (host/owner/repo), so the "
            "pull request state cannot be read from the repository the delete goes to"
        )
    groups = match.groupdict()
    host, owner, repo = match.group("host").lower(), match.group("owner"), match.group("repo")
    port = groups.get("port")
    ssh_over_https = (groups.get("scheme"), host, port) == _SSH_OVER_HTTPS
    if port is not None and port != _DEFAULT_PORTS[str(groups["scheme"])] and not ssh_over_https:
        raise RejectRefusedError(
            f"the remote URL names port {port}, which `gh -R` cannot carry, so the "
            "repository the pull request state is read from cannot be named"
        )
    if groups.get("scheme", _SSH_SCHEME) == _SSH_SCHEME:
        host = resolve_ssh_host_alias(host)
    repo = repo.removesuffix(_GIT_SUFFIX)
    if not _OWNER.fullmatch(owner) or not _REPO.fullmatch(repo) or repo in {".", ".."}:
        raise RejectRefusedError(
            "the remote URL's owner or repository part is not a plain name, so the "
            "repository the pull request state is read from cannot be named"
        )
    return f"{host}/{owner}/{repo}"


def configured_repository(top: Path, remote: str) -> str:
    """The ``gh -R`` repository of ``remote``'s configured URL (``remote.<r>.url``).

    The configured URL is the repository's identity; an ``insteadOf`` rewrite only
    changes how git reaches it, and :func:`live_refs_problem` separately confirms the
    fetch and push destinations hold the judged commits. Exactly one URL is required.
    """
    result = run_git(top, "config", "--get-all", f"remote.{remote}.url")
    urls = [line for line in result.stdout.splitlines() if line]
    if result.returncode != 0 or len(urls) != 1:
        raise RejectRefusedError(
            f"`{remote}` does not have exactly one configured URL, so the repository the "
            "pull request state is read from cannot be named"
        )
    return repository_slug(urls[0])


def refuse_open_base_prs(runner: GhRunner, repository: str, name: str) -> None:
    """Refuse when any OPEN pull request uses ``name`` as its BASE branch.

    Deleting a base branch closes every open pull request based on it, which is work
    the review never judged. An unreadable answer refuses too.
    """
    args = ["pr", "list", "-R", repository, "--base", name, "--state", "open"]
    unreadable = f"the open pull requests based on `{name}` could not be read"
    try:
        raw = runner([*args, "--json", "number", "--limit", str(PR_PAGE_LIMIT)])
        data: Any = json.loads(raw)
    except GhError as exc:
        raise RejectRefusedError(f"{unreadable} ({exc}); nothing is removed") from exc
    except ValueError as exc:
        raise RejectRefusedError(f"{unreadable}: gh did not answer JSON ({exc})") from exc
    if not isinstance(data, list) or not all(
        isinstance(record, Mapping)
        and isinstance(record.get("number"), int)
        and not isinstance(record.get("number"), bool)
        for record in data
    ):
        raise RejectRefusedError(f"{unreadable}: gh did not answer a list of numbered records")
    if data:
        numbers = ", ".join(f"#{record['number']}" for record in data)
        raise RejectRefusedError(
            f"open pull request(s) {numbers} are based on `{name}`; deleting it would close "
            "them. Retarget or close them first"
        )


def closed_pr(runner: GhRunner, repository: str, name: str, tip: str) -> int:
    """The number of a CLOSED-unmerged pull request of ``name`` whose head is ``tip``.

    Asked of ``repository`` (``gh -R``), never of whatever gh would pick. Raises
    RejectRefusedError unless gh answers, every same-repository PR headed by ``name``
    is closed unmerged, and one of them has ``tip`` as its head commit. A PR from a
    fork (``isCrossRepository``) or with another head name is not this branch's.
    """
    args = ["pr", "list", "-R", repository, "--head", name, "--state", "all"]
    args += ["--json", _PR_FIELDS]
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
    #: ``host/owner/repo``: the repository every gh call of the route names (``-R``).
    repository: str


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
    if name.startswith("-"):
        raise RejectRefusedError(f"`{name}` is not a literal branch name (it reads as an option)")
    problem = named_ref_problem(remote, name, default, branches)
    if problem is not None:
        raise RejectRefusedError(problem)
    ref = subject_ref(name, remote)
    top = _git_top(repo)
    repository = configured_repository(top, remote)
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
    pr_number = closed_pr(runner, repository, name, tip)
    refuse_open_base_prs(runner, repository, name)
    return RemoteSubject(
        remote=remote,
        name=name,
        tip=tip,
        default=default,
        default_ref=default_ref,
        default_sha=default_sha,
        pr_number=pr_number,
        top=top,
        repository=repository,
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
    "configured_repository",
    "delete_rejected_remote",
    "issue_remote_requests",
    "pr_runner",
    "refuse_open_base_prs",
    "repository_slug",
]
