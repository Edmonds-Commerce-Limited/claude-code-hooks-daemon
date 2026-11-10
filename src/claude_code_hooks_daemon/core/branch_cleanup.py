"""Delete branches proven merged: after a merge, and from ``branch-sweep --clean``.

Plan 00558 Task 3.1 (DESIGN.md section 7). Two callers share this module so they
cannot disagree about what is safe:

- the ``cleanup_after_merge`` PostToolUse handler deletes ONLY the merged tier
  (every commit reachable from the merge target), without a recovery bundle, and
  prints the ``git branch <name> <sha>`` restore line instead. A bundle of one
  branch here took 8.2 s and 51 MB, which no hook budget absorbs. It never
  removes a worktree: ``git worktree remove`` deletes ignored files, and that loss
  is issue #155. It advises instead.
- ``branch-sweep --clean`` deletes the merged AND patch-equivalent tiers behind a
  recovery bundle, and removes a linked worktree only when it is clean and every
  ignored file in it lies under a regenerable store
  (``branches.cleanup_after_merge.regenerable``).

Neither runs the content-preserved tier (a walk of every reachable object), so
only a merged or patch-equivalent branch can ever be deleted here.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
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
from claude_code_hooks_daemon.core.branch_park import clear_park_record
from claude_code_hooks_daemon.core.remote_branch_proof import (
    REMOTES_PREFIX,
    named_ref_problem,
    prove_remote_merged,
)
from claude_code_hooks_daemon.daemon.branch_safety import (
    TIER_MERGED,
    TIER_MERGED_NOT_IN_HEAD,
    TIER_MERGED_UNPUSHED,
    TIER_PATCH_EQUIVALENT,
    BranchClassification,
    bundle_restore_command,
    classify_branch,
    delete_branches,
    matches_any_glob,
    new_bundle_path,
    write_recovery_bundle,
)
from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import (
    GIT_COMMAND_ERRORS,
    HEADS_PREFIX,
    WorktreeRecord,
    branch_ref,
    parse_worktree_porcelain,
    run_git,
)
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to
from claude_code_hooks_daemon.utils.regenerable_paths import (
    clone_probe_globs,
    is_regenerable,
    lock_regenerated_dirs,
    under_any,
)

logger = logging.getLogger(__name__)

CleanupMode = Literal["act", "advise", "off"]

#: Tiers whose every commit is reachable from the target: deletable with no bundle.
MERGED_TIERS = frozenset({TIER_MERGED, TIER_MERGED_UNPUSHED, TIER_MERGED_NOT_IN_HEAD})

#: Inventory states ``branch-sweep --clean`` considers.
CLEAN_STATES = frozenset(
    {BranchState.MERGED_DEFAULT, BranchState.MERGED_LINE, BranchState.PATCH_EQUIVALENT}
)

_UNTRACKED = "untracked"

#: Blocking paths listed per skipped worktree before the rest are counted.
BLOCKER_PREVIEW = 10

#: Width of the ``XY `` status prefix in ``git status --porcelain``.
_STATUS_PREFIX = 3


#: Branches (local and remote together) one ``--clean --apply`` batch deletes: one recovery
#: bundle and one ``git push --delete`` per batch, so an interruption loses at most one.
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
        f"Delete every provably merged branch in one step, behind a recovery bundle: "
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
        bundle: The recovery bundle written, if any.
        deleted_remote: Remote branches removed, as ``<remote>/<name>``.
        bundles: Every recovery bundle written, one per batch (``bundle`` is the last).
        remaining: Branches proven for deletion that this run did not delete
            (``<name>``, or ``<remote>/<name>`` for a remote copy).
        stopped: Why a bulk run ended early (interrupt or failed batch), else None.
        next_command: The command to run next: apply after a preview, resume after a stop.
    """

    deleted: tuple[str, ...] = ()
    removed_worktrees: tuple[Path, ...] = ()
    skipped: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    bundle: Path | None = None
    deleted_remote: tuple[str, ...] = ()
    park_cleared: tuple[str, ...] = ()
    bundles: tuple[Path, ...] = ()
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
    status = run_git(path, "status", "--porcelain")
    if status.returncode != 0:
        return ((f"<git status failed: {status.stderr.strip()}>",), ())
    dirty = [line[_STATUS_PREFIX:] for line in status.stdout.splitlines() if line]
    ignored = run_git(
        path, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"
    )
    if ignored.returncode != 0:
        return ((*dirty, f"<git ls-files failed: {ignored.stderr.strip()}>"), ())
    entries = [e for line in ignored.stdout.splitlines() if line for e in _expand(path, line)]
    undecided = [
        entry
        for entry in entries
        if not _is_symlink(path, entry)
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


def remote_delete_advice(repo: Path, config: BranchesConfig, default: str, name: str) -> str | None:
    """What to tell a person about the remote copy of ``name``, when the remote holds one.

    The runnable delete line only when the remote-delete guard's own proof
    (:func:`prove_remote_merged`) accepts the branch, so a printed command is one the
    guard allows. Otherwise owner-only wording, which is advice and not a command.
    """
    remote = config.remote
    if not _ref_exists(repo, f"refs/remotes/{remote}/{name}"):
        return None
    problem = named_ref_problem(remote, name, default, config)
    if problem is None:
        proof = prove_remote_merged(repo, remote, [name], default, config)
        problem = proof.problems.get(name)
        if problem is None and name in proof.tips:
            return f"git push {remote} --delete {name}"
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
) -> BranchClassification:
    return classify_branch(
        repo,
        name,
        protected_names=never_work,
        targets=targets,
        ignore_worktree=ignore_worktree,
        content_tier=False,
        line_names=lines,
        line_targets=line_targets,
    )


