"""The read-only scratch sweep: one verdict per entry, as a table or JSON (Plan 00627 Task 1.7).

The sweep is a report and nothing else. It lists, ``lstat``s and judges; it
never creates, moves, packs or removes anything, and prints no file content
and no delete command; a filing proposal is printed, never acted on. Git is run once per sweep in the project (tracked files
under the root, worktrees, live remote tips, and the tracked lines that name
a scratch path) and, for a due entry holding a
repository, inside that repository under the rules of
:mod:`~claude_code_hooks_daemon.core.scratch_repos`.

One :class:`~claude_code_hooks_daemon.core.scratch_walk.WalkBudget` covers the
whole run. Each entry is judged as soon as it is walked and its node list is
dropped before the next walk, so memory grows with the number of entries, not
the number of inodes. An entry reached after the budget is spent still gets a
row (STUCK, or LIVE when its root's ctime proves it), and the report says it is
incomplete and why.

Entries are judged one at a time, but one entry's ``.git`` pointer can depend
on another entry's git directory (F-BYPS 2). A post-pass reads every entry's
``.git`` file and ``commondir`` pointers: an entry another entry points into
is PROTECTED unless it is already LIVE, STUCK or PROTECTED. A pointer that
cannot be read, or an entry not walked to the end, leaves the dependencies
unknown: every DISPOSABLE row becomes STUCK and the report is incomplete.
"""

from __future__ import annotations

import dataclasses
import enum
import os
import stat
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import ScratchConfig
from claude_code_hooks_daemon.core.scratch_clock import NO_BIRTH_NOTE, EntryAge, entry_age
from claude_code_hooks_daemon.core.scratch_filing import (
    PlanIndex,
    Protection,
    build_plan_index,
    propose,
)
from claude_code_hooks_daemon.core.scratch_liveness import LivenessInputs, entry_liveness
from claude_code_hooks_daemon.core.scratch_references import (
    References,
    ReferenceSet,
    build_references,
)
from claude_code_hooks_daemon.core.scratch_repos import (
    ProjectGit,
    RepoFindings,
    blob_id,
    blob_length,
    classify_entry,
    read_small_regular_file,
)
from claude_code_hooks_daemon.core.scratch_session import (
    MANIFEST_NAME,
    is_session_dir_name,
    read_manifest,
)
from claude_code_hooks_daemon.core.scratch_verdict import (
    KEEP_MARKER,
    NOT_EVALUATED,
    Judgement,
    Proof,
    RepositoryMarker,
    Verdict,
    has_keep_marker,
    judge,
    uncovered_nodes,
)
from claude_code_hooks_daemon.core.scratch_walk import (
    EntryStats,
    NodeKind,
    ScandirFn,
    WalkBudget,
    list_entries,
    walk_entry,
)
from claude_code_hooks_daemon.core.untracked_roots import SweepRoot
from claude_code_hooks_daemon.utils.bounded_walk import Bounded
from claude_code_hooks_daemon.utils.path_containment import (
    path_is_relative_to,
    path_relative_to,
)

_SECONDS_PER_HOUR = 3600.0

#: Said when no process working directory could be read at all.
NO_CWDS_NOTE = (
    "no process working directory could be read: the working-directory liveness "
    "signal was unavailable"
)


def liveness_unknown_reason(inputs: LivenessInputs) -> str:
    """Why the working-directory liveness signal proves nothing this sweep, or ''.

    Empty cwds (no ``/proc``, another pid namespace) or any unreadable pid
    means "no process sits in the entry" was never established (F-BYPS low).
    """
    if not inputs.cwds:
        return NO_CWDS_NOTE
    if inputs.unreadable_pids:
        count = len(inputs.unreadable_pids)
        return (
            f"{count} process(es) whose working directory could not be read, "
            f"first pid {inputs.unreadable_pids[0]}"
        )
    return ""


#: Table order: what needs a human first, what is in use last.
_TABLE_ORDER = (
    Verdict.STUCK,
    Verdict.KEPT,
    Verdict.PROTECTED,
    Verdict.REFERENCED,
    Verdict.UNCERTAIN,
    Verdict.DISPOSABLE,
    Verdict.LIVE,
)

_REPOSITORY_LABEL = {
    RepositoryMarker.FOUND: "repository",
    RepositoryMarker.NONE: "-",
    RepositoryMarker.UNKNOWN: "unknown (walk incomplete)",
}


#: P3's per-sweep hashing bounds (DESIGN.md section 3.2): files and bytes read.
P3_MAX_FILES = 20_000
P3_MAX_BYTES = 256 * 1024 * 1024


