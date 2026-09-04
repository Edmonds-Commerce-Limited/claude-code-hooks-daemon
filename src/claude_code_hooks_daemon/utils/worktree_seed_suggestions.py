"""Propose worktree seed entries by scanning a repository (Plan 00267 Phase 4).

The daemon's shipped default for ``seed.entries`` is necessarily EMPTY: no
default can know which git-ignored local files a given project happens to have.
The three-way config merge that already runs on upgrade therefore cannot help —
it reconciles a daemon default against a user value, and here the daemon has
nothing to offer. Suggestions have to be derived from the project itself.

**Git decides what is ignored.** Reimplementing ``.gitignore`` semantics would
drift from the tool that actually governs the answer, so this module asks git
and filters the result.

**Being ignored is necessary, not sufficient.** A build directory and a log
file are ignored too. A candidate must also *look like local configuration* —
the shapes below — and must not sit inside a dependency or build directory.
The heuristics are deliberately narrow: a false suggestion costs a human a
moment's attention, and over-suggesting would train them to ignore the report.

**Suggestions are reported, never written.** The project owns its config; this
module only says what it would propose, and :func:`diff_seed_config` says how
that compares with what is configured now.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.worktree_seed import DEFAULT_SEED_MODE, SeedEntry
from claude_code_hooks_daemon.utils.git_repo import run_git

logger = logging.getLogger(__name__)

# Filename shapes that read as per-developer local configuration rather than as
# build output or scratch. Matched against the BASENAME.
_LOCAL_CONFIG_PATTERNS: Final[tuple[str, ...]] = (
    ".env",
    ".env.*",
    # A dotfile is not the only shape a local env file takes: this daemon's own
    # `.claude/hooks-daemon.env` ends in `.env` without starting with it, and a
    # first pass that only matched the dotfile shapes missed it.
    "*.env",
    "*.local",
    "*.local.*",
    # A worktree missing a secret or word-list file does not fail loudly — the
    # guard that reads it goes silently inert, which is the worse outcome.
    "*.secret",
    "*.secrets",
    ".secrets",
)

# Seed's own domain extras (Plan 00288 Task 3.2, measurement doc §3): tool
# caches encountered while scanning gitignored paths, VCS internals, and this
# daemon's own scratch convention -- none of these is "vendored/build", but
# a seed candidate found inside one is always incidental.
_SEED_EXTRA_EXCLUDED_DIRECTORY_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "__pycache__",
        "untracked",
    }
)

# Directory names whose ignored contents are never local configuration —
# dependencies, build output and tool caches. Matched against any path segment.
_EXCLUDED_DIRECTORY_NAMES: Final[frozenset[str]] = (
    CORE_VENDORED_BUILD_DIR_NAMES | _SEED_EXTRA_EXCLUDED_DIRECTORY_NAMES
)

# A worktree seeds paths at or near the top of the tree; something buried deep
# in an ignored tree is far more likely to be incidental than intended.
_MAX_SUGGESTION_DEPTH: Final = 2


@dataclass(frozen=True)
class SeedConfigDrift:
    """How a project's configured seed entries compare with what it now has.

    Attributes:
        unconfigured: Candidates present in the repository that the config does
            not mention. Informational — a project may have decided against
            each one, which is why this is a report rather than a change.
        missing: Configured entries whose source no longer exists. These are
            the urgent ones: the seeding executor fails fast on exactly this,
            so each will abort the next worktree creation.
    """

    unconfigured: tuple[SeedEntry, ...] = ()
    missing: tuple[SeedEntry, ...] = ()

    @property
    def has_drift(self) -> bool:
        """True when there is anything worth a human's attention."""
        return bool(self.unconfigured or self.missing)


def _is_excluded(relative: Path, vendor_dirs: frozenset[str] | None) -> bool:
    """True when any segment names a dependency, build or cache directory.

    ``vendor_dirs`` replaces only the VENDOR half of the set (Plan 00331);
    seed's own extras -- ``.git``, the tool caches, ``untracked`` -- are a
    different category with no config axis and always apply, so a
    ``mode: replace`` vendor declaration cannot switch them off.
    """
    excluded = (
        _EXCLUDED_DIRECTORY_NAMES
        if vendor_dirs is None
        else (vendor_dirs | _SEED_EXTRA_EXCLUDED_DIRECTORY_NAMES)
    )
    return any(part in excluded for part in relative.parts)


def _looks_like_local_config(relative: Path) -> bool:
    """True when the basename matches one of the local-configuration shapes."""
    return any(fnmatch.fnmatch(relative.name, pattern) for pattern in _LOCAL_CONFIG_PATTERNS)


def _ignored_paths(root: Path) -> list[str]:
    """Ask git which paths it is ignoring, or return nothing if it cannot say."""
    result = run_git(
        root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        timeout=Timeout.GIT_CONTEXT,
    )
    if result.returncode != 0:
        logger.debug("worktree seed suggestions: %s is not a usable git repository", root)
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def suggest_seed_entries(
    root: Path, *, vendor_dirs: frozenset[str] | None = None
) -> list[SeedEntry]:
    """Return the seed entries this repository's contents suggest.

    Args:
        root: The repository root to scan.
        vendor_dirs: The project's EFFECTIVE ``layout.vendor_dirs``. ``None``
            keeps the canonical set. Supplied so a DECLARED vendor directory
            is not offered as a seed candidate (Plan 00331) — a vendored
            ansible-role tree is commonly gitignored, so without this the
            report suggests seeding third-party content into every worktree.

    Returns:
        Proposed entries in deterministic path order, each using
        :data:`~claude_code_hooks_daemon.core.worktree_seed.DEFAULT_SEED_MODE`.
        Empty when nothing qualifies, and empty (not an error) when ``root`` is
        not a git repository — a caller asking about a plain directory wants
        silence, not a failure.
    """
    candidates: set[str] = set()
    for line in _ignored_paths(root):
        relative = Path(line)
        if len(relative.parts) > _MAX_SUGGESTION_DEPTH:
            continue
        if _is_excluded(relative, vendor_dirs):
            continue
        if not _looks_like_local_config(relative):
            continue
        candidates.add(line)

    return [SeedEntry(path=path, mode=DEFAULT_SEED_MODE) for path in sorted(candidates)]


def diff_seed_config(
    root: Path, configured: list[SeedEntry], *, vendor_dirs: frozenset[str] | None = None
) -> SeedConfigDrift:
    """Compare a project's configured entries with what the repository suggests.

    A configured entry whose mode differs from the suggested default is NOT
    drift. The mode is precisely the choice this feature exists to give the
    project, so reporting a deliberate ``copy`` against a suggested ``symlink``
    would be nagging about a decision already made — and a report that nags is
    one people stop reading.

    Args:
        root: The repository root to scan.
        configured: The project's parsed seed entries.

    Returns:
        The drift, empty when the configuration is current.
    """
    configured_paths = {entry.path for entry in configured}

    unconfigured = tuple(
        entry
        for entry in suggest_seed_entries(root, vendor_dirs=vendor_dirs)
        if entry.path not in configured_paths
    )
    missing = tuple(entry for entry in configured if not (root / entry.path).exists())

    return SeedConfigDrift(unconfigured=unconfigured, missing=missing)
