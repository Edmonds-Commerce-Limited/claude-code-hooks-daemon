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
  ignored file in it lies under a regenerable store (:data:`REGENERABLE_STORES`).

Neither runs the content-preserved tier (a walk of every reachable object), so
only a merged or patch-equivalent branch can ever be deleted here.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import branch_inventory
from claude_code_hooks_daemon.core.branch_inventory import BranchState
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
from claude_code_hooks_daemon.utils.git_repo import (
    branch_ref,
    parse_worktree_porcelain,
    run_git,
)

CleanupMode = Literal["act", "advise", "off"]

#: Tiers whose every commit is reachable from the target: deletable with no bundle.
MERGED_TIERS = frozenset({TIER_MERGED, TIER_MERGED_UNPUSHED, TIER_MERGED_NOT_IN_HEAD})

#: Inventory states ``branch-sweep --clean`` considers.
CLEAN_STATES = frozenset(
    {BranchState.MERGED_DEFAULT, BranchState.MERGED_LINE, BranchState.PATCH_EQUIVALENT}
)

#: Ignored stores a worktree removal may destroy, because each is rebuilt on demand.
#: A directory entry ends in ``/``; the rest are file-name globs under ``untracked/``.
REGENERABLE_STORES = (
    "untracked/venv-*/",
    "untracked/qa/",
    "untracked/docs-qa/",
    "untracked/branch-inventory/",
    "untracked/daemon-*",
    "untracked/events-*",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
)

#: Cache directories regenerable wherever they sit in the tree.
_ANYWHERE_STORES = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
_UNTRACKED = "untracked"
_UNTRACKED_DIR_STORES = ("venv-*", "qa", "docs-qa", "branch-inventory")
_UNTRACKED_FILE_STORES = ("daemon-*", "events-*")

#: Blocking paths listed per skipped worktree before the rest are counted.
BLOCKER_PREVIEW = 10

#: Width of the ``XY `` status prefix in ``git status --porcelain``.
_STATUS_PREFIX = 3

SWEEP_CLEAN_COMMAND = "bin/hooks-daemon branch-sweep --clean"
_BUNDLE_STAMP = "%Y%m%dT%H%M%SZ"


@dataclass(frozen=True)
class CleanupReport:
    """What a cleanup did, skipped and advises.

    Attributes:
        deleted: Local branches removed.
        removed_worktrees: Linked worktrees removed before their branch.
        skipped: ``"<name>: <reason>"`` for every branch left alone.
        commands: Commands to run by hand (advice, restore lines, remote deletes).
        bundle: The recovery bundle written, if any.
    """

    deleted: tuple[str, ...] = ()
    removed_worktrees: tuple[Path, ...] = ()
    skipped: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    bundle: Path | None = None


def _never_work(config: BranchesConfig, default: str) -> tuple[str, ...]:
    """Names and globs no cleanup may delete (DESIGN.md section 1)."""
    return (*config.protected_names, *config.integration_lines, *config.exempt, default)


def policy_refusal(name: str, config: BranchesConfig, default: str) -> str | None:
    """Why policy forbids deleting ``name``, or None when it may be judged."""
    if matches_any_glob(name, _never_work(config, default)):
        return "the default, an integration line, protected or exempt"
    return None


def merge_target_qualifies(target: str | None, config: BranchesConfig, default: str) -> bool:
    """Whether a merge INTO ``target`` earns a cleanup: the default or a line."""
    if target is None:
        return False
    return target == default or matches_any_glob(target, config.integration_lines)


def _ref_exists(repo: Path, ref: str) -> bool:
    return run_git(repo, "show-ref", "--verify", "--quiet", ref).returncode == 0


def cleanup_targets(repo: Path, config: BranchesConfig, default: str) -> list[str]:
    """The refs a merge into counts as safe, only those that exist.

    The default by bare name (``classify_branch`` qualifies it), the remote's
    default, and every integration-line branch local and remote. A missing ref is
    left out because the ancestry and patch proofs fail on it.
    """
    targets = [default] if _ref_exists(repo, branch_ref(default)) else []
    remote_default = f"refs/remotes/{config.remote}/{default}"
    if _ref_exists(repo, remote_default):
        targets.append(remote_default)
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


