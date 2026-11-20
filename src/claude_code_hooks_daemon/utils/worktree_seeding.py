"""Place a project's git-ignored local files into a fresh worktree (Plan 00267).

A fresh worktree is a clean checkout, so the git-ignored files that make the
main checkout work are absent from it. This module puts a project's configured
:class:`~claude_code_hooks_daemon.core.worktree_seed.SeedEntry` list in place,
either as a **relative symlink** back to the canonical file or as an
independent **copy**.

Validation and placement are split into two functions on purpose.
``git worktree add`` runs BETWEEN them, so a content error must surface while
there is still nothing to clean up: a half-seeded worktree is worse than an
unseeded one, because the agent working inside it cannot tell which of its
files are missing.

**Symlinks are always relative.** An absolute target dangles the moment the
same tree is viewed at a different prefix — a host at ``/home/user/project``
and a container at ``/workspace`` sharing one bind mount, a configuration this
project explicitly supports. A dangling link is strictly worse than an absent
file: most loaders raise on it rather than treating it as absent. A relative
target resolves under either prefix.

**The two modes trade off differently and neither is safe by accident.** A
symlink keeps the main checkout as the single source of truth, but a write from
INSIDE the worktree flows back through the link and mutates the canonical file.
A copy is isolated, so a worktree agent can overwrite it harmlessly, but it
drifts from the original and costs disk for a large directory. The project
chooses per entry; this module only enforces the choice.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from claude_code_hooks_daemon.core.worktree_seed import SEED_MODE_COPY, SEED_MODE_SYMLINK, SeedEntry
from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to
from claude_code_hooks_daemon.utils.path_exclusion import resolve_project_root
from claude_code_hooks_daemon.utils.private_io import make_private_dir, open_private_append

logger = logging.getLogger(__name__)

#: Returns the secret guard's effective protected globs, or raises
#: ``secret_file_matching.ProtectedSetUnreadable``.
ProtectedPatternsLoader = Callable[[], tuple[str, ...]]

_PARENT_TRAVERSAL = ".."


class WorktreeSeedError(RuntimeError):
    """A configured seed entry cannot be honoured.

    Raised by :func:`validate_seed_sources` BEFORE the worktree is created, so
    creation is abandoned rather than producing a partially-seeded worktree.
    This is the FAIL FAST half of the module's contract: a *shape* error in the
    config is warned about and skipped during parsing, but a well-formed entry
    naming a path that is absent or unsafe is a clear intention the daemon
    cannot fulfil, and proceeding would hand back a worktree quietly missing
    the files its agent needs.
    """


def _describe_problem(root: Path, entry: SeedEntry) -> str | None:
    """Return why ``entry`` cannot be seeded from ``root``, or ``None`` if it can."""
    candidate = Path(entry.path)
    if candidate.is_absolute():
        return f"{entry.path!r}: must be relative to the repository root, not absolute"
    if _PARENT_TRAVERSAL in candidate.parts:
        return f"{entry.path!r}: must not traverse upwards with {_PARENT_TRAVERSAL!r}"

    source = root / candidate
    if not source.exists():
        # An OPTIONAL entry says "seed this if it exists", which is a different
        # intention from "seed this" and the only one that tolerates absence.
        # The safety checks above are deliberately ahead of this return, so
        # optional never becomes a way to skip validation — see SeedEntry.
        if entry.optional:
            return None
        return f"{entry.path!r}: no such file or directory at the repository root"

    # The checks above bound where a link is WRITTEN. This bounds where it
    # POINTS: a path traversing a symlinked directory component inside the repo
    # has no '..' and is not absolute, yet can still resolve outside the tree.
    resolved = source.resolve()
    if not path_is_relative_to(resolved, root.resolve()):
        return f"{entry.path!r}: resolves to {resolved}, outside the repository root"

    if not source.is_file() and not source.is_dir():
        return f"{entry.path!r}: is neither a regular file nor a directory"

    return None


#: Most paths one copy-mode directory may hold before it is refused unjudged.
PROTECTED_COPY_WALK_MAX_PATHS = 10_000

#: How a refusal names a seed: by position among the VALID entries (a malformed
#: entry is dropped at parse time), never by its path, which may be protected.
_SEED_ROLE = "seed entry #{number} of the valid entries (mode: copy)"

_COPY_REFUSAL = _SEED_ROLE + ": refused by the secret_file_guard protected-set check"


def _paths_a_copy_would_read(source: Path) -> list[str] | None:
    """``source`` and every path ``shutil.copytree`` would copy from it, by name only.

    ``copytree`` follows symlinks (to files and to directories), so the walk
    does too. ``None`` when the walk cannot be completed: an unreadable
    directory, a directory reached twice (a symlink loop, on which copytree
    itself would never end), or more than :data:`PROTECTED_COPY_WALK_MAX_PATHS`.
    """
    paths = [str(source)]
    if not source.is_dir():
        return paths
    errors: list[OSError] = []
    visited: set[str] = set()
    for current, dirs, names in os.walk(source, followlinks=True, onerror=errors.append):
        real = os.path.realpath(current)
        if real in visited:
            return None
        visited.add(real)
        paths.extend(str(Path(current, name)) for name in (*dirs, *names))
        if len(paths) > PROTECTED_COPY_WALK_MAX_PATHS:
            return None
    return None if errors else paths


_UNWALKABLE = (
    "its directory could not be walked in full (unreadable, a symlink loop, or more "
    "than {cap} paths)"
)


class _Unwalkable:
    """A source whose reachable paths could not all be listed, so it cannot be judged."""


#: The verdict on a source: the first protecting glob, ``None`` (protects
#: nothing), or :data:`_UNWALKED` (could not be judged).
_UNWALKED = _Unwalkable()


def _protecting_pattern_for_source(
    root: Path, relative: str, patterns: tuple[str, ...]
) -> str | _Unwalkable | None:
    """The first glob protecting ``relative`` or any path reachable through it.

    Paths only: no file is opened. Anchored globs are tried at the seeding
    root (as given and resolved) and at the daemon's own project root.
    """
    paths = _paths_a_copy_would_read(root / relative)
    if paths is None:
        return _UNWALKED
    anchors = tuple(dict.fromkeys((str(root), str(root.resolve()), resolve_project_root())))
    for path in paths:
        for anchor in anchors:
            pattern = sfm.protecting_pattern_under(path, patterns, anchor)
            if pattern is not None:
                return pattern
    return None


def _describe_copy_refusal(
    root: Path, entry: SeedEntry, number: int, patterns: tuple[str, ...]
) -> str | None:
    """Why a copy of ``entry`` is refused for protected content, or ``None``.

    The reason names the seed by its position, never its path, because that
    path may itself be a protected name and the reason is logged.
    """
    verdict = _protecting_pattern_for_source(root, entry.path, patterns)
    refused = _COPY_REFUSAL.format(number=number)
    if isinstance(verdict, _Unwalkable):
        return (
            f"{refused}: {_UNWALKABLE.format(cap=PROTECTED_COPY_WALK_MAX_PATHS)}, so it "
            "cannot be shown to hold no protected path"
        )
    if verdict is not None:
        return (
            f"{refused}: its source is, holds or links to a path the secret guard protects. "
            "A protected file may not be seeded with mode: copy"
        )
    return None


def _copy_refusals(
    root: Path,
    numbered: list[tuple[int, SeedEntry]],
    protected_patterns: ProtectedPatternsLoader,
) -> list[str]:
    """One refusal per copy-mode entry that cannot be shown free of protected paths.

    ``numbered`` pairs each entry with its 1-based position among the parsed
    (valid) entries. The protected set is read once, and only when a
    copy-mode entry exists, so a link-only config behaves the same whatever
    state the guard config is in. An unreadable set refuses EVERY copy entry
    rather than falling back.
    """
    copies = [(number, entry) for number, entry in numbered if entry.mode == SEED_MODE_COPY]
    if not copies:
        return []
    try:
        patterns = protected_patterns()
    except sfm.ProtectedSetUnreadable as exc:
        return [
            _SEED_ROLE.format(number=number)
            + ": refused because the secret_file_guard protected set could not be read "
            f"({exc}), so no copy can be shown safe; fix the config"
            for number, _entry in copies
        ]
    return [
        refusal
        for number, entry in copies
        if (refusal := _describe_copy_refusal(root, entry, number, patterns))
    ]


def protected_copy_refusals(
    root: Path, entries: list[SeedEntry], *, protected_patterns: ProtectedPatternsLoader
) -> list[str]:
    """The copy-mode refusals :func:`validate_seed_sources` would raise, one per entry.

    Public so ``check-worktree-seed`` reports exactly what creation refuses,
    in the same words. An entry with a shape problem (absolute, ``..``, absent,
    outside the root) aborts creation anyway, so it is not walked here; entries
    keep their 1-based position among ``entries``.
    """
    judged = [
        (number, entry)
        for number, entry in enumerate(entries, start=1)
        if _describe_problem(root, entry) is None
    ]
    return _copy_refusals(root, judged, protected_patterns)


def validate_seed_sources(
    root: Path, entries: list[SeedEntry], *, protected_patterns: ProtectedPatternsLoader
) -> None:
    """Check every entry can be seeded, raising before any worktree exists.

    Args:
        root: The main checkout's repository root, where sources live.
        entries: Validated-by-shape entries from the project's config.
        protected_patterns: Returns the secret guard's effective globs, or
            raises ``ProtectedSetUnreadable``. Required, so no caller can skip
            the protected-set check; called only when a ``mode: copy`` entry
            exists (Plan 00613 ruling Q3).

    Raises:
        WorktreeSeedError: if any entry is unsafe, absent, of an unsupported
            type, or a copy that cannot be shown free of protected paths.
            EVERY offending entry is named in one message — reporting only
            the first would make fixing a misconfigured list an iterative
            guessing game.
    """
    problems = [problem for entry in entries if (problem := _describe_problem(root, entry))]
    problems.extend(protected_copy_refusals(root, entries, protected_patterns=protected_patterns))
    if problems:
        raise WorktreeSeedError(
            "Cannot seed worktree — "
            f"{len(problems)} configured entr{'y is' if len(problems) == 1 else 'ies are'} "
            "unusable:\n  " + "\n  ".join(problems)
        )


def _place(source: Path, dest: Path, mode: str) -> None:
    """Put ``source`` at ``dest`` using ``mode``; the destination must not exist."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    if mode == SEED_MODE_SYMLINK:
        # Relative to the LINK's directory, so the pair survives the whole tree
        # being viewed at a different absolute prefix.
        dest.symlink_to(os.path.relpath(source, dest.parent))
    elif source.is_dir():
        shutil.copytree(source, dest)
    else:
        shutil.copy2(source, dest)


