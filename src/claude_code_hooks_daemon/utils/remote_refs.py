"""What a remote holds, from ONE bounded ``git ls-remote`` (issue #166).

A remote can hold a branch's commits under a namespace the default refspec never
fetches (``refs/archive/<name>``), so no remote-tracking ref shows them. The
explicit CLI commands (``branch-sweep``, ``delete-branch``) list the remote once
and accept a ref at, or descending from, a branch tip as proof the remote holds
the content. Hook paths never call this: they stay network-free.

A failed or timed-out listing carries its reason in ``failure`` and is never
proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import run_git

_HEAD_LINE = "HEAD"
_PEELED_SUFFIX = "^{}"
_NO_PROMPT_ENV = {"GIT_TERMINAL_PROMPT": "0"}


@dataclass(frozen=True)
class RemoteRefs:
    """One remote's listing: ``(ref, sha)`` pairs, or why it could not be read."""

    remote: str
    refs: tuple[tuple[str, str], ...] = ()
    failure: str | None = None


def parse_listing(stdout: str) -> tuple[tuple[str, str], ...]:
    """The ``(ref, sha)`` pairs of ``ls-remote`` output, without ``HEAD`` and peeled lines."""
    pairs: list[tuple[str, str]] = []
    for line in stdout.splitlines():
        sha, separator, ref = line.partition("\t")
        if separator and ref != _HEAD_LINE and not ref.endswith(_PEELED_SUFFIX):
            pairs.append((ref, sha))
    return tuple(pairs)


def list_remote_refs(repo: Path, remote: str) -> RemoteRefs:
    """List ``remote`` with one bounded ``ls-remote``; a failure is returned, not raised."""
    result = run_git(
        repo,
        "ls-remote",
        remote,
        timeout=Timeout.GIT_LS_REMOTE,
        env=_NO_PROMPT_ENV,
    )
    if result.returncode != 0:
        reason = result.stderr.strip() or f"git ls-remote exited {result.returncode}"
        return RemoteRefs(remote, failure=reason)
    return RemoteRefs(remote, refs=parse_listing(result.stdout))


def _exists_locally(repo: Path, sha: str) -> bool:
    return run_git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def _is_ancestor(repo: Path, tip: str, sha: str) -> bool:
    return run_git(repo, "merge-base", "--is-ancestor", tip, sha).returncode == 0


def holder_of(repo: Path, listing: RemoteRefs, tip: str) -> str | None:
    """The remote ref that holds ``tip``, or None.

    A ref whose sha equals ``tip`` wins; otherwise a ref whose sha descends from
    it, which is checked only when that commit exists locally (an object this
    clone lacks cannot be shown to descend from ``tip``). Refs are tried in name
    order so the answer is stable.
    """
    if listing.failure is not None:
        return None
    ordered = sorted(listing.refs)
    for ref, sha in ordered:
        if sha == tip:
            return ref
    for ref, sha in ordered:
        if _exists_locally(repo, sha) and _is_ancestor(repo, tip, sha):
            return ref
    return None


class LazyRemoteRefs:
    """A listing made on first use, so a run that never needs the remote never asks.

    ``delete-branch`` of a merged branch and a sweep with nothing CONTAINED
    NOWHERE make no network call. The first ``resolve`` makes the one
    ``ls-remote`` and every later one reuses it.
    """

    def __init__(self, repo: Path, remote: str) -> None:
        self._repo = repo
        self._remote = remote
        self._listing: RemoteRefs | None = None

    @property
    def resolved(self) -> RemoteRefs | None:
        """The listing if one was made, else None."""
        return self._listing

    def resolve(self) -> RemoteRefs:
        """The listing, made on the first call."""
        if self._listing is None:
            self._listing = list_remote_refs(self._repo, self._remote)
        return self._listing


#: A listing already made, or one that will be made if (and only if) it is needed.
RemoteSource = RemoteRefs | LazyRemoteRefs


def resolve_source(source: RemoteSource) -> RemoteRefs:
    """The listing behind ``source``, making it now when it is lazy."""
    return source.resolve() if isinstance(source, LazyRemoteRefs) else source


def made_listing(source: RemoteSource | None) -> RemoteRefs | None:
    """The listing ``source`` produced, or None when none was ever made."""
    return source.resolved if isinstance(source, LazyRemoteRefs) else source