@dataclass
class HashBudget:
    """How many files and bytes P3 may still hash in this sweep."""

    max_files: int = P3_MAX_FILES
    max_bytes: int = P3_MAX_BYTES
    spent: bool = False

    def take(self, size: int) -> bool:
        """Spend one file of ``size`` bytes; False (and spent) when it does not fit."""
        if self.spent or self.max_files < 1 or size > self.max_bytes:
            self.spent = True
            return False
        self.max_files -= 1
        self.max_bytes -= size
        return True


#: Said when P3's hashing budget ran out: files left are not proved, never STUCK.
P3_BUDGET_NOTE = "the P3 hashing budget ran out: later files were not hashed and stay UNCERTAIN"


@dataclass(frozen=True)
class EntryRow:
    """One entry's line of the report. Holds no node list."""

    name: str
    kind: NodeKind
    verdict: Verdict
    reasons: tuple[str, ...]
    proofs: tuple[Proof, ...]
    repository: RepositoryMarker
    git_markers: tuple[str, ...]
    walk_complete: bool
    directories: int
    files: int
    bytes: int
    age_hours: float
    due: bool
    uncovered: tuple[str, ...]
    uncovered_count: int
    #: Where the entry could be filed, and the ``mv -n`` that would do it (empty: none).
    filing_destination: str = ""
    filing_command: str = ""
    #: :attr:`Judgement.ttl_hold`: set only on a LIVE row held by its TTL alone.
    ttl_hold: Verdict | None = None
    ttl_hold_proofs: tuple[Proof, ...] = ()


def pending_verdict(row: EntryRow) -> Verdict:
    """The verdict an action would act on: a TTL-held row's ``ttl_hold``, else its verdict."""
    return row.ttl_hold if row.ttl_hold is not None else row.verdict


@dataclass(frozen=True)
class SweepReport:
    """The whole dry run."""

    root: str
    rows: tuple[EntryRow, ...]
    complete: bool
    incomplete_reasons: tuple[str, ...]
    notes: tuple[str, ...]
    not_evaluated: tuple[str, ...] = NOT_EVALUATED
    #: One report per session directory, whose children are its entries (Task 4.3).
    sessions: tuple[SweepReport, ...] = ()
    #: A session sub-report's ``(st_dev, st_ino)``: the directory it listed, checked by apply.
    identity: tuple[int, int] | None = None


@dataclass(frozen=True)
class _Container:
    """A session directory judged as a sub-root: what overrules its children, and their TTLs."""

    #: ``(verdict, reason)`` pairs computed from the container itself, never from its row.
    holds: tuple[tuple[Verdict, str], ...]
    #: Why a DISPOSABLE child cannot be proved so; "" when nothing says so.
    unproved: str
    #: TTL hours ``scratch new --ttl-hours`` recorded per child.
    recorded_ttl: dict[str, int]
    #: ``(st_dev, st_ino)`` of the directory the parent judged a session directory.
    identity: tuple[int, int] | None = None


def _relative(root: Path, project_root: Path) -> str | None:
    """``root`` from the project root, or None for a root outside the project."""
    if not path_is_relative_to(root, project_root):
        return None
    return path_relative_to(root, project_root).as_posix()


def _root_problem(root: Path) -> tuple[str, bool]:
    """Why ``root`` cannot be listed, and whether that is "it does not exist"."""
    try:
        info = root.lstat()
    except FileNotFoundError:
        return f"scratch root {root} does not exist: nothing to sweep", True
    except OSError as exc:
        return f"scratch root {root} could not be read: {type(exc).__name__}", False
    if stat.S_ISLNK(info.st_mode):
        return f"scratch root {root} is a link: not followed", False
    if not stat.S_ISDIR(info.st_mode):
        return f"scratch root {root} is not a directory", False
    return "", False


def run_sweep(
    sweep_root: SweepRoot,
    *,
    config: ScratchConfig,
    now: float,
    budget: WalkBudget,
    inputs: LivenessInputs,
    project_root: Path,
    project_git: ProjectGit | None,
    scandir: ScandirFn = os.scandir,
    hash_budget: HashBudget | None = None,
    plan_dir: str | None = None,
) -> SweepReport:
    """Judge every entry of a resolved sweep root; read only.

    The root comes from :func:`~claude_code_hooks_daemon.core.untracked_roots.resolve_sweep_root`,
    so a refused root (``untracked/repos``, a reference root, a ``"*"`` TTL) is
    reported and never listed, and an entry holding a never-swept path is skipped.
    ``project_git`` is the project's repository read once (None: git unavailable,
    so every due entry is STUCK: nothing can be proved about tracked files).
    ``plan_dir`` is the project's plan directory, indexed once for filing
    proposals (None: no plan folder is proposed).

    Each real session directory that is not itself a repository is judged again
    as a sub-root of its own (``SweepReport.sessions``): its children are the
    entries, one level only (Task 4.3).
    """
    return _run(
        sweep_root,
        _Context(config, now, budget, inputs, project_root, project_git, scandir, plan_dir),
        hash_budget or HashBudget(),
        None,
    )