#: The audit log of protected links, under the MAIN checkout's daemon untracked dir.
SEED_LINK_AUDIT_FILENAME = "worktree-seed-protected-links.jsonl"

_AUDIT_VERB = "worktree-seed"
_AUDIT_CHECK = "secret_file_guard"
_OUTCOME_LINKED = "linked"
_OUTCOME_UNCLASSIFIED = "linked-unclassified"

_LINK_ROLE = "seed entry #{number} of the valid entries (mode: symlink)"


def seed_link_audit_path(root: Path) -> Path:
    """The protected-link audit log of the main checkout at ``root``."""
    return get_untracked_dir(root) / SEED_LINK_AUDIT_FILENAME


@dataclass(frozen=True)
class LinkAudit:
    """How :func:`seed_worktree` records each protected source it links (Plan 00613 Task 2.2).

    Attributes:
        log_path: The JSON-lines log, normally :func:`seed_link_audit_path`.
        protected_patterns: Returns the secret guard's effective globs, or
            raises ``ProtectedSetUnreadable``; read once, and only when a link
            is about to be placed.
        session_id: The session that triggered the creation, when known.
    """

    log_path: Path
    protected_patterns: ProtectedPatternsLoader
    session_id: str | None


class _LinkAuditor:
    """Classifies each link before it is placed and appends its audit line.

    A link to a protected source, or one that cannot be classified (the
    protected set is unreadable, or a linked directory cannot be walked), gets
    one line BEFORE the link is created. Paths only: no seeded file is opened.
    """

    def __init__(self, root: Path, worktree: Path, audit: LinkAudit) -> None:
        self._root = root
        self._worktree = worktree
        self._audit = audit
        self._patterns: tuple[str, ...] | None = None
        self._unreadable: str | None = None
        self._loaded = False

    def _load(self) -> None:
        """Read the protected set once; remember why it could not be read."""
        if self._loaded:
            return
        self._loaded = True
        try:
            self._patterns = self._audit.protected_patterns()
        except sfm.ProtectedSetUnreadable as exc:
            self._unreadable = f"the secret_file_guard protected set could not be read ({exc})"
            logger.warning(
                "worktree seed: %s; every link placed into %s is audited as unclassified",
                self._unreadable,
                self._worktree,
            )

    def before_link(self, entry: SeedEntry, number: int) -> None:
        """Append the audit line for ``entry`` if it needs one.

        Raises:
            WorktreeSeedError: the line could not be written, so the caller must
                not create the link.
        """
        self._load()
        pattern: str | None = None
        reason: str | None = self._unreadable
        if self._patterns is not None:
            verdict = _protecting_pattern_for_source(self._root, entry.path, self._patterns)
            if isinstance(verdict, _Unwalkable):
                reason = _UNWALKABLE.format(cap=PROTECTED_COPY_WALK_MAX_PATHS)
            elif verdict is None:
                return
            else:
                pattern = verdict
        record = {
            "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "verb": _AUDIT_VERB,
            "outcome": _OUTCOME_UNCLASSIFIED if reason else _OUTCOME_LINKED,
            "check": _AUDIT_CHECK,
            "worktree": str(self._worktree),
            "path": entry.path,
            "pattern": pattern,
            "unclassified_reason": reason,
            "session_id": self._audit.session_id,
        }
        try:
            make_private_dir(self._audit.log_path.parent)
            with open_private_append(self._audit.log_path) as handle:
                handle.write(json.dumps(record) + "\n")
        except OSError as exc:
            raise WorktreeSeedError(
                f"Cannot seed worktree — {_LINK_ROLE.format(number=number)}: its audit line "
                f"could not be written ({type(exc).__name__}), so the link was not created"
            ) from exc