def _clear_parks(repo: Path, names: Sequence[str]) -> tuple[str, ...]:
    """Clear the park record of each merged branch; ``"<name>: <reason>"`` for each cleared.

    A merge ends a park, so the record goes with it and the report says so.
    """
    cleared: list[str] = []
    for name in names:
        record = clear_park_record(repo, name)
        if record is not None:
            cleared.append(f"{name}: {record.reason}")
    return tuple(cleared)


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

    Only the merged tiers are deleted, with no bundle: the restore line is printed
    instead. A worktree holding the branch, and a patch-equivalent branch, are
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
    delete_command = (
        daemon_cli_command_for_docs("delete-branch") + " {name} --protected-ref " + target
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
        park_cleared += _clear_parks(repo, [name])
        if held_by is not None:
            skipped.append(f"{name}: checked out in the worktree {held_by}")
            commands += [f"git worktree remove {held_by}", delete_command.format(name=name)]
        elif mode == "advise":
            commands.append(delete_command.format(name=name))
        else:
            report = delete_branches(
                repo,
                [name],
                protected_names=never_work,
                targets=targets,
                bundle_path=None,
                content_tier=False,
                line_names=lines,
                line_targets=targets,
            )
            if name not in report.deleted:
                skipped += [f"{name}: {blocker}" for blocker in report.blockers]
                continue
            deleted.append(name)
            commands.append(f"git branch {name} {verdict.tip}")
        remote = remote_delete_advice(repo, config, protected_default, name)
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
    deleted, with no bundle (the restore line is printed instead); anything else
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
    park_cleared = _clear_parks(repo, [name])
    report = delete_branches(
        repo,
        [name],
        protected_names=never_work,
        targets=targets,
        bundle_path=None,
        content_tier=False,
        line_names=config.integration_lines,
        line_targets=line_targets,
    )
    if name not in report.deleted:
        return CleanupReport(
            skipped=tuple(f"{name}: {b}" for b in report.blockers), park_cleared=park_cleared
        )
    commands = [f"git branch {name} {verdict.tip}"]
    remote = remote_delete_advice(repo, config, default, name)
    if remote is not None:
        commands.append(remote)
    return CleanupReport(deleted=(name,), commands=tuple(commands), park_cleared=park_cleared)


def _remove_worktree(repo: Path, path: Path) -> str | None:
    """Remove a linked worktree without ``--force``; git's refusal verbatim, or None."""
    result = run_git(repo, "worktree", "remove", str(path), timeout=Timeout.GIT_WORKTREE_REMOVE)
    if result.returncode == 0:
        return None
    return result.stderr.strip() or f"git worktree remove exited {result.returncode}"


def clean_sweep(
    repo: Path,
    config: BranchesConfig,
    *,
    dry_run: bool,
    bundle_dir: Path,
    remote: bool = False,
    untracked: Path | None = None,
) -> CleanupReport:
    """Delete every merged and patch-equivalent local branch, behind a bundle.

    With ``remote`` (``--clean --remote``) every merged branch the remote holds is
    deleted there too, by the remote-delete guard's proof, its tip in the same
    bundle. That path contacts the remote (``ls-remote``, ``push``).

    Each candidate is classified on its own first, because ``delete_branches`` is
    all-or-nothing: only the proven ones are batched. A linked worktree is removed
    first, and only when :func:`worktree_blockers` finds nothing it would lose.

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
    inventory = branch_inventory.build_inventory(repo, unhurried)
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
    spared = _spared(config, inventory.records)
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
                skipped.append(
                    f"{name}: the worktree {held_by} holds {len(blockers)} path(s) a removal "
                    f"would lose: {preview_paths(blockers)}"
                )
                continue
        verdict = _classify(
            repo,
            name,
            targets,
            never_work,
            lines=config.integration_lines,
            line_targets=line_targets,
            ignore_worktree=held_by is not None,
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
    if remote and keep_fetch_error is not None:
        skipped.append(
            f"{config.remote}: keep notes could not be fetched ({keep_fetch_error}), "
            "so the remote half was refused"
        )
    elif remote:
        remote_tips, problems = _proven_remote(
            repo, config, default, inventory.records, spared=frozenset({*owned, *spared})
        )
        skipped += [f"{config.remote}/{name}: {why}" for name, why in problems.items()]
        skipped += [
            f"{config.remote}/{name}: {spared[name]}"
            for name in sorted(spared)
            if inventory.records[name].remote_tip is not None
            and inventory.records[name].state in CLEAN_STATES
        ]
    apply_command = sweep_clean_command(remote=remote)
    if dry_run:
        commands += [
            f"would delete remote {config.remote}/{name} (tip {tip[:_TIP_PREVIEW]}, "
            f"proven merged into {default})"
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
        bundle_dir=bundle_dir,
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
    bundle_dir: Path
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
    bundles: list[Path] = field(default_factory=list)
    deleted_remote: list[str] = field(default_factory=list)
    park_cleared: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)


def _apply_in_batches(
    plan: _BulkPlan, units: Sequence[str], skipped: list[str], apply_command: str
) -> CleanupReport:
    """Delete ``units`` ``BULK_BATCH_SIZE`` at a time, stopping cleanly on an interrupt.

    The only state is the repository: a deleted branch is no longer a candidate, so
    running the same command again continues where this one stopped, and a bundle is
    written before each batch's deletions. A SIGINT or a failed batch ends the loop;
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
        bundle=outcome.bundles[-1] if outcome.bundles else None,
        bundles=tuple(outcome.bundles),
        deleted_remote=tuple(outcome.deleted_remote),
        park_cleared=tuple(outcome.park_cleared),
        remaining=tuple(dict.fromkeys(outcome.remaining)),
        stopped=stopped,
        next_command=apply_command if needs_resume else None,
    )