@dataclass(frozen=True)
class _Context:
    """What every sub-root of one sweep shares."""

    config: ScratchConfig
    now: float
    budget: WalkBudget
    inputs: LivenessInputs
    project_root: Path
    project_git: ProjectGit | None
    scandir: ScandirFn
    plan_dir: str | None


def _run(
    sweep_root: SweepRoot,
    ctx: _Context,
    hashing: HashBudget,
    container: _Container | None,
) -> SweepReport:
    """One root's report; ``container`` is set when the root is a session directory."""
    config, now, budget, inputs = ctx.config, ctx.now, ctx.budget, ctx.inputs
    project_root, project_git, scandir = ctx.project_root, ctx.project_git, ctx.scandir
    root = sweep_root.path
    notes: list[str] = []
    liveness_unknown = liveness_unknown_reason(inputs)
    if sweep_root.refusal or sweep_root.ttl_hours is None:
        return SweepReport(str(root), (), False, (sweep_root.refusal,), tuple(notes))
    ttl_hours = sweep_root.ttl_hours
    notes.extend(sweep_root.notes)
    if sweep_root.apply_refusal:
        notes.append(f"not apply-eligible: {sweep_root.apply_refusal}")
    problem, absent = _root_problem(root)
    if absent:
        return SweepReport(str(root), (), True, (), (*notes, problem))
    if problem:
        return SweepReport(str(root), (), False, (problem,), tuple(notes))
    listing = list_entries(root, scandir=scandir)
    if not listing.complete:
        return SweepReport(str(root), (), False, (listing.reason,), tuple(notes))
    if container is not None and _identity(root) != container.identity:
        # Swapped between the parent's check and this listing: what was listed is not it.
        changed = f"session directory {root.name} changed while it was listed"
        return SweepReport(str(root), (), False, (changed,), tuple(notes))
    resolved_root = root.resolve()
    relative_root = _relative(resolved_root, project_root.resolve())
    tracked = _tracked_by_entry(project_git, project_root, relative_root)
    references = build_references(project_git, relative_root)
    filing = _Filing(
        build_plan_index(project_root, ctx.plan_dir),
        project_root,
        relative_root,
        config.filing.max_bytes,
    )
    if project_git is not None and project_git.verified_note:
        notes.append(f"remote proof: {project_git.verified_note}")
    judged = [
        _judge_entry(
            root,
            resolved_root,
            relative_root,
            name,
            _clock(name, ttl_hours, config.max_lifetime_hours, now, container),
            budget,
            inputs,
            scandir,
            _EntryGit(
                project_git,
                None if tracked is None else tracked.get(name, ()),
                hashing,
                references.for_entry(name),
            ),
            filing,
        )
        for name in listing.value
        if name not in sweep_root.skip and not (container and _container_file(name))
    ]
    rows, dependency_unknown, depended_on = _with_dependencies(judged)
    sessions: list[SweepReport] = []
    if container is None:
        for row in rows:
            identity = _splits(root, row)
            if identity is not None:
                held = _container_holds(
                    root,
                    row.name,
                    _Parent(resolved_root, relative_root, references, depended_on),
                    inputs,
                    dependency_unknown,
                )
                held = dataclasses.replace(held, identity=identity)
                sub_root = dataclasses.replace(sweep_root, path=root / row.name, skip=(), notes=())
                sessions.append(_run(sub_root, ctx, hashing, held))
        rows = [_held_if_session(root, row) for row in rows]
    else:
        rows = [_carried_down(row, container) for row in rows]
    if hashing.spent:
        notes.append(P3_BUDGET_NOTE)
    if rows:
        # Phase 1 records no birth for any entry, so the note holds for every row: said once.
        notes.append(NO_BIRTH_NOTE)
    stopped = sum(not row.walk_complete for row in rows)
    reasons: list[str] = []
    if stopped:
        noun = "entry" if stopped == 1 else "entries"
        reasons.append(f"{stopped} {noun} not walked to the end")
    if budget.spent_reason:
        reasons.append(budget.spent_reason)
    if liveness_unknown:
        reasons.append(liveness_unknown)
    if tracked is None:
        reasons.append("the project's tracked files under the root could not be listed")
    if references.unknown:
        reasons.append(references.unknown)
    if dependency_unknown:
        reasons.append(dependency_unknown)
    reasons.extend(
        f"session directory {Path(sub.root).name} is incomplete"
        for sub in sessions
        if not sub.complete
    )
    return SweepReport(
        str(root),
        tuple(rows),
        not reasons,
        tuple(reasons),
        tuple(notes),
        sessions=tuple(sessions),
        identity=None if container is None else container.identity,
    )