#: Bytes read per step when comparing two files, so a huge seed is never held whole.
_COMPARE_CHUNK_BYTES = 1 << 16

#: Budget for one seeded entry's comparison, which runs inside a hook. A larger
#: entry counts as differing, so it blocks rather than stalling the hook.
SEED_COMPARE_MAX_BYTES = 64 * 1024 * 1024
SEED_COMPARE_MAX_FILES = 2000


def _files_identical(source: Path, copy: Path) -> bool:
    """Whether two regular files hold the same bytes (a size mismatch ends it at once)."""
    try:
        if source.stat().st_size != copy.stat().st_size:
            return False
        with source.open("rb") as left, copy.open("rb") as right:
            while True:
                chunk = left.read(_COMPARE_CHUNK_BYTES)
                if chunk != right.read(_COMPARE_CHUNK_BYTES):
                    return False
                if not chunk:
                    return True
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"worktree seed: {copy} or {source} is unreadable, so the copy is "
            "reported as differing from its source; an unread file is never called identical",
        )
        return False


def _tree_files(root: Path, max_files: int) -> set[Path] | None:
    """Every non-directory path under ``root``, relative to it.

    ``None`` when any part is unreadable or the tree holds more than ``max_files``
    paths, in which case the walk stops early.
    """
    found: set[Path] = set()
    errors: list[OSError] = []
    for current, dirs, names in os.walk(root, onerror=errors.append):
        # os.walk reports a symlink to a directory under ``dirs`` and never enters it.
        linked_dirs = [name for name in dirs if Path(current, name).is_symlink()]
        relative_dir = Path(os.path.relpath(current, root))
        found.update(relative_dir / name for name in (*names, *linked_dirs))
        if len(found) > max_files:
            return None
    return None if errors else found


