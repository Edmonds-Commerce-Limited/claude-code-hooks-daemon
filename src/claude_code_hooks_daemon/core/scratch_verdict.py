"""One verdict per scratch entry, and the proofs that need no git (Plan 00627 Task 1.6).

The verdicts are DESIGN.md section 3.1's, first match wins. STUCK is checked
second rather than last as 3.1 lists it, because no later rung can be judged
from a walk that did not finish:

1. LIVE: something uses the entry now, or it is within its TTL. A fresh mtime
   found by a partial walk still proves this: the walk can only have missed a
   NEWER mtime, never an older one. An entry LIVE only because it is within
   its TTL also carries ``ttl_hold``: the verdict the remaining rungs give it.
2. STUCK: liveness could not be read (no process working directory was
   readable, or some pids were not), the walk did not finish, or a file has
   another name outside the entry. Nothing is concluded about an entry that
   was not read whole.
3. KEPT: a ``.scratch-keep`` of any kind directly in the entry (a human's
   pin, R15; an agent may not create one, ``R-SCRATCH-KEEP-MARKER``). An
   agent's bounded pause is a keep on the ARCHIVE, not an entry verdict.
   Also STUCK, after KEPT: a repository in the entry could not be classified
   (:mod:`~claude_code_hooks_daemon.core.scratch_repos`), or the project's
   tracked files could not be listed, or whether a tracked file names the entry
   is unknown (:mod:`~claude_code_hooks_daemon.core.scratch_references`).
4. PROTECTED: a repository in the entry is a registered worktree, points
   outside the entry, or is related and holds work no remote holds (R6); or
   the entry holds a file the project tracks.
5. REFERENCED: a tracked file, on a revision that can still reach the default
   branch or in the working tree, names a path in the entry (DESIGN.md 3.4).
6. DISPOSABLE when every file is covered by P1, P2, P3, P4, P5 or P7; else
   UNCERTAIN. P3 is computed by the caller (it hashes files) and passed in.
   P4 covers a clean pushed related repository's git directory and tracked
   files. P7 covers a standalone repository's work tree and git directory: the
   coordinator's ruling applying the owner's "scratch repo ... no value"
   (DESIGN.md section 0). It stops at the deepest other repository root, and
   files beside the repository are judged on their own. Neither P4 nor P7
   covers a non-empty node in a git directory's ``objects`` store: a clone
   anywhere on disk may borrow it through ``alternates``, so an entry holding
   a repository with objects is UNCERTAIN (the long hold), never DISPOSABLE.

Coverage is judged over every non-directory node and every empty directory.
P1 trusts a regular file's own basename only; P2 covers anything, links and
special files included, inside a regenerable directory, and in a virtual
environment only the venv's own layout, never a file beside it; P5 covers a zero-byte
regular file or an empty directory.
"""

from __future__ import annotations

import dataclasses
import enum
import fnmatch
import logging
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.core.scratch_clock import EntryAge
from claude_code_hooks_daemon.core.scratch_references import References
from claude_code_hooks_daemon.core.scratch_repos import RepoFindings
from claude_code_hooks_daemon.core.scratch_walk import EntryStats, Node, NodeKind, kind_of
from claude_code_hooks_daemon.utils.bounded_walk import Bounded
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.regenerable_paths import is_regenerable

_LOG = logging.getLogger(__name__)

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
NOT_EVALUATED: tuple[str, ...] = ()

#: A node of this name, of any kind, at the top of an entry or session directory
#: pins it for ever (R15; :func:`marker_keeps`).
KEEP_MARKER = ".scratch-keep"

#: How many uncovered paths a judgement keeps, so a huge entry stays small in memory.
MAX_UNCOVERED = 5


class Verdict(enum.Enum):
    """The fate an entry is judged to have."""

    LIVE = "LIVE"
    STUCK = "STUCK"
    KEPT = "KEPT"
    PROTECTED = "PROTECTED"
    REFERENCED = "REFERENCED"
    DISPOSABLE = "DISPOSABLE"
    UNCERTAIN = "UNCERTAIN"


class Proof(enum.Enum):
    """A proof of no value that needs no git."""

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"
    P5 = "P5"
    P7 = "P7"


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
    #: For LIVE "within its TTL" only: the verdict the full ladder gives the entry
    #: as if it were due. None for every other judgement, so an entry LIVE for a
    #: liveness reason (process, cwd, background command) never carries one.
    #: Pressure mode (DESIGN.md section 5.5) acts on this, never on LIVE itself.
    ttl_hold: Verdict | None = None
    ttl_hold_proofs: tuple[Proof, ...] = ()