@dataclass(frozen=True)
class _Pointers:
    """Which other entries one entry's git pointers lead into, and what was unreadable."""

    #: ``(target entry name, pointing path from the scratch root)``.
    into: tuple[tuple[str, str], ...] = ()
    unknown: tuple[str, ...] = ()


_GITDIR_PREFIX = "gitdir:"
_ACTIONABLE = frozenset({Verdict.DISPOSABLE, Verdict.UNCERTAIN})
_DEPENDABLE = frozenset({Verdict.DISPOSABLE, Verdict.UNCERTAIN, Verdict.REFERENCED})


def _pointer_text(path: Path, prefix: str) -> str | None:
    """The single path a pointer file names, or None when it is not a readable pointer."""
    raw = read_small_regular_file(path)
    if raw is None:
        return None
    text = raw.decode("utf-8", errors="replace").strip()
    if prefix:
        if not text.startswith(prefix):
            return None
        text = text[len(prefix) :].strip()
    return text if text and "\n" not in text else None


def _entry_of(path: Path, root: Path) -> str | None:
    if path == root or not path_is_relative_to(path, root):
        return None
    return path_relative_to(path, root).parts[0]


def _entry_pointers(
    root: Path, resolved_root: Path, name: str, walk: Bounded[EntryStats]
) -> _Pointers:
    """Where entry ``name``'s ``.git``, ``commondir`` and ``alternates`` files point, outside itself.

    Every ``objects/info/alternates`` file in the entry is read, whatever
    repository holds it, and each line maps its lender to an entry (N1). Both the lexical and the resolved target are mapped to an entry; the pointer
    text itself is never reported, only the path of the file holding it.
    """
    if not walk.complete:
        return _Pointers((), (f"{name} was not walked to the end",))
    nodes = {node.path for node in walk.value.nodes}
    into: set[tuple[str, str]] = set()
    unknown: list[str] = []
    for marker in walk.value.git_markers:
        path = root / marker
        try:
            info = os.lstat(path)
        except OSError:
            unknown.append(marker)
            continue
        if stat.S_ISDIR(info.st_mode):
            pointer_file, prefix = f"{marker}/commondir", ""
            if pointer_file not in nodes:
                continue
            base = path
        else:
            pointer_file, prefix, base = marker, _GITDIR_PREFIX, path.parent
        pointer = _pointer_text(root / pointer_file, prefix)
        if pointer is None:
            unknown.append(pointer_file)
            continue
        into.update(_into(root, resolved_root, name, base, pointer, pointer_file))
    for node in walk.value.nodes:
        if node.path == _ALTERNATES or node.path.endswith(f"/{_ALTERNATES}"):
            lines = _alternates_lines(root / node.path)
            if lines is None:
                unknown.append(node.path)
                continue
            objects = (root / node.path).parent.parent
            for line in lines:
                into.update(_into(root, resolved_root, name, objects, line, node.path))
    return _Pointers(tuple(sorted(into)), tuple(unknown))


#: A repository's list of other object stores it borrows from (N1).
_ALTERNATES = "objects/info/alternates"


def _alternates_lines(path: Path) -> list[str] | None:
    """Every object-store path an ``alternates`` file names; None when it cannot be read whole.

    Read as a small regular file, never through a link. Blank and ``#`` lines are
    skipped as git skips them; a C-quoted line (``"..."``) is not decoded, so the
    file is unknown rather than guessed at.
    """
    raw = read_small_regular_file(path)
    if raw is None:
        return None
    lines: list[str] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith('"'):
            return None
        lines.append(text)
    return lines


def _into(
    root: Path, resolved_root: Path, name: str, base: Path, pointer: str, source: str
) -> set[tuple[str, str]]:
    """The other entries ``pointer`` (relative to ``base``) leads into, lexically or resolved."""
    lexical = Path(os.path.normpath(base / pointer))
    targets = {
        _entry_of(lexical, root),
        _entry_of(Path(os.path.realpath(lexical)), resolved_root),
    }
    return {(target, source) for target in targets if target and target != name}


