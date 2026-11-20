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
4. REPOSITORY: a ``.git`` marker at any depth. Phase 1 runs no git, so it
   cannot tell a standalone repository (which has no repository rule and goes
   down the ordinary ladder) from a registered worktree or a related clone
   (which may be PROTECTED). Until Task 2.1 classifies the marker, the entry is
   "repository, not judged" and never DISPOSABLE.
5. REFERENCED: not evaluated in Phase 1 (the reference set needs git).
6. DISPOSABLE when every file is covered by P1, P2 or P5; else UNCERTAIN.

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

#: The rungs of the order Phase 1 does not evaluate, in order.
NOT_EVALUATED: tuple[str, ...] = ("KEPT", "PROTECTED", "REFERENCED")

#: How many uncovered paths a judgement keeps, so a huge entry stays small in memory.
MAX_UNCOVERED = 5


class Verdict(enum.Enum):
    """The fate an entry is judged to have."""

    LIVE = "LIVE"
    STUCK = "STUCK"
    REPOSITORY = "REPOSITORY"
    DISPOSABLE = "DISPOSABLE"
    UNCERTAIN = "UNCERTAIN"


class Proof(enum.Enum):
    """A proof of no value that needs no git."""

    P1 = "P1"
    P2 = "P2"
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


def _coverage(nodes: Sequence[Node]) -> tuple[tuple[Proof, ...], list[str]]:
    venvs = _venv_directories(nodes)
    used: set[Proof] = set()
    uncovered: list[str] = []
    for node in nodes:
        if node.kind is NodeKind.DIRECTORY and not node.empty:
            continue
        proof = _proof_for(node, venvs)
        if proof is None:
            uncovered.append(node.path)
        else:
            used.add(proof)
    return tuple(proof for proof in Proof if proof in used), uncovered


def judge(walk: Bounded[EntryStats], *, age: EntryAge, liveness: tuple[str, ...]) -> Judgement:
    """Judge one walked entry, given its age and any liveness reasons."""
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
    if markers:
        return result(
            Verdict.REPOSITORY,
            "repository, not judged: which kind of repository it is (Task 2.1) is not yet known",
        )
    proofs, uncovered = _coverage(stats.nodes)
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
    "NOT_EVALUATED",
    "REGENERABLE_DIRECTORIES",
    "VENV_MARKER",
    "Judgement",
    "Proof",
    "RepositoryMarker",
    "Verdict",
    "judge",
]
