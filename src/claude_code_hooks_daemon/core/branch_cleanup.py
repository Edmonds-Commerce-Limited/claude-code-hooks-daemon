"""Delete branches proven merged: after a merge, and from ``branch-sweep --clean``.

Plan 00558 Task 3.1 (DESIGN.md section 7). Two callers share this module so they
cannot disagree about what is safe:

- the ``cleanup_after_merge`` PostToolUse handler deletes ONLY the merged tier
  (every commit reachable from the merge target) and prints the
  ``git branch <name> <sha>`` restore line. It never
  removes a worktree: ``git worktree remove`` deletes ignored files, and that loss
  is issue #155. It advises instead.
- ``branch-sweep --clean`` deletes the merged AND patch-equivalent tiers, printing
  the same restore lines, and removes a linked worktree only when it is clean and every
  ignored file in it lies under a regenerable store
  (``branches.cleanup_after_merge.regenerable``).

Neither runs the content-preserved tier (a walk of every reachable object), so
only a merged or patch-equivalent branch can ever be deleted here.
"""

from __future__ import annotations

import logging
import os
import shlex
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import branch_inventory, branch_keep
from claude_code_hooks_daemon.core.agent_ownership import (
    RunningHolds,
    ownership_refusal,
    running_holds,
)
from claude_code_hooks_daemon.core.branch_inventory import BranchRecord, BranchState
from claude_code_hooks_daemon.core.branch_park import (
    BranchParkError,
    ParkRecord,
    clear_park_record,
    read_park_records,
)
from claude_code_hooks_daemon.core.remote_branch_proof import (
    branch_name,
    named_ref_problem,
    prove_remote_merged,
)
from claude_code_hooks_daemon.core.worktree_paths import WORKTREE_DIR_PATTERNS
from claude_code_hooks_daemon.daemon.branch_safety import (
    TIER_MERGED,
    TIER_MERGED_NOT_IN_HEAD,
    TIER_MERGED_UNPUSHED,
    TIER_PATCH_EQUIVALENT,
    BranchClassification,
    classify_branch,
    delete_branches,
    matches_any_glob,
)
from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import (
    GIT_COMMAND_ERRORS,
    HEADS_PREFIX,
    SEE_SUBMODULES,
    GitRepo,
    WorktreeRecord,
    branch_ref,
    parse_worktree_porcelain,
    run_git,
)
from claude_code_hooks_daemon.utils.load_scaling import scaled_timeout
from claude_code_hooks_daemon.utils.path_containment import (
    path_is_relative_to,
    path_relative_to,
)
from claude_code_hooks_daemon.utils.regenerable_paths import (
    clone_probe_globs,
    is_regenerable,
    lock_regenerated_dirs,
    under_any,
)
from claude_code_hooks_daemon.utils.remote_refs import remote_git_env

logger = logging.getLogger(__name__)

CleanupMode = Literal["act", "advise", "off"]

#: Tiers whose every commit is reachable from the target: deletable on the ancestry proof alone.
MERGED_TIERS = frozenset({TIER_MERGED, TIER_MERGED_UNPUSHED, TIER_MERGED_NOT_IN_HEAD})

#: Inventory states ``branch-sweep --clean`` considers, a park marker over work the
#: default holds included: ``classify_branch`` proves its local delete and
#: :func:`prove_remote_merged` its remote one (``park-carried``, Plan 00617).
#: ``content-preserved`` comes only from the ``prove_content`` inventory ``--clean``
#: builds, and is re-proved by ``classify_branch``'s content tier before any delete.
CLEAN_STATES = frozenset(
    {
        BranchState.MERGED_DEFAULT,
        BranchState.MERGED_LINE,
        BranchState.PATCH_EQUIVALENT,
        BranchState.PARK_CARRIED,
        BranchState.CONTENT_PRESERVED,
    }
)

#: States ``--clean --remote`` considers: the same states as the local half.
REMOTE_CLEAN_STATES = CLEAN_STATES

_UNTRACKED = "untracked"

#: Blocking paths listed per skipped worktree before the rest are counted.
BLOCKER_PREVIEW = 10

#: Width of the ``XY `` status prefix in ``git status --porcelain``.
_STATUS_PREFIX = 3


#: Branches (local and remote together) one ``--clean --apply`` batch deletes: one
#: ``git push --delete`` per batch, so an interruption loses at most one.
BULK_BATCH_SIZE: Final = 50


#: Inventory time budget (ms) for ``--clean``: ten minutes, in place of the hook-sized default.
BULK_SWEEP_BUDGET_MS: Final = 600_000


def sweep_clean_command(*, remote: bool = False, apply: bool = True) -> str:
    """The ``branch-sweep --clean`` invocation, spelled for this install's wrapper.

    ``remote`` adds ``--remote``: name it wherever a listed merged branch has a
    remote copy, so the one command clears that copy too. ``apply`` (the default)
    adds ``--apply``, without which ``--clean`` only previews.
    """
    flags = ("--clean", "--remote") if remote else ("--clean",)
    if apply:
        flags = (*flags, "--apply")
    return daemon_cli_command_for_docs("branch-sweep", *flags)


def sweep_clean_line(*, remote: bool) -> str:
    """The one-step fix line every merged-branch listing carries (Plan 00571 Task 2.3)."""
    return (
        f"Delete every provably merged branch in one step: "
        f"`{sweep_clean_command(remote=remote)}`"
    )


@dataclass(frozen=True)
class CleanupReport:
    """What a cleanup did, skipped and advises.

    Attributes:
        deleted: Local branches removed.
        removed_worktrees: Linked worktrees removed before their branch.
        skipped: ``"<name>: <reason>"`` for every branch left alone.
        commands: Commands to run by hand (advice, restore lines, remote deletes).
        deleted_remote: Remote branches removed, as ``<remote>/<name>``.
        remaining: Branches proven for deletion that this run did not delete
            (``<name>``, or ``<remote>/<name>`` for a remote copy).
        stopped: Why a bulk run ended early (interrupt or failed batch), else None.
        next_command: The command to run next: apply after a preview, resume after a stop.
    """

    deleted: tuple[str, ...] = ()
    removed_worktrees: tuple[Path, ...] = ()
    skipped: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    deleted_remote: tuple[str, ...] = ()
    park_cleared: tuple[str, ...] = ()
    remaining: tuple[str, ...] = ()
    stopped: str | None = None
    next_command: str | None = None


def _never_work(
    config: BranchesConfig, default: str, *, refuse_lines: bool = False
) -> tuple[str, ...]:
    """Names and globs no cleanup may delete (DESIGN.md section 1).

    An integration line is NOT among them unless ``refuse_lines``: a line is judged
    by the proof, which accepts it only once the DEFAULT branch holds every commit.
    """
    lines = config.integration_lines if refuse_lines else []
    return (*config.protected_names, *lines, *config.exempt, default)


def policy_refusal(
    name: str, config: BranchesConfig, default: str, *, refuse_lines: bool = False
) -> str | None:
    """Why policy forbids deleting ``name``, or None when it may be judged.

    ``refuse_lines`` refuses an integration line by name, for a caller that has no
    merged-into-the-default proof to offer (orphan pruning, a merge into a line).
    """
    if matches_any_glob(name, _never_work(config, default, refuse_lines=refuse_lines)):
        return "the default, protected or exempt" + (
            " (or an integration line)" if refuse_lines else ""
        )
    return None


