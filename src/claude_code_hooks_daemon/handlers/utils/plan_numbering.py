"""Plan numbering utilities for planning mode integration.

Two layers:

1. A pure filesystem scan (:func:`get_next_plan_number` /
   :func:`highest_plan_number`) that derives the next number from the
   ``NNNNN-`` plan folders on disk.

2. A git-anchored counter (:func:`next_plan_number_for_target`,
   :func:`record_plan_allocation`) that persists the latest allocated plan
   number per-repository in ``git config --local hooksdaemon.latestPlanNumber``.
   The counter is the authoritative source for the next number; the scan is
   used only to bootstrap (or self-heal) the counter. The counter lives in
   ``.git/config`` so it is stable across branch switches, and the repo is
   resolved from the *target path* so a plan created inside a nested/vendor
   repo uses that repo's own counter and plan folder. See Plan 00112.
"""

import re
from pathlib import Path

from claude_code_hooks_daemon.utils.git_repo import GitRepo

# git config key holding the per-repo plan high-water mark (highest number
# ever allocated). Section names are case-insensitive in git; stored lowercased.
_PLAN_COUNTER_CONFIG_KEY = "hooksdaemon.latestPlanNumber"
_PLAN_NUMBER_WIDTH = 5


def get_next_plan_number(plan_folder: Path) -> str:
    """Calculate next plan number by scanning plan folder.

    Scans the plan folder (and non-numbered subdirectories) for the highest
    plan number and returns the next number as a 5-digit zero-padded string.

    Plan folders follow the pattern: {number}-{name}/
    - number: 1-5 digits (e.g., 001, 00001, 123)
    - name: any text

    Subdirectories that start with digits are treated as plan folders and are
    NOT scanned recursively (they are plans, not archives).

    Subdirectories that don't start with digits (e.g., "archive/", "2025/")
    ARE scanned recursively to find archived plans.

    Args:
        plan_folder: Path to CLAUDE/Plan directory

    Returns:
        Next plan number as 5-digit zero-padded string (e.g., "00001", "00042")

    Raises:
        FileNotFoundError: If plan_folder does not exist

    Examples:
        >>> get_next_plan_number(Path("CLAUDE/Plan"))  # Empty dir
        "00001"
        >>> # Dir with: 00001-first/, 00003-third/
        >>> get_next_plan_number(Path("CLAUDE/Plan"))
        "00004"
        >>> # Dir with: 00001-current/, archive/00002-old/
        >>> get_next_plan_number(Path("CLAUDE/Plan"))
        "00003"
    """
    if not plan_folder.exists():
        raise FileNotFoundError(f"Plan directory does not exist: {plan_folder}")

    # Return next number as 5-digit zero-padded string
    next_number = highest_plan_number(plan_folder) + 1
    return f"{next_number:0{_PLAN_NUMBER_WIDTH}d}"


def highest_plan_number(plan_folder: Path) -> int:
    """Highest existing plan number in ``plan_folder`` (0 when none / missing).

    Unlike :func:`get_next_plan_number` this does NOT raise for a missing
    folder — a repo that has never had a plan returns 0, which is exactly the
    bootstrap seed the git-anchored counter wants. Scans direct numbered plan
    folders AND recurses into non-numbered organisational subfolders
    (``Completed/``, ``archive/``, ...) so archived plans are counted.
    """
    highest_number = 0
    # Require a letter after hyphen to exclude date-formatted dirs
    # like "2026-01-12" (digit after hyphen) while matching plan dirs like
    # "00032-svc-feature" or "00032-Feature" (letter after hyphen).
    pattern = re.compile(r"^(\d{1,5})-[a-zA-Z]")

    def scan_directory(directory: Path) -> None:
        nonlocal highest_number

        if not directory.is_dir():
            return

        for entry in directory.iterdir():
            # Only process directories
            if not entry.is_dir():
                continue

            # Check if directory name starts with digits
            match = pattern.match(entry.name)
            if match:
                # Found a plan directory
                number = int(match.group(1))
                highest_number = max(highest_number, number)
                # Don't scan numbered directories recursively (they are plans)
                continue

            # Non-numbered organisational directory — recurse to find archived plans.
            scan_directory(entry)

    scan_directory(plan_folder)
    return highest_number


def resolve_plan_repo_root(target_path: Path) -> Path | None:
    """Return the toplevel of the nearest git repo enclosing ``target_path``.

    Thin plan-facing wrapper over :meth:`GitRepo.resolve_for`. Returns ``None``
    when no enclosing git repo is found (caller falls back to the daemon's
    global project root).
    """
    repo = GitRepo.resolve_for(target_path)
    return repo.root if repo is not None else None


def read_plan_counter(repo_root: Path) -> int | None:
    """Read the per-repo plan high-water mark, or ``None`` when unset/invalid.

    Plan-specific typed facade over :meth:`GitRepo.read_config`: parses the
    raw config string to ``int``. ``None`` (unset or non-integer) is the
    documented 'no counter yet' signal that triggers bootstrap-from-scan.
    """
    raw = GitRepo(repo_root).read_config(_PLAN_COUNTER_CONFIG_KEY)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def write_plan_counter(repo_root: Path, value: int) -> None:
    """Write the per-repo plan high-water mark via :meth:`GitRepo.write_config`.

    FAIL FAST: propagates ``CalledProcessError`` if git rejects the write so
    the caller (a handler with its own error handling) surfaces the failure
    rather than silently losing the counter.
    """
    GitRepo(repo_root).write_config(_PLAN_COUNTER_CONFIG_KEY, str(value))


def next_plan_number_for_target(
    target_path: Path,
    plan_subdir: str,
    fallback_root: Path,
) -> str:
    """Next plan number for the repo enclosing ``target_path``.

    Trusts the git-stored counter when present (``counter + 1``). When the
    counter is absent it bootstraps from a filesystem scan of the repo's plan
    folder and seeds the counter. When ``target_path`` is not inside any git
    repo, falls back to a pure filesystem scan against ``fallback_root`` (the
    daemon's global project root) so non-git behaviour is unchanged.

    Args:
        target_path: The plan file/folder about to be created.
        plan_subdir: Plan folder relative to the repo root (e.g. ``CLAUDE/Plan``).
        fallback_root: Project root used when ``target_path`` is not in a repo.
    """
    repo_root = resolve_plan_repo_root(target_path)
    if repo_root is None:
        highest = highest_plan_number(fallback_root / plan_subdir)
        return f"{highest + 1:0{_PLAN_NUMBER_WIDTH}d}"

    counter = read_plan_counter(repo_root)
    if counter is not None:
        return f"{counter + 1:0{_PLAN_NUMBER_WIDTH}d}"

    # Bootstrap: no counter yet — seed it from the filesystem high-water mark.
    highest = highest_plan_number(repo_root / plan_subdir)
    write_plan_counter(repo_root, highest)
    return f"{highest + 1:0{_PLAN_NUMBER_WIDTH}d}"


def record_plan_allocation(target_path: Path, plan_number: int) -> None:
    """Advance the enclosing repo's plan counter to include ``plan_number``.

    Sets the counter to ``max(current, plan_number)`` — a monotonic high-water
    mark that records what was actually created and self-heals drift without
    ever lowering the next number. No-op when ``target_path`` is not in a git
    repo (nothing to persist the counter to).
    """
    repo_root = resolve_plan_repo_root(target_path)
    if repo_root is None:
        return
    current = read_plan_counter(repo_root) or 0
    if plan_number > current:
        write_plan_counter(repo_root, plan_number)