def _with_dependencies(
    judged: list[tuple[EntryRow, _Pointers]],
) -> tuple[list[EntryRow], str, frozenset[str]]:
    """F-BYPS 2: protect an entry another entry's repository depends on.

    Returns the rows, the incomplete reason when some pointer could not be read,
    and every entry name some pointer leads into (whatever that entry's verdict).
    """
    dependents: dict[str, list[str]] = {}
    unknown: list[str] = []
    for _row, pointers in judged:
        unknown.extend(pointers.unknown)
        for target, source in pointers.into:
            dependents.setdefault(target, []).append(source)
    reason = ""
    if unknown:
        reason = (
            f"{len(unknown)} git pointer(s) unknown (first: {unknown[0]}), so which "
            "entries other entries depend on is unknown"
        )
    rows: list[EntryRow] = []
    for row, _pointers in judged:
        pointing = sorted(dependents.get(row.name, ()))
        if pointing and pending_verdict(row) in _DEPENDABLE:
            more = f" (and {len(pointing) - 1} more)" if len(pointing) > 1 else ""
            row = _overruled(
                row,
                Verdict.PROTECTED,
                f"another entry's repository depends on this one: {pointing[0]}{more}",
            )
        elif reason and pending_verdict(row) in _ACTIONABLE:
            # UNCERTAIN too: a repository's object store is never proved, so a
            # possible lender is UNCERTAIN, and an unread pointer may name it.
            row = _overruled(row, Verdict.STUCK, f"not judged: {reason}")
        rows.append(row)
    return rows, reason, frozenset(dependents)


@dataclass(frozen=True)
class _Parent:
    """What the root above a session directory knows about it."""

    resolved_root: Path
    relative_root: str | None
    references: ReferenceSet
    #: Names of the root's entries another entry's repository points into.
    depended_on: frozenset[str]


def _splits(root: Path, row: EntryRow) -> tuple[int, int] | None:
    """The identity of ``row`` when it is a real session directory that is not a repository.

    A repository at the session root keeps being judged whole (and held by
    :func:`_held_if_session`), so its children are never entries. None: not split.
    """
    if not is_session_dir_name(row.name) or row.kind is not NodeKind.DIRECTORY:
        return None
    identity = _identity(root / row.name)
    if isinstance(identity, _NoIdentity) or _is_repository(root / row.name):
        return None
    return identity


@dataclass(frozen=True)
class _NoIdentity:
    """Why a path has no directory identity; never equal to an ``(st_dev, st_ino)`` pair."""

    reason: str


def _identity(directory: Path) -> tuple[int, int] | _NoIdentity:
    """``(st_dev, st_ino)`` of a real directory by ``lstat``; why not, for anything else."""
    try:
        info = os.lstat(directory)
    except OSError as exc:
        return _NoIdentity(f"{directory} could not be read: {type(exc).__name__}")
    if not stat.S_ISDIR(info.st_mode):
        return _NoIdentity(f"{directory} is not a directory")
    return (info.st_dev, info.st_ino)


def _is_repository(directory: Path) -> bool:
    """A ``.git`` of any type, or the bare shape (``HEAD`` and ``objects``); ``lstat`` only."""
    return any(os.path.lexists(directory / name) for name in (".git", "HEAD", "objects"))


#: The manifest's in-flight replacement (``scratch_session._replace_file``).
_MANIFEST_TEMP_PREFIX = f".{MANIFEST_NAME}.tmp-"


def _container_file(name: str) -> bool:
    """True for a session directory's own files, which are never its entries."""
    return name in (MANIFEST_NAME, KEEP_MARKER) or name.startswith(_MANIFEST_TEMP_PREFIX)


def _container_holds(
    root: Path,
    name: str,
    parent: _Parent,
    inputs: LivenessInputs,
    dependency_unknown: str,
) -> _Container:
    """What holds every child of session directory ``name``, computed from the directory itself.

    Never read from the directory's own row: a row that is not due says only
    LIVE "within its TTL", which hides its keep marker and every protection.
    """
    holds: list[tuple[Verdict, str]] = []
    session = root / name
    if os.path.lexists(session / KEEP_MARKER):
        holds.append((Verdict.KEPT, "the session directory holds a keep marker"))
    resolved = parent.resolved_root / name
    for pid, cwd in sorted(inputs.cwds.items()):
        if Path(cwd) == resolved:
            holds.append(
                (Verdict.LIVE, f"process {pid} has its working directory at the session directory")
            )
            break
    needles = [str(resolved)]
    if parent.relative_root:
        needles.append(f"{parent.relative_root}/{name}")
    if any(needle in command for command in inputs.background.commands for needle in needles):
        holds.append((Verdict.LIVE, "a tracked background command names the session directory"))
    if parent.references.root_sites:
        holds.append((Verdict.REFERENCED, "a tracked file names the root above the session"))
    if name in parent.depended_on:
        holds.append(
            (Verdict.PROTECTED, "another entry's repository depends on the session directory")
        )
    unproved = parent.references.unknown or dependency_unknown
    manifest = read_manifest(session)
    recorded = {} if manifest is None else manifest.entries
    ttls = {key: record.ttl_hours for key, record in recorded.items() if record.ttl_hours}
    return _Container(tuple(holds), unproved, ttls)