#: Top-level files a venv tool writes beside ``pyvenv.cfg`` (``python -m venv``, uv).
VENV_FILES: tuple[str, ...] = (VENV_MARKER, ".gitignore", "CACHEDIR.TAG")

#: Top-level names whose whole subtree is the venv's own layout (headers pip installs).
VENV_INCLUDE_DIRECTORIES: tuple[str, ...] = ("include", "Include")

#: Top-level names that may be the venv's link to ``lib`` (``python -m venv`` writes lib64).
VENV_LIB_LINKS: tuple[str, ...] = ("lib64", "lib32")

#: The scripts folders; only the files named by :data:`_VENV_SCRIPT` are the venv's (N3).
VENV_SCRIPT_DIRECTORIES: tuple[str, ...] = ("bin", "Scripts")

#: An interpreter a venv tool writes in its scripts folder: ``python``, ``python3.13``, ``pythonw.exe``.
_VENV_INTERPRETER = re.compile(r"pythonw?(\d+(\.\d+)?)?(\.exe)?")

#: Every file a venv tool or ensurepip writes in the scripts folder, matched whole (N3).
#: A console script pip installs later is NOT here: its name is arbitrary, so it is
#: uncovered and the entry is UNCERTAIN, which over-protects only.
_VENV_SCRIPT = re.compile(
    r"pythonw?(\d+(\.\d+)?)?(\.exe)?"
    r"|pip(\d+(\.\d+)?)?(\.exe)?"
    r"|activate(\.(sh|bash|csh|fish|nu|ps1|bat|xsh))?|Activate\.ps1|activate_this\.py"
    r"|deactivate(\.(bat|nu))?|pydoc(\.bat)?"
)

#: The installed-package tree of a lib folder: ``lib/python3.13/site-packages/`` (N3).
_SITE_PACKAGES = re.compile(
    r"(lib|lib64|lib32)/python\d+\.\d+/site-packages(/.*)?|Lib/site-packages(/.*)?"
)


def _is_interpreter(relative: str) -> bool:
    folder, _, name = relative.partition("/")
    return folder in VENV_SCRIPT_DIRECTORIES and bool(_VENV_INTERPRETER.fullmatch(name))


def _is_venv(venv: str, paths: Sequence[str]) -> bool:
    """The real venv shape: an exact interpreter in the scripts folder and a site-packages tree."""
    prefix = f"{venv}/"
    below = [path[len(prefix) :] for path in paths if path.startswith(prefix)]
    has_interpreter = any(_is_interpreter(relative) for relative in below)
    has_lib = any(_SITE_PACKAGES.fullmatch(relative) for relative in below)
    return has_interpreter and has_lib


def _venv_directories(nodes: Sequence[Node]) -> tuple[str, ...]:
    """Directories that hold a regular ``pyvenv.cfg`` AND the venv's own layout (F-BYPS 4)."""
    suffix = f"/{VENV_MARKER}"
    paths = [node.path for node in nodes]
    candidates = (
        node.path[: -len(suffix)]
        for node in nodes
        if node.kind is NodeKind.FILE and node.path.endswith(suffix)
    )
    return tuple(venv for venv in candidates if _is_venv(venv, paths))


def _in_venv_layout(node: Node, venv: str) -> bool:
    """True only for the files a venv tool writes, never a user file in or beside them (N3).

    Covered: the top-level :data:`VENV_FILES`, a ``lib64``/``lib32`` link, the
    ``include`` tree, the named scripts directly in ``bin``/``Scripts``, and the
    ``site-packages`` tree of a lib folder. Anything else (``bin/probe.py``,
    ``lib/helpers.py``, ``share/notes.md``, a top-level FILE named ``share``) is
    uncovered.
    """
    if not node.path.startswith(f"{venv}/"):
        return False
    relative = node.path[len(venv) + 1 :]
    top, _, below = relative.partition("/")
    if not below:
        if node.kind is NodeKind.FILE:
            return top in VENV_FILES
        return node.kind is NodeKind.SYMLINK and top in VENV_LIB_LINKS
    if top in VENV_INCLUDE_DIRECTORIES:
        return True
    if top in VENV_SCRIPT_DIRECTORIES:
        return (
            "/" not in below
            and node.kind is not NodeKind.DIRECTORY
            and bool(_VENV_SCRIPT.fullmatch(below))
        )
    return bool(_SITE_PACKAGES.fullmatch(relative))