def _within_byte_budget(root: Path, relatives: Iterable[Path], max_bytes: int) -> bool:
    """Whether the files at ``relatives`` under ``root`` total at most ``max_bytes``."""
    total = 0
    for relative in relatives:
        try:
            total += (root / relative).lstat().st_size
        except OSError:
            return False
        if total > max_bytes:
            return False
    return True


def _entries_identical(source: Path, copy: Path) -> bool:
    """Whether ``copy`` is a byte-identical copy of ``source`` (symlinks compare by target)."""
    if copy.is_symlink() or source.is_symlink():
        return copy.is_symlink() and source.is_symlink() and copy.readlink() == source.readlink()
    return source.is_file() and copy.is_file() and _files_identical(source, copy)


def seed_copy_is_identical(
    source: Path,
    copy: Path,
    *,
    max_bytes: int = SEED_COMPARE_MAX_BYTES,
    max_files: int = SEED_COMPARE_MAX_FILES,
) -> bool:
    """Whether a copy-mode seeded ``copy`` still equals its ``source`` in the main checkout.

    A file is identical when both are regular files of the same bytes. A
    directory is identical only when both hold exactly the same files, each
    identical. A missing or unreadable source, a type mismatch, any
    difference and a comparison larger than the budget all answer ``False``,
    so the caller treats the copy as work that could be lost.

    Args:
        source: The path in the main checkout the entry was seeded from.
        copy: The same entry inside the worktree.
        max_bytes: Most source bytes the comparison may read in total.
        max_files: Most files the comparison may cover.

    Returns:
        True only when nothing in ``copy`` is absent from ``source``.
    """
    if not source.is_dir() or source.is_symlink() or copy.is_symlink() or not copy.is_dir():
        return _within_byte_budget(source.parent, [Path(source.name)], max_bytes) and (
            _entries_identical(source, copy)
        )
    source_files, copy_files = _tree_files(source, max_files), _tree_files(copy, max_files)
    if source_files is None or copy_files is None or source_files != copy_files:
        return False
    return _within_byte_budget(source, source_files, max_bytes) and all(
        _entries_identical(source / rel, copy / rel) for rel in source_files
    )