def merge_target_qualifies(target: str | None, config: BranchesConfig, default: str) -> bool:
    """Whether a merge INTO ``target`` earns a cleanup: the default or a line."""
    if target is None:
        return False
    return target == default or matches_any_glob(target, config.integration_lines)


def _ref_exists(repo: Path, ref: str) -> bool:
    return run_git(repo, "show-ref", "--verify", "--quiet", ref).returncode == 0


def default_targets(repo: Path, config: BranchesConfig, default: str) -> list[str]:
    """The default branch refs that exist (local, then the remote's): the only proof
    an integration line's own deletion accepts."""
    targets = [default] if _ref_exists(repo, branch_ref(default)) else []
    remote_default = f"refs/remotes/{config.remote}/{default}"
    if _ref_exists(repo, remote_default):
        targets.append(remote_default)
    return targets


def cleanup_targets(repo: Path, config: BranchesConfig, default: str) -> list[str]:
    """The refs a merge into counts as safe, only those that exist.

    The default by bare name (``classify_branch`` qualifies it), the remote's
    default, and every integration-line branch local and remote. A missing ref is
    left out because the ancestry and patch proofs fail on it.
    """
    targets = default_targets(repo, config, default)
    if not config.integration_lines:
        return targets
    remote_prefix = f"refs/remotes/{config.remote}/"
    listing = run_git(repo, "for-each-ref", "--format=%(refname)", "refs/heads", remote_prefix)
    if listing.returncode != 0:
        raise RuntimeError(f"git for-each-ref failed: {listing.stderr.strip()}")
    for ref in listing.stdout.splitlines():
        name = ref.removeprefix("refs/heads/").removeprefix(remote_prefix)
        if ref not in targets and matches_any_glob(name, config.integration_lines):
            targets.append(ref)
    return targets


def validated_proof_target(
    repo: Path, config: BranchesConfig, default: str, requested: str
) -> str | None:
    """The full ref ``requested`` names, if it may prove a deletion safe, else ``None``.

    The proof target is the config's, never the caller's: a caller that may name any
    ref (its own tip, a sha, a sibling holding it) chooses its own proof. Only the
    default and the declared integration lines (local or remote) qualify.
    """
    allowed = {
        ref if ref.startswith("refs/") else branch_ref(ref)
        for ref in cleanup_targets(repo, config, default)
    }
    candidates = (
        [requested]
        if requested.startswith("refs/")
        else [branch_ref(requested), f"refs/remotes/{requested}"]
    )
    return next((ref for ref in candidates if ref in allowed), None)