def _carried_down(row: EntryRow, container: _Container) -> EntryRow:
    """A child's row, overruled by the first container hold when it is actionable."""
    if pending_verdict(row) not in _ACTIONABLE:
        return row
    if container.holds:
        verdict, reason = container.holds[0]
        return _overruled(row, verdict, reason)
    if container.unproved:
        return _overruled(row, Verdict.STUCK, f"not judged: {container.unproved}")
    return row


def _clock(
    name: str, ttl_hours: int, max_lifetime_hours: int, now: float, container: _Container | None
) -> _EntryClock:
    """The entry's clock: a session child's recorded TTL is used when longer, up to the backstop."""
    lifetime = max(max_lifetime_hours, ttl_hours)
    recorded = container.recorded_ttl.get(name, 0) if container else 0
    return _EntryClock(min(max(ttl_hours, recorded), lifetime), lifetime, now)


#: Why a session directory is never acted on as one entry (Task 4.3).
SESSION_HELD_REASON = (
    "session directory: a container whose children are the entries, never packed as one"
)

#: Why a session name walked as a directory, then found otherwise, is held.
SESSION_CHANGED_REASON = (
    "session directory walked as a directory but no longer a directory: held, it changed"
)


def _held_if_session(root: Path, row: EntryRow) -> EntryRow:
    """A real session directory's actionable row, made STUCK so ``--apply`` never packs it whole.

    It is still walked and judged as one entry first, so its git pointers keep
    protecting the entries they lead into. A link or a file the walk saw with
    the name is an ordinary entry. One walked as a directory that the second
    ``lstat`` cannot read, or finds no longer a directory, is held too (fail
    closed): it changed under the sweep.
    """
    if (
        not is_session_dir_name(row.name)
        or row.kind is not NodeKind.DIRECTORY
        or pending_verdict(row) not in _ACTIONABLE
    ):
        return row
    try:
        info = os.lstat(root / row.name)
    except OSError:
        return _overruled(row, Verdict.STUCK, SESSION_HELD_REASON)
    if not stat.S_ISDIR(info.st_mode):
        return _overruled(row, Verdict.STUCK, SESSION_CHANGED_REASON)
    return _overruled(row, Verdict.STUCK, SESSION_HELD_REASON)


def _overruled(row: EntryRow, verdict: Verdict, reason: str) -> EntryRow:
    """``row`` with a new verdict; its proofs and any filing proposal no longer hold.

    A row held by its TTL alone keeps showing LIVE; the overrule lands on its
    ``ttl_hold``, so pressure mode sees it.
    """
    if row.ttl_hold is not None:
        return dataclasses.replace(
            row, ttl_hold=verdict, ttl_hold_proofs=(), reasons=(*row.reasons, reason)
        )
    return dataclasses.replace(
        row,
        verdict=verdict,
        reasons=(reason, *row.reasons),
        proofs=(),
        filing_destination="",
        filing_command="",
    )


def _tracked_by_entry(
    project_git: ProjectGit | None, project_root: Path, relative_root: str | None
) -> dict[str, tuple[str, ...]] | None:
    """Tracked paths under the root by entry name; None when they could not be listed."""
    if project_git is None or relative_root is None:
        return None
    result = project_git.runner(project_root, "ls-files", "-z", "--", relative_root)
    if result.returncode != 0:
        return None
    by_entry: dict[str, list[str]] = {}
    prefix = f"{relative_root}/"
    for path in filter(None, result.stdout.split("\0")):
        if not path.startswith(prefix):
            return None
        rel = path[len(prefix) :]
        by_entry.setdefault(rel.split("/", 1)[0], []).append(rel)
    return {name: tuple(paths) for name, paths in by_entry.items()}


@dataclass(frozen=True)
class _EntryGit:
    """The project's git, and the entry's paths the project tracks (None: unknown)."""

    project: ProjectGit | None
    tracked: tuple[str, ...] | None
    hashing: HashBudget
    references: References


@dataclass(frozen=True)
class _Filing:
    """What a filing proposal needs, built once per sweep."""

    plans: PlanIndex
    project_root: Path
    relative_root: str | None
    max_bytes: int


@dataclass(frozen=True)
class _EntryClock:
    """The root's TTL, the lifetime backstop (never shorter than the TTL), and now."""

    ttl_hours: int
    max_lifetime_hours: int
    now: float