def _run_batch(plan: _BulkPlan, batch: Sequence[str], outcome: _Outcome) -> None:
    """One batch: worktrees, bundle, local deletes, then one push for the remote copies.

    An already-deleted local branch is skipped, never an error. A batch whose delete
    is refused, or whose remote push is refused, adds what is left to ``remaining``
    so the report can name it; a later run retries exactly those.
    """
    repo, config = plan.repo, plan.config
    local: list[str] = []
    for name in batch:
        if name not in plan.proven:
            continue
        if not _ref_exists(repo, branch_ref(name)):
            outcome.skipped.append(f"{name}: already deleted")
            continue
        held_by = plan.worktrees.get(name)
        if held_by is not None:
            refused = _remove_worktree(repo, held_by)
            if refused is not None:
                outcome.skipped.append(f"{name}: git refused to remove {held_by}: {refused}")
                continue
            outcome.removed.append(held_by)
        local.append(name)
    tips = {name: plan.remote_tips[name] for name in batch if name in plan.remote_tips}
    tracking = {name: f"{REMOTES_PREFIX}{config.remote}/{name}" for name in tips}
    outcome.park_cleared += _clear_parks(repo, local)
    bundle: Path | None = None
    bundle_path = new_bundle_path(plan.bundle_dir, "branch-cleanup")
    deleted: tuple[str, ...] = ()
    if local:
        report = delete_branches(
            repo,
            local,
            protected_names=plan.never_work,
            targets=plan.targets,
            bundle_path=bundle_path,
            content_tier=False,
            line_names=config.integration_lines,
            line_targets=plan.line_targets,
            extra_bundle_refs=list(tracking.values()),
        )
        deleted, bundle = report.deleted, report.bundle
        outcome.skipped += report.blockers
    elif tracking:
        bundle = write_recovery_bundle(repo, [], bundle_path, extra_refs=list(tracking.values()))
    if bundle is not None:
        outcome.bundles.append(bundle)
        outcome.commands += [bundle_restore_command(bundle, branch_ref(name)) for name in deleted]
    outcome.deleted += deleted
    outcome.remaining += [name for name in local if name not in deleted]
    if bundle is not None and tips:
        gone, push_refusals = _push_deletes(repo, config.remote, tips)
        outcome.skipped += push_refusals
        outcome.deleted_remote += [f"{config.remote}/{name}" for name in gone]
        outcome.remaining += [name for name in tips if name not in gone]
        outcome.commands += [
            f"{bundle_restore_command(bundle, tracking[name])} && "
            f"git push {config.remote} {tracking[name]}:{branch_ref(name)}"
            for name in gone
        ]
    elif tips:
        outcome.remaining += list(tips)
    for name in deleted:
        advice = remote_delete_advice(repo, config, plan.default, name)
        if advice is not None and name not in tips:
            outcome.commands.append(advice)