def linked_worktrees(repo: Path) -> dict[str, Path]:
    """Branch name to path for every LINKED worktree (never the main one)."""
    listing = run_git(repo, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        raise RuntimeError(f"git worktree list failed: {listing.stderr.strip()}")
    records = parse_worktree_porcelain(listing.stdout)[1:]
    return {r.branch: r.path for r in records if r.branch is not None}


def is_regenerable(entry: str) -> bool:
    """Whether an ignored ``ls-files --directory`` entry lies under a regenerable store."""
    parts = entry.rstrip("/").split("/")
    if any(part in _ANYWHERE_STORES for part in parts[:-1]) or (
        entry.endswith("/") and parts[-1] in _ANYWHERE_STORES
    ):
        return True
    if len(parts) < 2 or parts[0] != _UNTRACKED:
        return False
    store = parts[1]
    inside_dir = entry.endswith("/") or len(parts) > 2
    if inside_dir and any(fnmatch.fnmatchcase(store, p) for p in _UNTRACKED_DIR_STORES):
        return True
    return any(fnmatch.fnmatchcase(store, p) for p in _UNTRACKED_FILE_STORES)


def _expand(root: Path, entry: str) -> list[str]:
    """Open a collapsed ``untracked/`` entry one level, so its stores can be told apart.

    ``ls-files --directory`` reports a WHOLLY ignored directory as one entry. For
    ``untracked/`` that hides the regenerable stores among the scratch notes, so
    its children are listed and judged one by one. Any other entry is as given.
    """
    if entry != f"{_UNTRACKED}/":
        return [entry]
    children = sorted((root / _UNTRACKED).iterdir(), key=lambda child: child.name)
    return [f"{entry}{c.name}/" if c.is_dir() else f"{entry}{c.name}" for c in children]


def worktree_blockers(path: Path) -> tuple[str, ...]:
    """Paths a removal of the worktree at ``path`` would lose.

    Modified and untracked files (git refuses those anyway) and every ignored
    entry outside :data:`REGENERABLE_STORES`. A git failure is itself a blocker:
    an unread tree is never called clean.
    """
    status = run_git(path, "status", "--porcelain")
    if status.returncode != 0:
        return (f"<git status failed: {status.stderr.strip()}>",)
    dirty = [line[_STATUS_PREFIX:] for line in status.stdout.splitlines() if line]
    ignored = run_git(
        path, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"
    )
    if ignored.returncode != 0:
        return (*dirty, f"<git ls-files failed: {ignored.stderr.strip()}>")
    entries = [e for line in ignored.stdout.splitlines() if line for e in _expand(path, line)]
    kept = [entry for entry in entries if not is_regenerable(entry)]
    return (*dirty, *kept)


def _preview(paths: Sequence[str]) -> str:
    shown = ", ".join(paths[:BLOCKER_PREVIEW])
    rest = len(paths) - BLOCKER_PREVIEW
    return f"{shown} and {rest} more" if rest > 0 else shown


def remote_delete_command(repo: Path, remote: str, name: str) -> str | None:
    """The remote delete to run by hand, when the remote holds the branch."""
    if _ref_exists(repo, f"refs/remotes/{remote}/{name}"):
        return f"git push {remote} --delete {name}"
    return None


def _classify(
    repo: Path,
    name: str,
    targets: Sequence[str],
    never_work: Sequence[str],
    *,
    ignore_worktree: bool = False,
) -> BranchClassification:
    return classify_branch(
        repo,
        name,
        protected_names=never_work,
        targets=targets,
        ignore_worktree=ignore_worktree,
        content_tier=False,
    )


def cleanup_after_merge(
    repo: Path,
    names: Sequence[str],
    *,
    config: BranchesConfig,
    target: str,
    mode: CleanupMode,
) -> CleanupReport:
    """Delete (``act``) or advise deleting the branches just merged into ``target``.

    Only the merged tiers are deleted, with no bundle: the restore line is printed
    instead. A worktree holding the branch, and a patch-equivalent branch, are
    only ever advised.
    """
    if mode == "off":
        return CleanupReport()
    never_work = _never_work(config, target)
    targets = [target]
    worktrees = linked_worktrees(repo)
    deleted: list[str] = []
    skipped: list[str] = []
    commands: list[str] = []
    delete_command = "bin/hooks-daemon delete-branch {name} --protected-ref " + target
    for name in names:
        refusal = policy_refusal(name, config, target)
        if refusal is not None:
            skipped.append(f"{name}: {refusal}")
            continue
        held_by = worktrees.get(name)
        verdict = _classify(repo, name, targets, never_work, ignore_worktree=held_by is not None)
        if verdict.refusal is not None:
            skipped.append(f"{name}: {verdict.detail}")
            continue
        if verdict.tier == TIER_PATCH_EQUIVALENT:
            skipped.append(f"{name}: patch-equivalent, not reachable from {target}")
            commands.append(SWEEP_CLEAN_COMMAND)
            continue
        if verdict.tier not in MERGED_TIERS:
            skipped.append(f"{name}: {verdict.detail}")
            continue
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
            )
            if name not in report.deleted:
                skipped += [f"{name}: {blocker}" for blocker in report.blockers]
                continue
            deleted.append(name)
            commands.append(f"git branch {name} {verdict.tip}")
        remote = remote_delete_command(repo, config.remote, name)
        if remote is not None:
            commands.append(remote)
    return CleanupReport(
        deleted=tuple(deleted), skipped=tuple(skipped), commands=tuple(dict.fromkeys(commands))
    )


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
) -> CleanupReport:
    """Delete every merged and patch-equivalent local branch, behind a bundle.

    Each candidate is classified on its own first, because ``delete_branches`` is
    all-or-nothing: only the proven ones are batched. A linked worktree is removed
    first, and only when :func:`worktree_blockers` finds nothing it would lose.

    Raises:
        branch_inventory.BranchInventoryError: The refs could not be listed.
        ValueError: No default branch can be resolved.
    """
    inventory = branch_inventory.build_inventory(repo, config)
    default = inventory.default_branch
    if default is None:
        raise ValueError("cannot determine the default branch; set branches.default")
    targets = cleanup_targets(repo, config, default)
    never_work = _never_work(config, default)
    worktrees = linked_worktrees(repo)
    candidates = sorted(
        name
        for name, record in inventory.records.items()
        if record.state in CLEAN_STATES
        and record.local_tip is not None
        and policy_refusal(name, config, default) is None
    )
    proven: list[str] = []
    removed: list[Path] = []
    skipped: list[str] = []
    commands: list[str] = []
    for name in candidates:
        held_by = worktrees.get(name)
        if held_by is not None:
            blockers = worktree_blockers(held_by)
            if blockers:
                skipped.append(
                    f"{name}: the worktree {held_by} holds {len(blockers)} path(s) a removal "
                    f"would lose: {_preview(blockers)}"
                )
                continue
        verdict = _classify(repo, name, targets, never_work, ignore_worktree=held_by is not None)
        if not verdict.is_safe:
            skipped.append(f"{name}: {verdict.detail}")
            continue
        if dry_run:
            if held_by is not None:
                commands.append(f"would remove the worktree {held_by}")
            commands.append(f"would delete {name} ({verdict.tier})")
            proven.append(name)
            continue
        if held_by is not None:
            refused = _remove_worktree(repo, held_by)
            if refused is not None:
                skipped.append(f"{name}: git refused to remove {held_by}: {refused}")
                continue
            removed.append(held_by)
        proven.append(name)

    deleted: tuple[str, ...] = ()
    bundle: Path | None = None
    if proven and not dry_run:
        stamp = datetime.now(UTC).strftime(_BUNDLE_STAMP)
        report = delete_branches(
            repo,
            proven,
            protected_names=never_work,
            targets=targets,
            bundle_path=bundle_dir / f"branch-cleanup-{stamp}.bundle",
            content_tier=False,
        )
        deleted, bundle = report.deleted, report.bundle
        skipped += list(report.blockers)
        if bundle is not None:
            commands += [
                f"git fetch {bundle} refs/heads/{name}:refs/heads/{name}" for name in deleted
            ]
    for name in proven if dry_run else deleted:
        remote = remote_delete_command(repo, config.remote, name)
        if remote is not None:
            commands.append(remote)
    return CleanupReport(
        deleted=deleted,
        removed_worktrees=tuple(removed),
        skipped=tuple(skipped),
        commands=tuple(commands),
        bundle=bundle,
    )


def render(report: CleanupReport) -> list[str]:
    """Human lines for a report; empty when there is nothing to say."""
    lines: list[str] = []
    lines += [f"Removed worktree: {path}" for path in report.removed_worktrees]
    if report.deleted:
        lines.append(f"Deleted branch(es): {', '.join(report.deleted)}")
    if report.bundle is not None:
        lines.append(f"Recovery bundle: {report.bundle}")
    lines += [f"Skipped {line}" for line in report.skipped]
    if report.commands:
        lines.append("Commands:")
        lines += [f"  {command}" for command in report.commands]
    return lines


__all__ = [
    "BLOCKER_PREVIEW",
    "CLEAN_STATES",
    "MERGED_TIERS",
    "REGENERABLE_STORES",
    "SWEEP_CLEAN_COMMAND",
    "CleanupMode",
    "CleanupReport",
    "clean_sweep",
    "cleanup_after_merge",
    "cleanup_targets",
    "is_regenerable",
    "linked_worktrees",
    "merge_target_qualifies",
    "policy_refusal",
    "remote_delete_command",
    "render",
    "worktree_blockers",
]