def _judge_entry(
    root: Path,
    resolved_root: Path,
    relative_root: str | None,
    name: str,
    clock: _EntryClock,
    budget: WalkBudget,
    inputs: LivenessInputs,
    scandir: ScandirFn,
    git: _EntryGit,
    filing: _Filing,
) -> tuple[EntryRow, _Pointers]:
    now = clock.now
    walk = walk_entry(root, name, now=now, budget=budget, scandir=scandir)
    stats = walk.value
    age = entry_age(
        stats, now=now, ttl_hours=clock.ttl_hours, max_lifetime_hours=clock.max_lifetime_hours
    )
    liveness = entry_liveness(
        resolved_root / name,
        relative=f"{relative_root}/{name}" if relative_root else None,
        root_ctime_ns=stats.root_ctime_ns,
        birth=None,
        inputs=inputs,
    )
    repos: RepoFindings | None = None
    needs_git = not liveness and age.due and walk.complete and not stats.multi_linked
    if needs_git and git.project is not None:
        repos = classify_entry(
            root,
            name,
            nodes=tuple(node.path for node in stats.nodes),
            markers=stats.git_markers,
            project=git.project,
        )
    judgement = judge(
        walk,
        age=age,
        liveness=liveness,
        references=git.references,
        repos=repos,
        tracked=git.tracked,
        liveness_unknown=liveness_unknown_reason(inputs),
        keep_reason=_keep_reason(root, stats),
    )
    if judgement.verdict is Verdict.UNCERTAIN:
        judgement = _with_p3(root, walk, age, repos, git, judgement)
    proposal = propose(
        name,
        kind=stats.kind,
        size=stats.bytes,
        verdict=judgement.verdict,
        protection=_protection(judgement.verdict, repos, git.tracked),
        plans=filing.plans,
        project_root=filing.project_root,
        relative_root=filing.relative_root,
        max_bytes=filing.max_bytes,
    )
    row = EntryRow(
        name=name,
        kind=stats.kind,
        verdict=judgement.verdict,
        reasons=judgement.reasons,
        proofs=judgement.proofs,
        repository=judgement.repository,
        git_markers=judgement.git_markers,
        walk_complete=walk.complete,
        directories=stats.directories,
        files=stats.files,
        bytes=stats.bytes,
        age_hours=round(age.age_seconds / _SECONDS_PER_HOUR, 1),
        due=age.due,
        uncovered=judgement.uncovered,
        uncovered_count=judgement.uncovered_count,
        filing_destination=proposal.destination if proposal else "",
        filing_command=proposal.command if proposal else "",
        ttl_hold=judgement.ttl_hold,
        ttl_hold_proofs=judgement.ttl_hold_proofs,
    )
    return row, _entry_pointers(root, resolved_root, name, walk)


#: The most of a ``.scratch-keep`` file read for its reason.
_KEEP_REASON_BYTES = 512


def _keep_reason(root: Path, stats: EntryStats) -> str:
    """The first line of the entry's keep marker, printable; "" when absent or unreadable.

    The marker's presence is decided from the walk; this only reads its reason,
    without following a link, so an unreadable marker still keeps the entry.
    """
    if not has_keep_marker(stats):
        return ""
    raw = read_small_regular_file(root / stats.name / KEEP_MARKER, _KEEP_REASON_BYTES)
    if raw is None:
        return ""
    first = raw.decode("utf-8", errors="replace").split("\n", 1)[0].strip()
    return _printable(first)


def _protection(
    verdict: Verdict, repos: RepoFindings | None, tracked: tuple[str, ...] | None
) -> Protection:
    """Why a PROTECTED entry is protected, in the order ``judge`` decides it."""
    if verdict is not Verdict.PROTECTED:
        return Protection.NONE
    if repos is not None and repos.protected:
        return Protection.REPOSITORY
    return Protection.TRACKED if tracked else Protection.NONE


def _with_p3(
    root: Path,
    walk: Bounded[EntryStats],
    age: EntryAge,
    repos: RepoFindings | None,
    git: _EntryGit,
    judgement: Judgement,
) -> Judgement:
    """Re-judge an UNCERTAIN entry once its uncovered regular files are hashed (P3).

    Nothing is hashed when the remote-held blob set is unknown, or when an
    uncovered node is not a regular file (the entry stays UNCERTAIN whatever
    the hashes say). The walk's node list bounds what is read.
    """
    blobs = git.project.remote_blobs if git.project is not None else None
    length = blob_length(blobs)
    if blobs is None or length is None:
        return judgement
    nodes = uncovered_nodes(walk.value.nodes, repos)
    if nodes is None or any(node.kind is not NodeKind.FILE for node in nodes):
        return judgement
    held: set[str] = set()
    for node in nodes:
        if not git.hashing.take(node.size):
            return judgement
        if blob_id(root / node.path, sha_length=length) in blobs:
            held.add(node.path)
    if len(held) < len(nodes):
        return judgement
    return judge(
        walk,
        age=age,
        liveness=(),
        references=git.references,
        repos=repos,
        tracked=git.tracked,
        p3=frozenset(held),
    )


