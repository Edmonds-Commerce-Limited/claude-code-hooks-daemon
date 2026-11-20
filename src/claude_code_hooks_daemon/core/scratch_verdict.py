"""One verdict per scratch entry, and the proofs that need no git (Plan 00627 Task 1.6).

The verdicts are DESIGN.md section 3.1's, first match wins. STUCK is checked
second rather than last as 3.1 lists it, because no later rung can be judged
from a walk that did not finish:

1. LIVE: something uses the entry now, or it is within its TTL. A fresh mtime
   found by a partial walk still proves this: the walk can only have missed a
   NEWER mtime, never an older one.
2. STUCK: the walk did not finish, or a file has another name outside the
   entry. Nothing is concluded about an entry that was not read whole.
3. KEPT: not evaluated in Phase 1 (no keep marker or pause store exists yet).
   Also STUCK: a repository in the entry could not be classified
   (:mod:`~claude_code_hooks_daemon.core.scratch_repos`), or the project's
   tracked files could not be listed.
4. PROTECTED: a repository in the entry is a registered worktree, points
   outside the entry, or is related and holds work no remote holds (R6); or
   the entry holds a file the project tracks.
5. REFERENCED: not evaluated yet (Task 2.4).
6. DISPOSABLE when every file is covered by P1, P2, P4 or P5; else UNCERTAIN.
   A standalone repository has no rule of its own (R7 overturned): its ``.git``
   is ordinary content. P4 covers a clean pushed related repository's git
   directory and tracked files.

Coverage is judged over every non-directory node and every empty directory.
P1 trusts a regular file's own basename only; P2 covers anything, links and
special files included, inside a regenerable directory; P5 covers a zero-byte
regular file or an empty directory.
"""

from __future__ import annotations

import enum
import fnmatch
from collections.abc import Sequence
from dataclasses import dataclass

from claude_code_hooks_daemon.core.scratch_clock import EntryAge
from claude_code_hooks_daemon.core.scratch_repos import RepoFindings
from claude_code_hooks_daemon.core.scratch_walk import EntryStats, Node, NodeKind
from claude_code_hooks_daemon.utils.bounded_walk import Bounded
from claude_code_hooks_daemon.utils.regenerable_paths import is_regenerable

#: Plan 00560's consumed message, body and journal shapes, plus log shapes (P1).
CONSUMED_SHAPES: tuple[str, ...] = (
    "commit-*.txt",
    "commit-*.md",
    "merge-*.txt",
    "merge-*.md",
    "tag-*.txt",
    "pr-*.md",
    "issue-*.md",
    "issue-*.json",
    "comment-*.md",
    "close-*.md",
    "gh-*.md",
    "journal-*.md",
    "*.log",
    "*.out",
    "ci-*",
    "qa-*",
    "push-*",
)

#: Directories rebuilt on demand, in the ``regenerable_paths`` dialect (P2).
REGENERABLE_DIRECTORIES: tuple[str, ...] = (
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "node_modules/",
    "*.egg-info/",
)

#: A regular file of this name makes its directory a virtual environment (P2).
VENV_MARKER = "pyvenv.cfg"

#: The rungs of the order not evaluated yet, in order.
NOT_EVALUATED: tuple[str, ...] = ("KEPT", "REFERENCED")

#: How many uncovered paths a judgement keeps, so a huge entry stays small in memory.
MAX_UNCOVERED = 5


class Verdict(enum.Enum):
    """The fate an entry is judged to have."""

    LIVE = "LIVE"
    STUCK = "STUCK"
    PROTECTED = "PROTECTED"
    DISPOSABLE = "DISPOSABLE"
    UNCERTAIN = "UNCERTAIN"


class Proof(enum.Enum):
    """A proof of no value that needs no git."""

    P1 = "P1"
    P2 = "P2"
    P4 = "P4"
    P5 = "P5"


class RepositoryMarker(enum.Enum):
    """Whether the walk found a ``.git`` marker; UNKNOWN when it stopped without one."""

    FOUND = "found"
    NONE = "none"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Judgement:
    """An entry's verdict and why."""

    verdict: Verdict
    reasons: tuple[str, ...]
    #: For DISPOSABLE, the proofs that covered the entry, in :class:`Proof` order.
    proofs: tuple[Proof, ...]
    repository: RepositoryMarker
    git_markers: tuple[str, ...]
    #: For UNCERTAIN, the first uncovered paths (at most :data:`MAX_UNCOVERED`).
    uncovered: tuple[str, ...] = ()
    uncovered_count: int = 0


def _venv_directories(nodes: Sequence[Node]) -> tuple[str, ...]:
    suffix = f"/{VENV_MARKER}"
    return tuple(
        node.path[: -len(suffix)]
        for node in nodes
        if node.kind is NodeKind.FILE and node.path.endswith(suffix)
    )