def _spared(config: BranchesConfig, records: Mapping[str, BranchRecord]) -> dict[str, str]:
    """``name -> reason`` for every branch ``--clean`` must leave alone on both sides.

    A keep inside its age, and any ``bot_owned`` name (defence in depth: the
    inventory already gives those a state outside CLEAN_STATES).
    """
    spared: dict[str, str] = {}
    for name, record in records.items():
        if matches_any_glob(name, config.bot_owned):
            spared[name] = "bot-owned (branches.bot_owned)"
        elif record.kept_reason is not None and not record.stale:
            spared[name] = f"kept: {record.kept_reason}"
    return spared


def _proven_remote(
    repo: Path,
    config: BranchesConfig,
    default: str,
    records: Mapping[str, BranchRecord],
    *,
    spared: frozenset[str] = frozenset(),
) -> tuple[dict[str, str], dict[str, str]]:
    """``(name -> live tip, name -> problem)`` for every merged branch the remote holds.

    Candidates are the inventory's merged and patch-equivalent records with a remote
    copy, past the cleanup policy; each is then judged by the remote-delete guard's
    own proof (:func:`prove_remote_merged`), so this deletes nothing the guard would
    refuse an agent. That proof accepts ancestry, patch-id and tree containment, so a
    patch-equivalent remote branch is deleted too (behind the same bundle).
    """
    names: list[str] = []
    problems: dict[str, str] = {}
    for name in sorted(records):
        record = records[name]
        if (
            record.cleanup_state not in CLEAN_STATES
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
        return {}, problems
    proof = prove_remote_merged(repo, config.remote, names, default, config)
    return proof.tips, {**problems, **proof.problems}


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
    tips, _problems = _proven_remote(repo, config, default, remote_only)
    return frozenset(tips)


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
        timeout=Timeout.GIT_FETCH_SESSION,
        env={"GIT_TERMINAL_PROMPT": "0"},
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
    if len(report.bundles) > 1:
        lines.append(f"Recovery bundles ({len(report.bundles)}): {report.bundles[0].parent}")
    elif report.bundle is not None:
        lines.append(f"Recovery bundle: {report.bundle}")
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
    "CleanupMode",
    "CleanupReport",
    "clean_sweep",
    "cleanup_after_merge",
    "cleanup_targets",
    "delete_if_merged",
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