def _proof_for(node: Node, venvs: Sequence[str]) -> Proof | None:
    regenerable_path = f"{node.path}/" if node.kind is NodeKind.DIRECTORY else node.path
    if is_regenerable(regenerable_path, REGENERABLE_DIRECTORIES) or any(
        _in_venv_layout(node, venv) for venv in venvs
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


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(f"{root}/")


def _p7(path: str, repos: RepoFindings | None) -> bool:
    """Covered by P7: the deepest repository root holding ``path`` is a standalone one."""
    if repos is None:
        return False
    holders = [
        (len(root), root in repos.standalone_roots)
        for root in (*repos.standalone_roots, *repos.other_roots)
        if _under(path, root)
    ]
    return bool(holders) and max(holders)[1]


#: The name of a git directory's object store, beside its ``HEAD``.
_OBJECTS = "objects"


def object_stores(nodes: Sequence[Node]) -> tuple[str, ...]:
    """Every ``objects`` directory beside a ``HEAD`` (of any kind): a git directory's store.

    Git accepts a symbolic-link ``HEAD``, so the kind is not checked: a false
    match only over-protects.
    """
    suffix = "/HEAD"
    return tuple(
        f"{node.path[: -len(suffix)]}/{_OBJECTS}" for node in nodes if node.path.endswith(suffix)
    )


def in_object_store(node: Node, stores: Sequence[str]) -> bool:
    """True for a non-empty node in an object store, which only P5 may cover (finding 1).

    A clone made with ``git clone --shared`` anywhere on disk borrows these
    objects through its ``alternates`` file, and no walk of the project can find
    it, so P4 and P7 must not give the store the short hold.
    """
    return any(_under(node.path, store) for store in stores) and not (
        node.empty or (node.kind is NodeKind.FILE and node.size == 0)
    )


def _coverage(
    nodes: Sequence[Node],
    repos: RepoFindings | None = None,
    p3: frozenset[str] = frozenset(),
) -> tuple[tuple[Proof, ...], list[str]]:
    venvs = _venv_directories(nodes)
    stores = object_stores(nodes)
    used: set[Proof] = set()
    uncovered: list[str] = []
    for node in nodes:
        if node.kind is NodeKind.DIRECTORY and not node.empty:
            continue
        if in_object_store(node, stores):
            uncovered.append(node.path)
            continue
        if _p4(node.path, repos):
            proof: Proof | None = Proof.P4
        elif _p7(node.path, repos):
            proof = Proof.P7
        else:
            proof = _proof_for(node, venvs)
            if proof is None and node.path in p3 and node.kind is NodeKind.FILE:
                proof = Proof.P3
        if proof is None:
            uncovered.append(node.path)
        else:
            used.add(proof)
    return tuple(proof for proof in Proof if proof in used), uncovered


def uncovered_nodes(nodes: Sequence[Node], repos: RepoFindings | None) -> list[Node] | None:
    """Every node no proof but P3 could still cover (the whole list, never capped).

    None when an uncovered node is in an object store: P3 can never cover one,
    so hashing the rest would only spend the shared budget.
    """
    _proofs, uncovered = _coverage(nodes, repos)
    wanted = set(uncovered)
    found = [node for node in nodes if node.path in wanted]
    stores = object_stores(nodes)
    if any(in_object_store(node, stores) for node in found):
        return None
    return found


#: Said when an entry holds a repository and no classification was run.
NOT_CLASSIFIED = "a repository in the entry was not classified (the project's git was not read)"

#: The reason of an entry held by time alone (its ``ttl_hold`` says what it would be when due).
WITHIN_TTL = "within its TTL"

#: Said when the project's tracked files under the root could not be listed.
TRACKED_UNKNOWN = "the project's tracked files could not be listed"


def marker_keeps(kind: NodeKind | None) -> bool:
    """The one keep-marker rule: a node named :data:`KEEP_MARKER` keeps, whatever its kind.

    ``kind`` is what an ``lstat`` of ``<directory>/.scratch-keep`` found, or
    None when nothing has that name. A regular file, a symlink (to a file,
    dangling, or a loop), a directory, a special file, and a name that could
    not be read (:attr:`NodeKind.UNREAD`) all keep: the marker is a human's pin
    (R15), and a marker that cannot be read safely must never lead to an
    archive. Used for an entry root (:func:`has_keep_marker`, from the walk)
    and for a session directory (:func:`keep_marker_present`, a fresh read).
    """
    return kind is not None


def keep_marker_present(directory: Path) -> bool:
    """True when ``directory`` holds a keep marker now, by :func:`marker_keeps`.

    Read by ``lstat``, so a link is never followed. Only ``FileNotFoundError``
    means absent; any other failure is :attr:`NodeKind.UNREAD`, read as kept.
    """
    try:
        kind = kind_of(os.lstat(directory / KEEP_MARKER).st_mode)
    except FileNotFoundError:
        return marker_keeps(None)
    except OSError as exc:
        log_and_continue(
            _LOG,
            exc,
            reason=f"{directory}: keep marker unreadable, read as kept (fail closed)",
        )
        kind = NodeKind.UNREAD
    return marker_keeps(kind)


def has_keep_marker(stats: EntryStats) -> bool:
    """True when the walk found a node named :data:`KEEP_MARKER` directly in the entry.

    Decided by :func:`marker_keeps`, the rule a session directory's marker is read by.
    """
    if stats.kind is not NodeKind.DIRECTORY:
        return False
    wanted = f"{stats.name}/{KEEP_MARKER}"
    found = next((node.kind for node in stats.nodes if node.path == wanted), None)
    return marker_keeps(found)


def judge(
    walk: Bounded[EntryStats],
    *,
    age: EntryAge,
    liveness: tuple[str, ...],
    references: References,
    repos: RepoFindings | None = None,
    tracked: tuple[str, ...] | None = (),
    p3: frozenset[str] = frozenset(),
    liveness_unknown: str = "",
    keep_reason: str = "",
) -> Judgement:
    """Judge one walked entry, given its age and any liveness reasons.

    ``liveness_unknown`` says why the absence of a liveness reason proves
    nothing (no process working directory could be read): a due entry is then
    STUCK, since "no process found in it" was never established.
    ``repos`` is the entry's repository classification (None: not run).
    ``tracked`` lists the entry's paths the project tracks (None: unknown).
    ``p3`` holds the regular files whose blob the remote's default tip holds.
    ``references`` is required, so no caller can skip the REFERENCED rung.
    ``keep_reason`` is the first line of the entry's :data:`KEEP_MARKER`, read
    by the caller; whether the entry is KEPT is decided from the walk alone.
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
        # Held by time alone: judge the rest of the ladder so pressure mode can
        # tell an idle young entry from one a keep marker, reference or repo holds.
        underlying = judge(
            walk,
            age=dataclasses.replace(age, due=True),
            liveness=liveness,
            references=references,
            repos=repos,
            tracked=tracked,
            p3=p3,
            liveness_unknown=liveness_unknown,
            keep_reason=keep_reason,
        )
        return dataclasses.replace(
            result(Verdict.LIVE, WITHIN_TTL),
            ttl_hold=underlying.verdict,
            ttl_hold_proofs=underlying.proofs,
        )
    if liveness_unknown:
        return result(Verdict.STUCK, f"liveness unknown: {liveness_unknown}")
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
    if references.unknown:
        return result(Verdict.STUCK, references.unknown)
    if has_keep_marker(stats):
        return result(
            Verdict.KEPT, f"pinned by {KEEP_MARKER}: {keep_reason or '(no reason given)'}"
        )
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
    if references.sites:
        return result(
            Verdict.REFERENCED,
            f"named by {len(references.sites)} tracked line(s), first {references.sites[0]}",
        )
    proofs, uncovered = _coverage(stats.nodes, repos, p3)
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
    "KEEP_MARKER",
    "MAX_UNCOVERED",
    "NOT_CLASSIFIED",
    "NOT_EVALUATED",
    "REGENERABLE_DIRECTORIES",
    "TRACKED_UNKNOWN",
    "VENV_FILES",
    "VENV_INCLUDE_DIRECTORIES",
    "VENV_LIB_LINKS",
    "VENV_MARKER",
    "VENV_SCRIPT_DIRECTORIES",
    "WITHIN_TTL",
    "Judgement",
    "Proof",
    "RepositoryMarker",
    "Verdict",
    "has_keep_marker",
    "judge",
    "keep_marker_present",
    "marker_keeps",
    "uncovered_nodes",
]