def seed_worktree(
    root: Path, worktree: Path, entries: list[SeedEntry], *, audit: LinkAudit
) -> list[Path]:
    """Place each entry into ``worktree``, skipping destinations already present.

    Call :func:`validate_seed_sources` first — this function assumes its
    entries are already known to be safe. "Present" is the one thing it does
    NOT assume: validation passes an absent ``optional`` entry, so placement
    has to skip the same entry rather than dying on it. Splitting that
    judgement across the two functions is how the pair would fall out of step.

    An existing destination is never overwritten. The check tests
    ``is_symlink()`` before ``exists()`` because ``exists()`` follows links and
    is therefore False for a *dangling* one: checking only existence would
    silently clobber a broken link the worktree may have been given
    deliberately.

    Args:
        root: The main checkout's repository root.
        worktree: The freshly-created worktree directory.
        entries: The entries to place, in configured order.
        audit: How each link to a protected source is recorded. Required, so
            no caller can place a protected link unaudited (Plan 00613 Task 2.2).

    Returns:
        The destinations actually created, in the order placed. A skipped
        destination is absent from this list.

    Raises:
        WorktreeSeedError: a link's audit line could not be written; that link
            is not created, and entries placed before it stay placed.
    """
    auditor = _LinkAuditor(root, worktree, audit)
    placed: list[Path] = []
    for number, entry in enumerate(entries, start=1):
        source = root / entry.path
        dest = worktree / entry.path

        if dest.is_symlink() or dest.exists():
            logger.debug(
                "worktree seed: %s already exists in the worktree; left untouched", entry.path
            )
            continue

        if entry.optional and not source.exists():
            logger.debug(
                "worktree seed: optional entry %s is absent from the main checkout; skipped",
                entry.path,
            )
            continue

        if entry.mode == SEED_MODE_SYMLINK:
            auditor.before_link(entry, number)
        _place(source, dest, entry.mode)
        placed.append(dest)

    if placed:
        logger.info(
            "worktree seed: placed %d entr%s into %s",
            len(placed),
            "y" if len(placed) == 1 else "ies",
            worktree,
        )
    return placed