def _printable(text: str) -> str:
    return "".join(char if char.isprintable() else f"\\x{ord(char):02x}" for char in text)


def _counts(report: SweepReport) -> dict[str, int]:
    counted = Counter(row.verdict for row in report.rows)
    return {verdict.value: counted[verdict] for verdict in Verdict if counted[verdict]}


def render_table(report: SweepReport, *, max_listed: int) -> list[str]:
    """The report as text, at most ``max_listed`` entry rows."""
    lines = [f"Scratch sweep of {_printable(report.root)} (dry run: nothing was changed)"]
    if not report.complete:
        lines.append("INCOMPLETE: " + "; ".join(report.incomplete_reasons))
    counts = _counts(report)
    summary = ", ".join(f"{verdict} {count}" for verdict, count in counts.items())
    lines.append(f"Entries: {len(report.rows)}" + (f" ({summary})" if summary else ""))
    if report.not_evaluated:
        lines.append("Not evaluated in this phase: " + ", ".join(report.not_evaluated))
    lines.extend(f"Note: {note}" for note in report.notes)
    for sub in report.sessions:
        lines.append("")
        lines.extend(render_table(sub, max_listed=max_listed))
    if not report.rows:
        return lines
    ordered = sorted(report.rows, key=lambda row: (_TABLE_ORDER.index(row.verdict), row.name))
    lines.append("")
    lines.append(
        f"{'ENTRY':<32} {'VERDICT':<10} {'AGE_H':>7} {'DIRS':>6} {'FILES':>7} "
        f"{'BYTES':>11} {'PROOFS':<9} REPOSITORY / REASON"
    )
    for row in ordered[:max_listed]:
        proofs = ",".join(proof.value for proof in row.proofs) or "-"
        detail = "; ".join(
            [_REPOSITORY_LABEL[row.repository], *(_printable(reason) for reason in row.reasons)]
        )
        lines.append(
            f"{_printable(row.name):<32} {row.verdict.value:<10} {row.age_hours:>7.1f} "
            f"{row.directories:>6} {row.files:>7} {row.bytes:>11} {proofs:<9} {detail}"
        )
    hidden = len(ordered) - max_listed
    if hidden > 0:
        lines.append(f"... and {hidden} more (--json lists every entry)")
    lines.extend(_render_filing(ordered, max_listed=max_listed))
    return lines


def _render_filing(ordered: list[EntryRow], *, max_listed: int) -> list[str]:
    """The "Filing proposals" section: a suggestion per row, nothing acted on."""
    proposed = [row for row in ordered if row.filing_destination]
    if not proposed:
        return []
    lines = ["", "Filing proposals (suggestions only: nothing is moved by the sweep)"]
    for row in proposed[:max_listed]:
        lines.append(f"{_printable(row.name)}: {_printable(row.filing_destination)}")
        if row.filing_command:
            lines.append(f"    {row.filing_command}")
    hidden = len(proposed) - max_listed
    if hidden > 0:
        lines.append(f"... and {hidden} more proposal(s) (--json lists every entry)")
    return lines


def _row_json(row: EntryRow) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in vars(row).items():
        if isinstance(value, enum.Enum):
            document[key] = value.value
        elif isinstance(value, tuple):
            document[key] = [item.value if isinstance(item, enum.Enum) else item for item in value]
        else:
            document[key] = value
    return document


def report_json(report: SweepReport) -> dict[str, Any]:
    """The report as a JSON-ready document, every row included."""
    return {
        "root": report.root,
        "dry_run": True,
        "complete": report.complete,
        "incomplete_reasons": list(report.incomplete_reasons),
        "notes": list(report.notes),
        "not_evaluated": list(report.not_evaluated),
        "counts": _counts(report),
        "entries": [_row_json(row) for row in report.rows],
        "sessions": [report_json(sub) for sub in report.sessions],
    }


__all__ = [
    "NO_CWDS_NOTE",
    "P3_BUDGET_NOTE",
    "P3_MAX_BYTES",
    "P3_MAX_FILES",
    "EntryRow",
    "HashBudget",
    "SweepReport",
    "pending_verdict",
    "render_table",
    "report_json",
    "run_sweep",
]
