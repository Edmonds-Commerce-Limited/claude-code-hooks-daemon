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

from claude_code_hooks_daemon.plan_qa.model import PLAN_DOC_FILENAME
from claude_code_hooks_daemon.utils.git_repo import GitRepo

# git config key holding the per-repo plan high-water mark (highest number
# ever allocated). Section names are case-insensitive in git; stored lowercased.
_PLAN_COUNTER_CONFIG_KEY = "hooksdaemon.latestPlanNumber"
PLAN_NUMBER_WIDTH = 5

# A plan folder is ``NNNNN-name``. The name must start with a LETTER so that a
# date-shaped directory ("2026-01-12", digit after the hyphen) is not read as
# plan 2026, while "00032-svc-feature" and "00032-Feature" both match. Shared
# by the filesystem scan and the new-document check so the two cannot drift
# into disagreeing about what a plan folder looks like.
_PLAN_FOLDER_RE = re.compile(r"^(\d{1,5})-[a-zA-Z]")


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
    return f"{next_number:0{PLAN_NUMBER_WIDTH}d}"


def highest_plan_number(plan_folder: Path) -> int:
    """Highest existing plan number in ``plan_folder`` (0 when none / missing).

    Unlike :func:`get_next_plan_number` this does NOT raise for a missing
    folder — a repo that has never had a plan returns 0, which is exactly the
    bootstrap seed the git-anchored counter wants. Scans direct numbered plan
    folders AND recurses into non-numbered organisational subfolders
    (``Completed/``, ``archive/``, ...) so archived plans are counted.
    """
    highest_number = 0
    pattern = _PLAN_FOLDER_RE

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
        return f"{highest + 1:0{PLAN_NUMBER_WIDTH}d}"

    counter = read_plan_counter(repo_root)
    if counter is not None:
        return f"{counter + 1:0{PLAN_NUMBER_WIDTH}d}"

    # Bootstrap: no counter yet — seed it from the filesystem high-water mark.
    highest = highest_plan_number(repo_root / plan_subdir)
    write_plan_counter(repo_root, highest)
    return f"{highest + 1:0{PLAN_NUMBER_WIDTH}d}"


def record_new_plan_document(
    plan_doc_path: Path,
    plan_subdir: str,
    fallback_root: Path,
) -> int | None:
    """Advance the counter for a plan document that has just been CREATED.

    This is the DIRECT-path counter writer: an agent hand-creating
    ``{plan_subdir}/NNNNN-name/PLAN.md`` rather than going through
    ``mkplan.bash`` (the recommended path) or the flat-plan redirect in
    ``markdown_organization`` (which creates the folder itself and records its
    own allocation). Relocated here from the ``validate_plan_number`` handler
    in Plan 00237, which is being removed.

    Only a number the counter could plausibly have allocated is recorded --
    ``expected`` or ``expected - 1``, the same window ``validate_plan_number``
    accepted. The lower half of that window exists for the mkdir-then-write
    ordering: the folder may already be on disk by the time the PLAN.md write
    is seen, in which case a bootstrap scan counts it and ``expected`` has
    already moved one ahead.

    The window is not cosmetic. The commit-stage ``counter-sanity`` check
    blocks a staged plan folder whose number EXCEEDS the counter, and it only
    ever READS. Recording a typo'd ``99999`` would raise the counter to 99999,
    after which every smaller number passes that check silently -- it would go
    on reporting clean while having stopped checking.

    Args:
        plan_doc_path: The ``PLAN.md`` about to be written.
        plan_subdir: Plan folder relative to the repo root (e.g. ``CLAUDE/Plan``).
        fallback_root: Project root used when the path is not inside a git repo.

    Returns:
        The number recorded, or ``None`` when the path is not a new plan
        document or its number falls outside the window.
    """
    plan_number = _plan_number_of_new_document(plan_doc_path, plan_subdir)
    if plan_number is None:
        return None

    # No enclosing repo means no counter to persist to. Bail before the window
    # check so the return value never claims a write that did not happen --
    # ``record_plan_allocation`` would no-op here and say nothing about it.
    if resolve_plan_repo_root(plan_doc_path) is None:
        return None

    expected = int(next_plan_number_for_target(plan_doc_path, plan_subdir, fallback_root))
    if plan_number not in (expected, expected - 1):
        return None

    record_plan_allocation(plan_doc_path, plan_number)
    return plan_number


def _plan_number_of_new_document(plan_doc_path: Path, plan_subdir: str) -> int | None:
    """Plan number when ``plan_doc_path`` is a plan doc in the ACTIVE plan root.

    Structural, deliberately: the document must be ``PLAN.md``, its parent must
    be an ``NNNNN-name`` folder, and that folder's parent must end with the
    configured plan directory. The last condition excludes an ARCHIVED plan
    (``{plan_subdir}/Completed/00111-x/PLAN.md``) without needing to know any
    archive directory's configured name -- an archived plan sits one level
    deeper, so the grandparent test fails. Archiving happens by ``git mv``, not
    by writing a PLAN.md, so a write under an archive directory is an edit to
    an existing plan and never an allocation.
    """
    if plan_doc_path.name != PLAN_DOC_FILENAME:
        return None

    match = _PLAN_FOLDER_RE.match(plan_doc_path.parent.name)
    if match is None:
        return None

    expected_parts = Path(plan_subdir).parts
    if plan_doc_path.parent.parent.parts[-len(expected_parts) :] != expected_parts:
        return None

    return int(match.group(1))


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