def _proof_for(node: Node, venvs: Sequence[str]) -> Proof | None:
    regenerable_path = f"{node.path}/" if node.kind is NodeKind.DIRECTORY else node.path
    if is_regenerable(regenerable_path, REGENERABLE_DIRECTORIES) or any(
        node.path.startswith(f"{venv}/") for venv in venvs
    ):
        return Proof.P2
    if node.kind is NodeKind.FILE:
        basename = node.path.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatchcase(basename, shape) for shape in CONSUMED_SHAPES):
            return Proof.P1
        if node.size == 0:
            return Proof.P5
    if node.kind is NodeKind.DIRECTORY and node.empty:
        return Proof.P5
    return None


def _p4(path: str, repos: RepoFindings | None) -> bool:
    """Covered by P4: a tracked file exactly, or anything inside a covered git directory."""
    if repos is None:
        return False
    return path in repos.p4_covered or any(
        path.startswith(f"{git_dir}/") for git_dir in repos.p4_git_dirs
    )


def _coverage(
    nodes: Sequence[Node], repos: RepoFindings | None = None
) -> tuple[tuple[Proof, ...], list[str]]:
    venvs = _venv_directories(nodes)
    used: set[Proof] = set()
    uncovered: list[str] = []
    for node in nodes:
        if node.kind is NodeKind.DIRECTORY and not node.empty:
            continue
        proof = Proof.P4 if _p4(node.path, repos) else _proof_for(node, venvs)
        if proof is None:
            uncovered.append(node.path)
        else:
            used.add(proof)
    return tuple(proof for proof in Proof if proof in used), uncovered


#: Said when an entry holds a repository and no classification was run.
NOT_CLASSIFIED = "a repository in the entry was not classified (the project's git was not read)"

#: Said when the project's tracked files under the root could not be listed.
TRACKED_UNKNOWN = "the project's tracked files could not be listed"


def judge(
    walk: Bounded[EntryStats],
    *,
    age: EntryAge,
    liveness: tuple[str, ...],
    repos: RepoFindings | None = None,
    tracked: tuple[str, ...] | None = (),
) -> Judgement:
    """Judge one walked entry, given its age and any liveness reasons.

    ``repos`` is the entry's repository classification (None: not run).
    ``tracked`` lists the entry's paths the project tracks (None: unknown).
    """
    stats = walk.value
    markers = stats.git_markers
    if markers:
        repository = RepositoryMarker.FOUND
    else:
        repository = RepositoryMarker.NONE if walk.complete else RepositoryMarker.UNKNOWN

    def result(verdict: Verdict, *reasons: str, proofs: tuple[Proof, ...] = ()) -> Judgement:
        return Judgement(verdict, reasons, proofs, repository, markers)

    if liveness:
        return result(Verdict.LIVE, *liveness)
    if not age.due:
        return result(Verdict.LIVE, "within its TTL")
    if not walk.complete:
        return result(Verdict.STUCK, walk.reason)
    if stats.multi_linked:
        count = len(stats.multi_linked)
        return result(
            Verdict.STUCK,
            f"{count} file(s) have another name outside the entry, first {stats.multi_linked[0]}",
        )
    if tracked is None:
        return result(Verdict.STUCK, TRACKED_UNKNOWN)
    if markers and repos is None:
        return result(Verdict.STUCK, NOT_CLASSIFIED)
    if repos is not None and repos.stuck:
        return result(Verdict.STUCK, *repos.stuck)
    if repos is not None and repos.protected:
        return result(Verdict.PROTECTED, *repos.protected)
    if tracked:
        return result(
            Verdict.PROTECTED,
            f"holds {len(tracked)} file(s) the project tracks, first {tracked[0]}",
        )
    proofs, uncovered = _coverage(stats.nodes, repos)
    if not uncovered:
        return result(Verdict.DISPOSABLE, "every file is covered by a proof", proofs=proofs)
    return Judgement(
        Verdict.UNCERTAIN,
        (f"{len(uncovered)} path(s) covered by no proof",),
        (),
        repository,
        markers,
        uncovered=tuple(uncovered[:MAX_UNCOVERED]),
        uncovered_count=len(uncovered),
    )


__all__ = [
    "CONSUMED_SHAPES",
    "MAX_UNCOVERED",
    "NOT_CLASSIFIED",
    "NOT_EVALUATED",
    "REGENERABLE_DIRECTORIES",
    "TRACKED_UNKNOWN",
    "VENV_MARKER",
    "Judgement",
    "Proof",
    "RepositoryMarker",
    "Verdict",
    "judge",
]