def linked_worktree_records(repo: Path) -> dict[str, WorktreeRecord]:
    """Branch name to porcelain record for every LINKED worktree (never the main one)."""
    listing = run_git(repo, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        raise RuntimeError(f"git worktree list failed: {listing.stderr.strip()}")
    records = parse_worktree_porcelain(listing.stdout)[1:]
    return {r.branch: r for r in records if r.branch is not None}


def linked_worktrees(repo: Path) -> dict[str, Path]:
    """Branch name to path for every LINKED worktree (never the main one)."""
    return {name: record.path for name, record in linked_worktree_records(repo).items()}


def _agent_owned(
    name: str, records: Mapping[str, WorktreeRecord], holds: RunningHolds
) -> str | None:
    """Why ``name`` belongs to a live agent (see :mod:`agent_ownership`), or None."""
    record = records.get(name)
    return ownership_refusal(
        name,
        record.path if record is not None else None,
        locked=record.locked if record is not None else False,
        holds=holds,
    )


def _expand(root: Path, entry: str) -> list[str]:
    """Open a collapsed ``untracked/`` entry one level, so its stores can be told apart.

    ``ls-files --directory`` reports a WHOLLY ignored directory as one entry. For
    ``untracked/`` that hides the regenerable stores among the scratch notes, so
    its children are listed and judged one by one. Any other entry is as given.
    """
    if entry != f"{_UNTRACKED}/":
        return [_judged_form(root, entry)]
    children = sorted((root / _UNTRACKED).iterdir(), key=lambda child: child.name)
    return [_judged_form(root, f"{entry}{c.name}") for c in children]


def _judged_form(root: Path, entry: str) -> str:
    """``entry`` with a trailing ``/`` when it is a directory or a symlink.

    A symlink is judged as the directory it names: a removal deletes only the
    link, so a symlinked store (``untracked/lsp-venv``) matches its ``store/``
    glob whether or not its target is still there.
    """
    bare = entry.rstrip("/")
    target = root / bare
    if entry.endswith("/") or target.is_symlink() or target.is_dir():
        return f"{bare}/"
    return bare


def _is_symlink(root: Path, entry: str) -> bool:
    """Whether ``entry`` is itself a symlink (never followed).

    A removal unlinks the link and leaves its target, which lives outside the
    worktree, so a symlink is never lost content whatever it points at.
    """
    return (root / entry.rstrip("/")).is_symlink()


def _holds_nothing(root: Path, entry: str) -> bool:
    """Whether ``entry`` is a real directory with no file anywhere beneath it.

    Removing such a directory loses nothing, so it is never a blocker. A
    symlink is not walked, and anything unreadable counts as holding something.
    """
    return entry.endswith("/") and _empty_tree(root / entry.rstrip("/"))


def _only_main_links(root: Path, entry: str, main: Path | None) -> bool:
    """Whether ``entry`` is a directory holding only directories and links into the main checkout.

    A ``worktree_create`` symlink-mode seed points at the main checkout's own
    file, so unlinking it loses nothing. A link counts only when it resolves to
    an existing path inside ``main`` and outside the worktree being removed;
    a dangling link, a link elsewhere and any real file all keep the entry a blocker.
    """
    if main is None or not entry.endswith("/"):
        return False
    return _links_only_tree(root / entry.rstrip("/"), main.resolve(), root.resolve())


def _links_only_tree(path: Path, main: Path, worktree: Path) -> bool:
    """A real directory whose subtree holds only directories and main-checkout links."""
    if path.is_symlink():
        resolved = path.resolve()
        return (
            resolved.exists()
            and path_is_relative_to(resolved, main)
            and not path_is_relative_to(resolved, worktree)
        )
    if not path.is_dir():
        return False
    try:
        children = list(path.iterdir())
    except OSError:
        return False
    return all(_links_only_tree(child, main, worktree) for child in children)


def _empty_tree(path: Path) -> bool:
    """A real directory whose subtree holds only directories (an unreadable one does not)."""
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        children = list(path.iterdir())
    except OSError:
        return False
    return all(_empty_tree(child) for child in children)


def _lock_regenerated(path: Path) -> tuple[str, ...]:
    """Directories the worktree's committed manifest + lock pairs let a manager rebuild.

    Judged from the tree at HEAD, so only a pair that is actually committed counts.
    A git failure yields none: nothing is then called regenerable.
    """
    listing = run_git(path, "ls-tree", "-r", "--name-only", "-z", "HEAD")
    if listing.returncode != 0:
        return ()

    def read_committed(name: str) -> str | None:
        shown = run_git(path, "show", f"HEAD:{name}")
        return shown.stdout if shown.returncode == 0 else None

    rebuilt = lock_regenerated_dirs([p for p in listing.stdout.split("\0") if p], read_committed)
    return tuple(d for d in rebuilt if not _holds_git_clone(path / d, clone_probe_globs(d)))


def _holds_git_clone(directory: Path, extra_probes: Sequence[str] = ()) -> bool:
    """Whether ``<directory>/.git``, ``<dir>/*/.git`` or ``<dir>/*/*/.git`` exists.

    A package manager can install a dependency as a real clone (``--prefer-source``),
    and commits made inside it exist nowhere else, so such a directory is work.
    Only those paths are statted, never every file, because this runs on the
    destructive-git guard path over directories that can hold thousands of packages.
    ``extra_probes`` are the package manager's own globs (relative to ``directory``)
    for clones it leaves deeper than that, each a fixed-depth pattern.
    A directory that is not there (an uninstalled ``vendor/``) holds nothing.
    """
    if not directory.is_dir():
        return False
    if os.path.lexists(directory / ".git"):
        return True
    if any(next(directory.glob(probe), None) is not None for probe in extra_probes):
        return True
    return any(
        os.path.lexists(Path(grandchild) / ".git")
        for child in _subdirectories(directory)
        for grandchild in (child, *_subdirectories(Path(child)))
    )


def _subdirectories(directory: Path) -> list[str]:
    """Paths of the real (non-symlink) subdirectories of ``directory``; none when unreadable."""
    try:
        with os.scandir(directory) as entries:
            return [e.path for e in entries if e.is_dir(follow_symlinks=False)]
    except OSError as exc:
        log_and_continue(
            logger, exc, reason="an unreadable directory is searched no further for a clone"
        )
        return []


#: The shape of :func:`worktree_blockers`, for a caller that takes it as a seam.
WorktreeBlockersFn = Callable[[Path, Sequence[str]], tuple[str, ...]]


def worktree_blockers(path: Path, regenerable: Sequence[str]) -> tuple[str, ...]:
    """Paths a removal of the worktree at ``path`` would lose.

    Modified and untracked files (git refuses those anyway) and every ignored
    entry outside the ``regenerable`` globs. A git failure is itself a blocker:
    an unread tree is never called clean.
    """
    dirty, ignored = worktree_blocker_groups(path, regenerable)
    return (*dirty, *ignored)


def worktree_blocker_groups(
    path: Path, regenerable: Sequence[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The ``(dirty, ignored)`` split of :func:`worktree_blockers`.

    ``ignored`` are the kept ignored entries (scratch and the like), which the
    agent may delete itself; ``dirty`` also carries a git failure, which no
    delete can clear.
    """
    status = run_git(path, "status", "--porcelain", SEE_SUBMODULES)
    if status.returncode != 0:
        return ((f"<git status failed: {status.stderr.strip()}>",), ())
    dirty = [line[_STATUS_PREFIX:] for line in status.stdout.splitlines() if line]
    ignored = run_git(
        path, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"
    )
    if ignored.returncode != 0:
        return ((*dirty, f"<git ls-files failed: {ignored.stderr.strip()}>"), ())
    entries = [e for line in ignored.stdout.splitlines() if line for e in _expand(path, line)]
    main = _main_checkout(path)
    undecided = [
        entry
        for entry in entries
        if not _is_symlink(path, entry)
        and not _only_main_links(path, entry, main)
        and not is_regenerable(entry, regenerable)
        and not _holds_nothing(path, entry)
        and not _is_generated_daemon_env(path, entry)
    ]
    # Only a directory can be a package manager's output, so the committed tree
    # is read for the lock pairs only when one is still undecided.
    rebuilt = _lock_regenerated(path) if any(e.endswith("/") for e in undecided) else ()
    kept = [entry for entry in undecided if not under_any(entry, rebuilt)]
    return tuple(dirty), tuple(_judge_seeded_copies(path, kept))


def _main_checkout(path: Path) -> Path | None:
    """The main checkout of the repository ``path`` belongs to, or None if not found."""
    common = run_git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common.returncode != 0:
        return None
    git_dir = Path(common.stdout.strip())
    return git_dir.parent if git_dir.name == ".git" else None


def _source_resolves_into(source: Path, worktree: Path) -> bool:
    """Whether ``source`` reaches the worktree being removed through a symlink.

    A parent directory of the seed in the main checkout can be a link into the
    worktree; the "source" is then the copy itself and would compare identical
    to it while holding the only copy of the work.
    """
    return path_is_relative_to(source.resolve(), worktree.resolve())


def _judge_seeded_copies(path: Path, entries: Sequence[str]) -> list[str]:
    """Drop the copy-mode seeded entries that still equal their source in the main checkout.

    The seed list is the one ``worktree_create`` is configured with, read from
    the main checkout. A copy cannot be lost while its source holds the same
    bytes. One that differs, or whose source is gone, stays a blocker and is
    named as differing from its source. Every other entry passes through.
    """
    # Imported here: the install package imports core, so a module-level import cycles.
    from claude_code_hooks_daemon.core.worktree_seed import SEED_MODE_COPY
    from claude_code_hooks_daemon.install.worktree_seed_report import configured_seed_entries
    from claude_code_hooks_daemon.utils.worktree_seeding import seed_copy_is_identical

    main = _main_checkout(path)
    if main is None or not entries:
        return list(entries)
    seeds = [
        seed.path.strip("/")
        for seed in configured_seed_entries(main)
        if seed.mode == SEED_MODE_COPY
    ]
    judged: list[str] = []
    for entry in entries:
        relative = entry.rstrip("/")
        covered = any(relative == seed or relative.startswith(f"{seed}/") for seed in seeds)
        if not covered:
            judged.append(entry)
        elif _source_resolves_into(main / relative, path) or not seed_copy_is_identical(
            main / relative, path / relative
        ):
            judged.append(f"{entry} (differs from its source in the main checkout)")
    return judged


#: The daemon env file every worktree gets from `scripts/setup_worktree.sh`.
_DAEMON_ENV_ENTRY: Final = ".claude/hooks-daemon.env"

#: The one assignment the installer's template writes; checkout-agnostic, so a
#: worktree's copy is regenerated identically by the next setup.
_GENERATED_DAEMON_ENV_LINE: Final = 'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"'


def _is_generated_daemon_env(path: Path, entry: str) -> bool:
    """True when ``entry`` is the daemon env file exactly as the installer writes it.

    Comments, blank lines and the single checkout-agnostic assignment, nothing
    else. Any other line is a hand edit the removal would lose, so it blocks;
    an unreadable file blocks too, and so does one the project protects (its
    bytes are never read, so it cannot be judged regenerable).
    """
    if entry != _DAEMON_ENV_ENTRY:
        return False
    if sfm.path_is_protected(str(path / entry), sfm.resolve_configured_patterns()):
        return False
    try:
        text = (path / entry).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"branch_cleanup: {entry} in {path} is unreadable, so it is kept as a "
            "blocker; an unread file is never called regenerable",
        )
        return False
    lines = [line.strip() for line in text.splitlines()]
    settings = [line for line in lines if line and not line.startswith("#")]
    return settings == [_GENERATED_DAEMON_ENV_LINE]


def preview_paths(paths: Sequence[str]) -> str:
    """The first ``BLOCKER_PREVIEW`` of ``paths``, then how many more there are."""
    shown = ", ".join(paths[:BLOCKER_PREVIEW])
    rest = len(paths) - BLOCKER_PREVIEW
    return f"{shown} and {rest} more" if rest > 0 else shown


def remote_delete_advice(
    repo: Path, config: BranchesConfig, default: str, name: str, *, prove: bool = True
) -> str | None:
    """What to tell a person about the remote copy of ``name``, when the remote holds one.

    The runnable line is the leased route (``delete-branch --remote-only``, which holds
    a lease on the proven tip and prints the restore line), and only when the
    remote-delete guard's own proof (:func:`prove_remote_merged`) accepts the branch.
    Otherwise owner-only wording, which is advice and not a command.

    ``prove=False`` is for a hook path, where the proof's ``ls-remote`` and history
    walks are too slow and need the network: the line is then owner-only wording that
    points at the sweep, which does prove and delete. The guard is not involved.
    """
    remote = config.remote
    if not _ref_exists(repo, f"refs/remotes/{remote}/{name}"):
        return None
    problem = named_ref_problem(remote, name, default, config)
    if problem is None and not prove:
        problem = f"run `{sweep_clean_command(remote=True)}` to prove and delete it"
    elif problem is None:
        proof = prove_remote_merged(repo, remote, [name], default, config)
        problem = proof.problems.get(name)
        if problem is None and name in proof.tips:
            return daemon_cli_command_for_docs("delete-branch", "--remote-only", shlex.quote(name))
        problem = problem or "the proof did not accept it"
    return f"remote delete of {remote}/{name} is for the owner: {problem}"


def _classify(
    repo: Path,
    name: str,
    targets: Sequence[str],
    never_work: Sequence[str],
    *,
    lines: Sequence[str] = (),
    line_targets: Sequence[str] | None = None,
    ignore_worktree: bool = False,
    content_tier: bool = False,
) -> BranchClassification:
    """``classify_branch`` for cleanup; ``content_tier`` is True only from ``--clean``."""
    return classify_branch(
        repo,
        name,
        protected_names=never_work,
        targets=targets,
        ignore_worktree=ignore_worktree,
        content_tier=content_tier,
        line_names=lines,
        line_targets=line_targets,
    )


def _park_snapshot(repo: Path, names: Sequence[str]) -> dict[str, ParkRecord]:
    """The park records of ``names`` as they stand now.

    Taken BEFORE a delete: deleting a branch takes its ``branch.<name>.*`` config
    with it, so the record can no longer be read afterwards to say what was cleared.
    """
    records = read_park_records(repo)
    return {name: records[name] for name in names if name in records}


def _clear_parks(
    repo: Path, names: Sequence[str], before: Mapping[str, ParkRecord] | None = None
) -> tuple[str, ...]:
    """Clear the park record of each merged branch; ``"<name>: <reason>"`` for each cleared.

    A merge ends a park, so the record goes with it and the report says so.
    ``before`` names a record read before a delete took the branch's config with it.
    """
    cleared: list[str] = []
    for name in names:
        record = clear_park_record(repo, name) or (before or {}).get(name)
        if record is not None:
            cleared.append(f"{name}: {record.reason}")
    return tuple(cleared)


_SCRATCH_ROOT: Final = Path("untracked") / "scratch"


def holds_scratch(worktree: Path) -> bool:
    """True when ``<worktree>/untracked/scratch`` is a real directory with a child.

    One ``lstat`` and one ``scandir`` stopped at its first entry: no walk, no
    classification, no git. A link or a non-directory is not a scratch root.
    Any other failure to read it answers True, so the caller points at the
    human route rather than at a removal that could lose notes.
    """
    scratch = worktree / _SCRATCH_ROOT
    try:
        mode = os.lstat(scratch).st_mode
    except FileNotFoundError:
        return False
    except OSError as exc:
        log_and_continue(logger, exc, reason="an unreadable scratch root is treated as held")
        return True
    if not stat.S_ISDIR(mode):
        return False
    try:
        with os.scandir(scratch) as entries:
            return next(iter(entries), None) is not None
    except OSError as exc:
        log_and_continue(logger, exc, reason="an unreadable scratch root is treated as held")
        return True


def _reap_name(repo: Path, worktree: Path) -> str | None:
    """The ``worktree-reap --only`` name for ``worktree``, or None when it cannot name it.

    ``--only`` matches the directory name of a worktree directly under one of
    the sanctioned roots of the MAIN checkout, so anything else gets no command.
    """
    main = GitRepo(repo).main_worktree_root()
    if not path_is_relative_to(worktree, main):
        return None
    relative = path_relative_to(worktree, main).as_posix()
    if any(relative == f"{pattern}{worktree.name}" for pattern in WORKTREE_DIR_PATTERNS):
        return worktree.name
    return None


def _held_worktree_advice(repo: Path, name: str, held_by: Path) -> tuple[str, list[str]]:
    """The skip line and commands for a merged branch checked out in ``held_by``.

    With scratch in the worktree the bare ``git worktree remove`` is not
    printed: it would lose the notes and the guard denies it. Evacuation lives
    only in ``worktree-reap --reap``, behind a typed phrase at a terminal.
    """
    where = f"{name}: checked out in the worktree {held_by}"
    if not holds_scratch(held_by):
        return where, [f"git worktree remove {shlex.quote(str(held_by))}"]
    reap_name = _reap_name(repo, held_by)
    if reap_name is None:
        return (
            f"{where}, which holds scratch (untracked/scratch/) a removal would lose; "
            "a human files or deletes it by hand, then removes the worktree",
            [],
        )
    return (
        f"{where}, which holds scratch (untracked/scratch/) a removal would lose; "
        "a human at a terminal archives it and removes the worktree with the "
        "worktree-reap command below (it names any entry to file by hand first)",
        [daemon_cli_command_for_docs("worktree-reap", "--reap", "--only", shlex.quote(reap_name))],
    )


def cleanup_after_merge(
    repo: Path,
    names: Sequence[str],
    *,
    config: BranchesConfig,
    target: str,
    mode: CleanupMode,
    default: str | None = None,
) -> CleanupReport:
    """Delete (``act``) or advise deleting the branches just merged into ``target``.

    Only the merged tiers are deleted: the restore line is printed. A worktree holding the branch, and a patch-equivalent branch, are
    only ever advised.

    ``default`` is the resolved default branch. It is never deleted, even when
    ``target`` is an integration line; it falls back to ``target`` when not given.
    """
    if mode == "off":
        return CleanupReport()
    # A merge into an integration line proves nothing about another line: lines are
    # refused by name unless the target is the default branch itself.
    refuse_lines = matches_any_glob(target, config.integration_lines)
    protected_default = default or target
    never_work = (*_never_work(config, protected_default, refuse_lines=refuse_lines), target)
    targets = [target]
    lines: Sequence[str] = () if refuse_lines else config.integration_lines
    worktrees = linked_worktrees(repo)
    deleted: list[str] = []
    skipped: list[str] = []
    commands: list[str] = []
    park_cleared: list[str] = []

    def delete_command(name: str) -> str:
        return daemon_cli_command_for_docs(
            "delete-branch", shlex.quote(name), "--protected-ref", shlex.quote(target)
        )

    for name in names:
        refusal = policy_refusal(name, config, protected_default, refuse_lines=refuse_lines)
        if refusal is not None:
            skipped.append(f"{name}: {refusal}")
            continue
        held_by = worktrees.get(name)
        verdict = _classify(
            repo,
            name,
            targets,
            never_work,
            lines=lines,
            line_targets=targets,
            ignore_worktree=held_by is not None,
        )
        if verdict.refusal is not None:
            skipped.append(f"{name}: {verdict.detail}")
            continue
        if verdict.tier == TIER_PATCH_EQUIVALENT:
            skipped.append(f"{name}: patch-equivalent, not reachable from {target}")
            commands.append(sweep_clean_command())
            continue
        if verdict.tier not in MERGED_TIERS:
            skipped.append(f"{name}: {verdict.detail}")
            continue
        if held_by is not None:
            park_cleared += _clear_parks(repo, [name])
            line, removal = _held_worktree_advice(repo, name, held_by)
            skipped.append(line)
            commands += [*removal, delete_command(name)]
        elif mode == "advise":
            park_cleared += _clear_parks(repo, [name])
            commands.append(delete_command(name))
        else:
            before = _park_snapshot(repo, [name])
            report = delete_branches(
                repo,
                [name],
                protected_names=never_work,
                targets=targets,
                content_tier=False,
                line_names=lines,
                line_targets=targets,
            )
            if name not in report.deleted:
                skipped += [f"{name}: {blocker}" for blocker in report.blockers]
                continue
            park_cleared += _clear_parks(repo, [name], before)
            deleted.append(name)
            commands.append(f"git branch {shlex.quote(name)} {verdict.tip}")
        remote = remote_delete_advice(repo, config, protected_default, name, prove=False)
        if remote is not None:
            commands.append(remote)
    return CleanupReport(
        deleted=tuple(deleted),
        skipped=tuple(skipped),
        commands=tuple(dict.fromkeys(commands)),
        park_cleared=tuple(park_cleared),
    )


def _merged_into_any(repo: Path, name: str, targets: Sequence[str], timeout: float) -> bool:
    """Cheap ancestry probe, so an unmerged branch never pays for ``git cherry``."""
    return any(
        run_git(
            repo, "merge-base", "--is-ancestor", branch_ref(name), target, timeout=timeout
        ).returncode
        == 0
        for target in targets
    )


def delete_if_merged(
    repo: Path,
    name: str,
    *,
    config: BranchesConfig,
    default: str,
    probe_timeout: float = Timeout.GIT_CONTEXT,
) -> CleanupReport:
    """Delete ``name`` when the default or an integration line holds every commit.

    For an integration-line ``name`` only the default counts: a line merged into
    another line is left alone.

    The WorktreeRemove cleanup (DESIGN.md section 8). Only the merged tiers are
    deleted (the restore line is printed); anything else
    is left for ``branch-sweep --clean``.

    Raises:
        RuntimeError: The integration-line refs could not be listed.
    """
    refusal = policy_refusal(name, config, default)
    if refusal is not None:
        return CleanupReport(skipped=(f"{name}: {refusal}",))
    is_line = matches_any_glob(name, config.integration_lines)
    line_targets = default_targets(repo, config, default)
    targets = line_targets if is_line else cleanup_targets(repo, config, default)
    if not targets or not _merged_into_any(repo, name, targets, probe_timeout):
        if is_line:
            return CleanupReport(
                skipped=(f"{name}: an integration line not yet merged into {default}",)
            )
        return CleanupReport(skipped=(f"{name}: not merged; left for {sweep_clean_command()}",))
    never_work = _never_work(config, default)
    verdict = _classify(
        repo, name, targets, never_work, lines=config.integration_lines, line_targets=line_targets
    )
    if verdict.refusal is not None or verdict.tier not in MERGED_TIERS:
        return CleanupReport(skipped=(f"{name}: {verdict.detail}",))
    before = _park_snapshot(repo, [name])
    report = delete_branches(
        repo,
        [name],
        protected_names=never_work,
        targets=targets,
        content_tier=False,
        line_names=config.integration_lines,
        line_targets=line_targets,
    )
    if name not in report.deleted:
        return CleanupReport(skipped=tuple(f"{name}: {b}" for b in report.blockers))
    park_cleared = _clear_parks(repo, [name], before)
    commands = [f"git branch {shlex.quote(name)} {verdict.tip}"]
    remote = remote_delete_advice(repo, config, default, name, prove=False)
    if remote is not None:
        commands.append(remote)
    return CleanupReport(deleted=(name,), commands=tuple(commands), park_cleared=park_cleared)


def _proof_words(tier: str | None, default: str) -> str:
    """How a dry-run line states its proof: a plain merge, or the named evidence tier."""
    if tier is None or tier == TIER_MERGED:
        return f"proven merged into {default}"
    return f"proven {tier} against {default}"


def blockers_line(held_by: Path, blockers: Sequence[str]) -> str:
    """Why a worktree is not removed: the paths a removal would lose."""
    return (
        f"the worktree {held_by} holds {len(blockers)} path(s) a removal "
        f"would lose: {preview_paths(blockers)}"
    )


def _remove_worktree(repo: Path, path: Path) -> str | None:
    """Remove a linked worktree without ``--force``; git's refusal verbatim, or None."""
    result = run_git(
        repo,
        "worktree",
        "remove",
        str(path),
        timeout=scaled_timeout(Timeout.GIT_WORKTREE_REMOVE, Timeout.GIT_WORKTREE_REMOVE_MAX),
    )
    if result.returncode == 0:
        return None
    return result.stderr.strip() or f"git worktree remove exited {result.returncode}"


def _lift_stale_marks_of_kept_branches(repo: Path, records: Mapping[str, BranchRecord]) -> None:
    """Make the creation guard's labels snapshot agree with the keeps this sweep honours.

    ``branch-preflight`` and the creation guard read a snapshot SessionStart wrote,
    and only a local ``branch-keep`` cleared its stale mark. A keep written in
    another clone and fetched by this sweep was honoured here yet left the mark,
    so the guard kept refusing on a branch the sweep reported kept (Plan 00641).
    The snapshot is a derived cache, so correcting it is not a change a dry run
    promises to withhold.
    """
    # Function-local: branch_creation imports this module at load time.
    from claude_code_hooks_daemon.core.branch_creation import (
        LABELS_RELATIVE_PATH,
        clear_label_stale,
    )

    # By name, never by tip: a keep is a note on one tip, and a local and a remote
    # copy of a branch can sit at different tips, so clearing every label at either
    # tip would also lift the mark of an unkept branch that merely shares one.
    for name, record in records.items():
        if record.kept_reason is not None and not record.stale:
            clear_label_stale(repo / LABELS_RELATIVE_PATH, name)


def clean_sweep(
    repo: Path,
    config: BranchesConfig,
    *,
    dry_run: bool,
    remote: bool = False,
    untracked: Path | None = None,
) -> CleanupReport:
    """Delete every merged and patch-equivalent local branch.

    With ``remote`` (``--clean --remote``) every merged branch the remote holds is
    deleted there too, by the remote-delete guard's proof. That path contacts the remote (``ls-remote``, ``push``).

    Each candidate is classified on its own first, because ``delete_branches`` is
    all-or-nothing: only the proven ones are batched. A linked worktree is removed
    first, and only when :func:`worktree_blockers` finds nothing it would lose and a
    fresh worktree listing at apply time shows it still holds the planned branch.

    A parked branch that is only content-preserved (never merged) is skipped on
    both sides with its park reason; a merged tier ends a park instead.

    A branch and worktree a live agent owns (:mod:`agent_ownership`: a ``running``
    work-queue record in ``untracked``, the harness's ``.claude/worktrees/``
    directory, a git lock) is skipped with its reason, locally and on the remote.

    A merged branch kept inside ``branches.merged.max_age_days`` (``branch-keep``)
    and any ``branches.bot_owned`` name are skipped, and the keep is reported; a
    lapsed keep is cleaned. With ``remote`` the keep notes are fetched first, so a
    keep written in another clone counts; if that fetch fails the remote half is
    refused (a keep cannot be ruled out) and only the local half runs.

    Raises:
        branch_inventory.BranchInventoryError: The refs could not be listed.
        ValueError: No default branch can be resolved.
    """
    keep_fetch_error = branch_keep.fetch_keeps(repo, config.remote) if remote else None
    # The hook-sized sweep budget would skip reading keep notes on a large repository
    # and leave a kept branch looking deletable; a bulk clean is not a hook.
    unhurried = config.model_copy(
        update={"sweep": config.sweep.model_copy(update={"budget_ms": BULK_SWEEP_BUDGET_MS})}
    )
    inventory = branch_inventory.build_inventory(repo, unhurried, prove_content=True)
    _lift_stale_marks_of_kept_branches(repo, inventory.records)
    default = inventory.default_branch
    if default is None:
        raise ValueError("cannot determine the default branch; set branches.default")
    targets = cleanup_targets(repo, config, default)
    # Defence in depth: the inventory gives an integration line a state outside
    # CLEAN_STATES, so no line is a candidate; the line arguments below keep the
    # default-only proof in force should that filter ever change.
    line_targets = default_targets(repo, config, default)
    never_work = _never_work(config, default)
    worktree_records = linked_worktree_records(repo)
    worktrees = {name: record.path for name, record in worktree_records.items()}
    holds = running_holds(untracked if untracked is not None else get_untracked_dir(repo), repo)
    owned = {
        name: why
        for name in {*inventory.records, *worktree_records}
        if (why := _agent_owned(name, worktree_records, holds)) is not None
    }
    spared = _spared(config, inventory.records, repo)
    candidates = sorted(
        name
        for name, record in inventory.records.items()
        if record.state in CLEAN_STATES
        and record.local_tip is not None
        and policy_refusal(name, config, default) is None
    )
    proven: list[str] = []
    skipped: list[str] = []
    commands: list[str] = []
    for name in candidates:
        if name in spared:
            skipped.append(f"{name}: {spared[name]}")
            continue
        if name in owned:
            skipped.append(f"{name}: {owned[name]}")
            continue
        held_by = worktrees.get(name)
        if held_by is not None:
            blockers = worktree_blockers(held_by, config.cleanup_after_merge.regenerable)
            if blockers:
                skipped.append(f"{name}: {blockers_line(held_by, blockers)}")
                continue
        verdict = _classify(
            repo,
            name,
            targets,
            never_work,
            lines=config.integration_lines,
            line_targets=line_targets,
            ignore_worktree=held_by is not None,
            content_tier=True,
        )
        if not verdict.is_safe:
            skipped.append(f"{name}: {verdict.detail}")
            continue
        if dry_run:
            if held_by is not None:
                commands.append(f"would remove the worktree {held_by}")
            commands.append(f"would delete {name} (proven {verdict.tier})")
        proven.append(name)

    remote_tips: dict[str, str] = {}
    remote_evidence: dict[str, str] = {}
    if remote and keep_fetch_error is not None:
        skipped.append(
            f"{config.remote}: keep notes could not be fetched ({keep_fetch_error}), "
            "so the remote half was refused"
        )
    elif remote:
        remote_tips, problems, remote_evidence = _proven_remote(
            repo, config, default, inventory.records, spared=frozenset({*owned, *spared})
        )
        skipped += [f"{config.remote}/{name}: {why}" for name, why in problems.items()]
        skipped += [
            f"{config.remote}/{name}: {spared[name]}"
            for name in sorted(spared)
            if inventory.records[name].remote_tip is not None
            and inventory.records[name].cleanup_state in REMOTE_CLEAN_STATES
        ]
    apply_command = sweep_clean_command(remote=remote)
    if dry_run:
        commands += [
            f"would delete remote {config.remote}/{name} (tip {tip[:_TIP_PREVIEW]}, "
            f"{_proof_words(remote_evidence.get(name), default)})"
            for name, tip in remote_tips.items()
        ]
        for name in proven:
            advice = remote_delete_advice(repo, config, default, name)
            if advice is not None and name not in remote_tips:
                commands.append(advice)
        return CleanupReport(
            skipped=tuple(skipped),
            commands=tuple(commands),
            next_command=apply_command if proven or remote_tips else None,
        )

    plan = _BulkPlan(
        repo=repo,
        config=config,
        default=default,
        targets=targets,
        line_targets=line_targets,
        never_work=never_work,
        proven=frozenset(proven),
        remote_tips=remote_tips,
        worktrees=worktrees,
    )
    return _apply_in_batches(plan, sorted({*proven, *remote_tips}), skipped, apply_command)


#: Leading hex digits of a tip shown in the preview.
_TIP_PREVIEW: Final = 12


@dataclass(frozen=True)
class _BulkPlan:
    """What ``clean_sweep --apply`` decided before it deleted anything."""

    repo: Path
    config: BranchesConfig
    default: str
    targets: Sequence[str]
    line_targets: Sequence[str]
    never_work: Sequence[str]
    proven: frozenset[str]
    remote_tips: Mapping[str, str]
    worktrees: Mapping[str, Path]


@dataclass
class _Outcome:
    """What the batches did so far; every field only grows."""

    deleted: list[str] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    deleted_remote: list[str] = field(default_factory=list)
    park_cleared: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)


def _apply_in_batches(
    plan: _BulkPlan, units: Sequence[str], skipped: list[str], apply_command: str
) -> CleanupReport:
    """Delete ``units`` ``BULK_BATCH_SIZE`` at a time, stopping cleanly on an interrupt.

    The only state is the repository: a deleted branch is no longer a candidate, so
    running the same command again continues where this one stopped. A SIGINT or a failed batch ends the loop;
    the units not yet handled are reported with the command that resumes.
    """
    outcome = _Outcome(skipped=skipped)
    batches = [list(units[i : i + BULK_BATCH_SIZE]) for i in range(0, len(units), BULK_BATCH_SIZE)]
    stopped: str | None = None
    for index, batch in enumerate(batches):
        try:
            _run_batch(plan, batch, outcome)
        except KeyboardInterrupt:
            logger.warning("branch cleanup interrupted during batch %d", index + 1)
            stopped = f"interrupted during batch {index + 1} of {len(batches)}"
        except GIT_COMMAND_ERRORS as exc:
            logger.warning("branch cleanup batch %d of %d failed: %s", index + 1, len(batches), exc)
            stopped = f"batch {index + 1} of {len(batches)} failed: {exc}"
        if stopped is not None:
            pending = [name for rest in batches[index:] for name in rest]
            outcome.remaining += [
                name
                for name in pending
                if name in plan.remote_tips or _ref_exists(plan.repo, branch_ref(name))
            ]
            break
    needs_resume = bool(outcome.remaining)
    return CleanupReport(
        deleted=tuple(outcome.deleted),
        removed_worktrees=tuple(outcome.removed),
        skipped=tuple(outcome.skipped),
        commands=tuple(outcome.commands),
        deleted_remote=tuple(outcome.deleted_remote),
        park_cleared=tuple(outcome.park_cleared),
        remaining=tuple(dict.fromkeys(outcome.remaining)),
        stopped=stopped,
        next_command=apply_command if needs_resume else None,
    )


def _run_batch(plan: _BulkPlan, batch: Sequence[str], outcome: _Outcome) -> None:
    """One batch: worktrees, local deletes, then one push for the remote copies.

    An already-deleted local branch is skipped, never an error. A batch whose delete
    is refused, or whose remote push is refused, adds what is left to ``remaining``
    so the report can name it; a later run retries exactly those.
    """
    repo, config = plan.repo, plan.config
    local: list[str] = []
    # The plan's worktree map is as old as its proofs: re-read it once per batch, so
    # a worktree switched to another branch (or claimed afresh) is never removed.
    now_held: Mapping[str, Path] | None = {}
    if any(name in plan.worktrees for name in batch):
        try:
            now_held = {name: rec.path for name, rec in linked_worktree_records(repo).items()}
        except RuntimeError as exc:
            # Fail closed: an unread listing cannot show the worktree still holds it.
            log_and_continue(
                logger,
                exc,
                reason="branch cleanup: worktree list unreadable at apply, so every "
                "worktree-held branch in this batch is kept (fail closed)",
            )
            now_held = None
    for name in batch:
        if name not in plan.proven:
            continue
        if not _ref_exists(repo, branch_ref(name)):
            outcome.skipped.append(f"{name}: already deleted")
            continue
        held_by = plan.worktrees.get(name)
        if held_by is not None:
            if now_held is None:
                outcome.skipped.append(
                    f"{name}: the worktree list could not be re-read, so {held_by} was kept"
                )
                continue
            if now_held.get(name) != held_by:
                outcome.skipped.append(_worktree_changed_line(name, held_by, now_held))
                continue
            # The proof ran long ago; work may have landed in the worktree since.
            blockers = worktree_blockers(held_by, config.cleanup_after_merge.regenerable)
            if blockers:
                outcome.skipped.append(f"{name}: {blockers_line(held_by, blockers)}")
                continue
            refused = _remove_worktree(repo, held_by)
            if refused is not None:
                outcome.skipped.append(f"{name}: git refused to remove {held_by}: {refused}")
                continue
            outcome.removed.append(held_by)
        local.append(name)
    tips = {name: plan.remote_tips[name] for name in batch if name in plan.remote_tips}
    deleted: tuple[str, ...] = ()
    if local:
        before = _park_snapshot(repo, local)
        # The content tier, as in the plan: a content-preserved branch is re-proved
        # here, so the delete never rests on the inventory's (or a cache's) word.
        report = delete_branches(
            repo,
            local,
            protected_names=plan.never_work,
            targets=plan.targets,
            content_tier=True,
            line_names=config.integration_lines,
            line_targets=plan.line_targets,
        )
        deleted = report.deleted
        outcome.park_cleared += _clear_parks(repo, deleted, before)
        outcome.skipped += report.blockers
        outcome.commands += report.restore_commands
    outcome.deleted += deleted
    outcome.remaining += [name for name in local if name not in deleted]
    if tips:
        gone, push_refusals = _push_deletes(repo, config.remote, tips)
        outcome.skipped += push_refusals
        outcome.deleted_remote += [f"{config.remote}/{name}" for name in gone]
        outcome.remaining += [name for name in tips if name not in gone]
        outcome.commands += [
            f"git push {shlex.quote(config.remote)} {shlex.quote(f'{tips[name]}:{branch_ref(name)}')}"
            for name in gone
        ]
    for name in deleted:
        advice = remote_delete_advice(repo, config, plan.default, name)
        if advice is not None and name not in tips:
            outcome.commands.append(advice)


def _worktree_changed_line(name: str, planned: Path, now_held: Mapping[str, Path]) -> str:
    """Why a planned worktree removal was dropped: the worktree no longer holds ``name``."""
    holder = next((branch for branch, path in now_held.items() if path == planned), None)
    now = f"now holds {holder}" if holder is not None else "no longer holds it"
    return f"{name}: the worktree {planned} {now} (changed since the plan); rerun the sweep"


def _spared(
    config: BranchesConfig, records: Mapping[str, BranchRecord], repo: Path
) -> dict[str, str]:
    """``name -> reason`` for every branch ``--clean`` must leave alone on both sides.

    A keep inside its age, any ``bot_owned`` name (defence in depth: the inventory
    already gives those a state outside CLEAN_STATES), and a parked content-preserved
    branch: it was never merged, so its park is a standing decision the sweep must
    not erase. A merged tier still ends a park, as a merge does.
    """
    parks: Mapping[str, ParkRecord] | None
    try:
        parks = read_park_records(repo)
    except BranchParkError as exc:
        log_and_continue(
            logger,
            exc,
            reason="branch cleanup: park records unreadable, so every content-preserved "
            "branch counts as parked and is spared (fail closed)",
        )
        parks = None
    spared: dict[str, str] = {}
    for name, record in records.items():
        if matches_any_glob(name, config.bot_owned):
            spared[name] = "bot-owned (branches.bot_owned)"
        elif record.kept_reason is not None and not record.stale:
            spared[name] = f"kept: {record.kept_reason}"
        elif record.cleanup_state == BranchState.CONTENT_PRESERVED:
            why = _park_reason(name, record, parks)
            if why is not None:
                spared[name] = (
                    f"parked ({why}), only content-preserved; clear the park with "
                    f"{daemon_cli_command_for_docs('branch-park', shlex.quote(name), '--clear')} "
                    "to clean it"
                )
    return spared


def _park_reason(
    name: str, record: BranchRecord, parks: Mapping[str, ParkRecord] | None
) -> str | None:
    """Why a branch is parked: its tip's trailer, or a record on that tip; else None.

    Unreadable park records (``parks`` None) count as parked: the sweep cannot rule
    a park out, so it keeps the branch.
    """
    if record.parked_reason is not None:
        return record.parked_reason
    if parks is None:
        return "park records unreadable"
    standing = parks.get(name)
    if standing is not None and standing.sha in (record.local_tip, record.remote_tip):
        return standing.reason
    return None


def _proven_remote(
    repo: Path,
    config: BranchesConfig,
    default: str,
    records: Mapping[str, BranchRecord],
    *,
    spared: frozenset[str] = frozenset(),
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """``(name -> live tip, name -> problem, name -> evidence tier)`` per merged remote branch.

    Candidates are the inventory's merged and patch-equivalent records with a remote
    copy, past the cleanup policy; each is then judged by the remote-delete guard's
    own proof (:func:`prove_remote_merged`), so this deletes nothing the guard would
    refuse an agent. That proof accepts ancestry, patch-id and tree containment, so a
    patch-equivalent remote branch is deleted too.
    """
    names: list[str] = []
    problems: dict[str, str] = {}
    for name in sorted(records):
        record = records[name]
        if (
            record.cleanup_state not in REMOTE_CLEAN_STATES
            or record.remote_tip is None
            or name in spared
            or policy_refusal(name, config, default) is not None
        ):
            continue
        problem = named_ref_problem(config.remote, name, default, config)
        if problem is None:
            names.append(name)
        else:
            problems[name] = problem
    if not names:
        return {}, problems, {}
    proof = prove_remote_merged(repo, config.remote, names, default, config)
    return proof.tips, {**problems, **proof.problems}, proof.evidence


def proven_remote_only(
    repo: Path, config: BranchesConfig, inventory: branch_inventory.BranchInventory
) -> frozenset[str]:
    """Remote-only done branches the remote-delete guard's proof accepts.

    These are the only names the ``branch-sweep`` report may print a runnable remote
    delete for. The remote is contacted only when such a branch exists.
    """
    default = inventory.default_branch
    if default is None:
        return frozenset()
    remote_only = {
        name: record
        for name, record in inventory.records.items()
        if record.local_tip is None and record.remote_tip is not None
    }
    if not remote_only:
        return frozenset()
    tips, _problems, _evidence = _proven_remote(repo, config, default, remote_only)
    return frozenset(tips)


def delete_remote_branches(
    repo: Path, config: BranchesConfig, default: str, names: Sequence[str]
) -> CleanupReport:
    """The agent's leased route to delete remote branches, each only when the proof accepts it.

    Every name is judged by the remote-delete guard's own proof
    (:func:`prove_remote_merged`, including the surviving-content tier), with the whole
    batch as ``also_deleting`` so no branch vouches for another. An accepted branch is
    deleted under a lease on its proven tip (:func:`_push_deletes`) and reported with
    the ``git push <remote> <sha>:refs/heads/<name>`` line that restores it. A refused
    name is reported in ``skipped`` with the reason and nothing is pushed for it.
    """
    unique = list(dict.fromkeys(branch_name(name) for name in names))
    refused: list[str] = []
    judged: list[str] = []
    for name in unique:
        problem = named_ref_problem(config.remote, name, default, config)
        if problem is None:
            judged.append(name)
        else:
            refused.append(f"{config.remote}/{name}: {problem}")
    tips: dict[str, str] = {}
    if judged:
        proof = prove_remote_merged(
            repo, config.remote, judged, default, config, also_deleting=unique
        )
        tips = proof.tips
        refused += [
            f"{config.remote}/{name}: {proof.problems.get(name, 'the proof did not accept it')}"
            for name in judged
            if name not in tips
        ]
    gone: list[str] = []
    if tips:
        gone, push_refusals = _push_deletes(repo, config.remote, tips)
        refused += push_refusals
    return CleanupReport(
        skipped=tuple(refused),
        commands=tuple(
            f"git push {config.remote} {tips[name]}:{branch_ref(name)}" for name in gone
        ),
        deleted_remote=tuple(f"{config.remote}/{name}" for name in gone),
    )


def push_leased_deletes(
    repo: Path, remote: str, tips: Mapping[str, str]
) -> tuple[list[str], list[str]]:
    """The public name of :func:`_push_deletes`, for the no-value remote route (N763)."""
    return _push_deletes(repo, remote, tips)


def _push_deletes(repo: Path, remote: str, tips: Mapping[str, str]) -> tuple[list[str], list[str]]:
    """Delete each remote branch under a lease on its proven tip: ``(deleted, refusals)``.

    The lease makes git reject a ref whose remote tip moved after the proof, so a
    commit pushed meanwhile is never lost. Results are read per ref from
    ``--porcelain``: ``-`` is a deleted ref, anything else is git's refusal.
    """
    leases = [f"--force-with-lease={branch_ref(name)}:{tip}" for name, tip in tips.items()]
    deletes = [f":{branch_ref(name)}" for name in tips]
    result = run_git(
        repo,
        "push",
        "--porcelain",
        *leases,
        remote,
        *deletes,
        timeout=scaled_timeout(Timeout.GIT_FETCH_SESSION, Timeout.GIT_FETCH_SESSION_MAX),
        env=remote_git_env(),
    )
    outcomes: dict[str, str] = {}
    for line in result.stdout.splitlines():
        flag, _, rest = line.partition("\t")
        spec, _, summary = rest.partition("\t")
        name = spec.removeprefix(":").removeprefix(HEADS_PREFIX)
        if name in tips:
            outcomes[name] = "-" if flag == "-" else summary or flag
    gone = [name for name in tips if outcomes.get(name) == "-"]
    detail = result.stderr.strip() or f"git push exited {result.returncode}"
    refused = [
        f"{remote}/{name}: git refused the remote delete: {outcomes.get(name) or detail}"
        for name in tips
        if name not in gone
    ]
    return gone, refused


def render(report: CleanupReport) -> list[str]:
    """Human lines for a report; empty when there is nothing to say."""
    lines: list[str] = []
    lines += [f"Removed worktree: {path}" for path in report.removed_worktrees]
    if report.deleted:
        lines.append(f"Deleted branch(es): {', '.join(report.deleted)}")
    for cleared in report.park_cleared:
        name, _, reason = cleared.partition(": ")
        lines.append(f"Park cleared: {name} ({reason})")
    if report.deleted_remote:
        lines.append(f"Deleted remote branch(es): {', '.join(report.deleted_remote)}")
    lines += [f"Skipped {line}" for line in report.skipped]
    if report.commands:
        lines.append("Commands:")
        lines += [f"  {command}" for command in report.commands]
    if report.stopped is not None:
        lines.append(f"Stopped: {report.stopped}")
    if report.remaining:
        lines.append(
            f"Remaining {len(report.remaining)} not yet deleted: "
            f"{preview_paths(report.remaining)}"
        )
    if report.next_command is not None:
        label = "Resume with" if report.remaining else "Apply with"
        lines.append(f"{label}: {report.next_command}")
    return lines


__all__ = [
    "BLOCKER_PREVIEW",
    "BULK_BATCH_SIZE",
    "CLEAN_STATES",
    "MERGED_TIERS",
    "REMOTE_CLEAN_STATES",
    "CleanupMode",
    "CleanupReport",
    "WorktreeBlockersFn",
    "blockers_line",
    "clean_sweep",
    "cleanup_after_merge",
    "cleanup_targets",
    "delete_if_merged",
    "delete_remote_branches",
    "linked_worktrees",
    "merge_target_qualifies",
    "policy_refusal",
    "preview_paths",
    "proven_remote_only",
    "remote_delete_advice",
    "render",
    "sweep_clean_command",
    "sweep_clean_line",
    "worktree_blockers",
]
