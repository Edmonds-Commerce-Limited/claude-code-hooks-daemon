"""Apply a project's configured seed list to a worktree made by hand (Plan 00613).

The ``worktree_create`` handler seeds the worktrees Claude Code creates. A
worktree made with a hand-run ``git worktree add`` never passes through that
hook, so it lacks the git-ignored files the main checkout works with, a
protected vault password file among them. This module re-applies THE CONFIGURED
LIST to one such worktree.

**It takes no path to link.** The owner approved linking a protected file into
a worktree by a route the project config or a human owns, never by one that
lets an agent link an arbitrary protected path. The only argument is the
worktree; what is placed, and in which mode, is read from the project's own
config, so this adds no route the config does not already grant at creation.

Everything is judged as at creation, by the same executor: the copy refusal for
a protected source and the audit line before each protected link. Placement
never overwrites an existing destination, so a second run places nothing.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from claude_code_hooks_daemon.config.models import Config, handler_options
from claude_code_hooks_daemon.config.yaml_loading import safe_load_yaml
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.worktree_seed import SeedEntry, parse_seed_config
from claude_code_hooks_daemon.utils import git_sync
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import (
    GitRepo,
    branch_ref,
    parse_worktree_porcelain,
    run_git,
)
from claude_code_hooks_daemon.utils.worktree_seeding import (
    LinkAudit,
    SeedPlacementError,
    WorktreeSeedError,
    protecting_pattern_for_source,
    seed_link_audit_path,
    seed_worktree,
    validate_seed_sources,
)

logger = logging.getLogger(__name__)

#: The audit verb of a link placed by this route, distinct from creation's.
SEED_APPLY_VERB = "seed-worktree"

#: The daemon config's names under the main checkout's ``.claude/``, in the
#: order the daemon's own loader tries them.
_CONFIG_NAMES = ("hooks-daemon.yaml", "hooks-daemon.yml")

_HANDLER_KEY = "worktree_create"
_SEED_OPTION = "seed"
_SECRET_GUARD_KEY = "secret_file_guard"


class SeedApplyRefused(RuntimeError):
    """The worktree, the config or a seed entry cannot be honoured; nothing was placed
    unless the message says which entries were, and ``placed`` lists their destinations."""

    def __init__(self, message: str, placed: list[Path] | None = None) -> None:
        super().__init__(message)
        self.placed: list[Path] = list(placed or [])


def _has_control_character(text: str) -> bool:
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in text)


def _refuse_another_project(main: Path, project_root: Path) -> None:
    """Refuse a worktree whose main checkout is not the daemon project's main checkout.

    Git is asked from the TARGET to find its main checkout, so a worktree of a
    sibling clone would otherwise bring its own config, its own committed
    baseline and its own audit log (security review D-PATH 1). The project
    root may itself be a linked worktree (a worktree-root daemon): its main
    checkout is what is compared.
    """
    repo = GitRepo.resolve_for(project_root)
    ours = repo.main_worktree_root().resolve() if repo is not None else None
    if ours != main:
        raise SeedApplyRefused(
            "target worktree: it is not a worktree of this project (its main checkout is "
            f"{main}, the daemon's project is {ours or project_root}); nothing was placed"
        )


def _main_checkout_of(worktree: Path) -> Path:
    """The main checkout of the repository ``worktree`` is registered in.

    ``worktree`` must be exactly one of the non-main worktrees git lists, by
    realpath: the main checkout itself, a directory inside a worktree, a
    prunable entry or an unlisted directory all refuse.
    """
    if _has_control_character(str(worktree)):
        raise SeedApplyRefused("target worktree: the path holds a control character")
    if not worktree.is_dir():
        raise SeedApplyRefused(f"target worktree: {worktree} is not a directory")
    target = worktree.resolve()
    listing = run_git(target, "worktree", "list", "--porcelain", timeout=Timeout.GIT_WORKTREE)
    if listing.returncode != 0:
        raise SeedApplyRefused(
            f"target worktree: git could not list the worktrees of {target} "
            f"(status {listing.returncode})"
        )
    records = parse_worktree_porcelain(listing.stdout)
    if not records:
        raise SeedApplyRefused(f"target worktree: git lists no worktree for {target}")
    main = records[0].path.resolve()
    if target == main:
        raise SeedApplyRefused(
            "target worktree: that is the main checkout, which holds the sources; "
            "name a linked worktree"
        )
    for record in records[1:]:
        if record.path.resolve() == target:
            if record.prunable:
                raise SeedApplyRefused("target worktree: git marks it prunable")
            return main
    raise SeedApplyRefused(
        f"target worktree: {target} is not a registered worktree of its repository "
        "(name the worktree's top directory)"
    )


def _load_config(main: Path) -> Config:
    """The main checkout's daemon config, read STRICTLY: no fallback to defaults.

    Found by the names the daemon itself accepts (``.yaml``, then ``.yml``).
    Read fresh from disk, so an uncommitted edit counts at once.
    """
    candidates = [main / ".claude" / name for name in _CONFIG_NAMES]
    path = next((c for c in candidates if c.is_file()), candidates[0])
    try:
        return Config.load(path)
    except (OSError, RuntimeError, ValueError, yaml.YAMLError) as exc:
        raise SeedApplyRefused(
            f"the daemon config at {path} could not be loaded ({type(exc).__name__}), "
            "so the seed list cannot be read"
        ) from exc


def _seed_entries(config: Config) -> list[SeedEntry]:
    """The configured entries; a disabled ``worktree_create`` handler refuses."""
    block = config.handlers.worktree_create.get(_HANDLER_KEY)
    if getattr(block, "enabled", True) is False:
        raise SeedApplyRefused(
            "the worktree_create handler is disabled in the config, so its seed list "
            "is not in force"
        )
    return parse_seed_config(handler_options(block).get(_SEED_OPTION))


def _refuse_redirected_parents(worktree: Path, entries: list[SeedEntry]) -> None:
    """Refuse an entry whose destination's parent, inside ``worktree``, is a symlink.

    A hand-made worktree is not fresh: a directory link inside it would carry
    the placement somewhere else. Checked with ``lstat`` (no link followed),
    on every existing component between the worktree and the destination.
    """
    for number, entry in enumerate(entries, start=1):
        current = worktree
        for part in Path(entry.path).parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise SeedApplyRefused(
                    f"seed entry #{number}: a parent of its destination inside the "
                    "worktree is a symlink, so the placement could land elsewhere"
                )
            if not current.exists():
                break


def _committed_seed_baseline(committed: Config) -> set[SeedEntry]:
    """The seed entries the committed config lists; none when its handler is disabled."""
    block = committed.handlers.worktree_create.get(_HANDLER_KEY)
    if getattr(block, "enabled", True) is False:
        return set()
    return set(parse_seed_config(handler_options(block).get(_SEED_OPTION)))


def _baseline_ref(main: Path) -> tuple[str | None, str]:
    """The default branch's ref when the main checkout is on it, else None and why.

    Re-review R5: ``HEAD`` is movable (``git checkout --detach <any commit>``),
    so the baseline is the tip of the repository's default branch, and only
    while the main checkout is attached to it. The default comes from git
    (``<remote>/HEAD``, else a local ``main``/``master``), never from the
    working config this check exists to distrust. The ref is fully qualified,
    so a tag of the same name cannot stand in for the branch.
    """
    head = run_git(main, "symbolic-ref", "--quiet", "HEAD", timeout=Timeout.GIT_WORKTREE)
    if head.returncode != 0:
        return None, "the main checkout's HEAD is detached"
    default = git_sync.default_branch(main)
    if default is None:
        return None, "the repository's default branch cannot be told"
    if head.stdout.strip() != branch_ref(default):
        return None, "the main checkout is not on the default branch"
    return branch_ref(default), ""


def _committed_config(main: Path, ref: str) -> Config | None:
    """The daemon config committed at ``ref``; None when there is none.

    Found by the names the daemon accepts, in its order. A config git cannot show,
    or one that does not parse, is no baseline: the caller then refuses every
    protected link.
    """
    for name in _CONFIG_NAMES:
        shown = run_git(main, "show", f"{ref}:.claude/{name}", timeout=Timeout.GIT_WORKTREE)
        if shown.returncode != 0:
            continue
        try:
            return Config.model_validate(safe_load_yaml(shown.stdout) or {})
        except (RuntimeError, ValueError, yaml.YAMLError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="a committed config that does not parse is no baseline (fail closed)",
            )
            return None
    return None


_UNCOMMITTED_REFUSAL = (
    "seed entry #{number}: it links a protected path, and the config committed on the "
    "default branch, with the main checkout on that branch, does not list it{why}. Commit "
    "the config change to the default branch first; nothing was placed"
)


def _working_protected_patterns(main: Path, number: int) -> tuple[str, ...]:
    """The protected set the main checkout's config on disk declares, read STRICTLY.

    Re-review R6: both routes judge with this one source, so a daemon whose own
    config differs (a worktree-root daemon's) cannot change the verdict. An
    unreadable config, or unreadable guard options, refuses (fail closed).
    """
    try:
        config = _load_config(main)
    except SeedApplyRefused as exc:
        raise WorktreeSeedError(
            _UNCOMMITTED_REFUSAL.format(number=number, why="") + f" ({exc})"
        ) from exc
    options = handler_options(config.handlers.pre_tool_use.get(_SECRET_GUARD_KEY))
    try:
        return sfm.protected_patterns_from_options(options)
    except sfm.ProtectedSetUnreadable as exc:
        raise WorktreeSeedError(
            _UNCOMMITTED_REFUSAL.format(number=number, why="")
            + " (the secret_file_guard options in the main checkout's config could not be read)"
        ) from exc


def refuse_uncommitted_protected_links(main: Path, entries: list[SeedEntry]) -> None:
    """Refuse a protected seed entry the config committed on the default branch does not list.

    The ONE check both seeding routes run before anything is placed, with the
    same arguments and the same config source: the creation hook (whose list
    is the daemon's loaded config, so an uncommitted edit takes effect after a
    restart) and ``seed-worktree``. An entry whose source is, holds or links to
    a path protected by the shipped defaults, the main checkout's config on
    disk or the committed config is placed only when the committed config
    lists the same entry (security review F6). This NARROWS the route to one
    that leaves a commit on the default branch behind; it does not close it.

    The baseline is the default branch's tip, and only while the main checkout
    is on it (re-review R5): detached, or on another branch, there is none.
    An entry the baseline lists needs nothing more; for any other entry an
    unreadable main config or unreadable guard options refuse (re-review R6).

    Raises:
        WorktreeSeedError: the first such entry, named by position only.
    """
    ref, why = _baseline_ref(main)
    committed = _committed_config(main, ref) if ref is not None else None
    baseline = _committed_seed_baseline(committed) if committed is not None else set()
    pending = [(n, e) for n, e in enumerate(entries, start=1) if e not in baseline]
    if not pending:
        return
    why = f" ({why})" if why else ""
    patterns: tuple[str, ...] = (
        *sfm.DEFAULT_PROTECTED_PATTERNS,
        *_working_protected_patterns(main, pending[0][0]),
    )
    if committed is not None:
        committed_guard = handler_options(committed.handlers.pre_tool_use.get(_SECRET_GUARD_KEY))
        try:
            patterns = (*patterns, *sfm.protected_patterns_from_options(committed_guard))
        except sfm.ProtectedSetUnreadable as exc:
            raise WorktreeSeedError(
                _UNCOMMITTED_REFUSAL.format(number=pending[0][0], why=why)
                + " (the committed secret_file_guard options could not be read)"
            ) from exc
    patterns = tuple(dict.fromkeys(patterns))
    for number, entry in pending:
        # A source that could not be walked is judged protected (fail closed).
        if protecting_pattern_for_source(main, entry.path, patterns) is not None:
            raise WorktreeSeedError(_UNCOMMITTED_REFUSAL.format(number=number, why=why))


def seed_existing_worktree(worktree: Path, *, project_root: Path) -> list[Path]:
    """Place the configured seed entries into the registered ``worktree``.

    Args:
        worktree: A linked worktree of a repository whose main checkout holds a
            daemon config. Nothing here names what to place.
        project_root: The daemon's project root. ``worktree`` must belong to the
            same repository (its main checkout is the project's main checkout).

    Returns:
        The destinations created, in configured order; empty when nothing is
        configured or every destination already exists.

    Raises:
        SeedApplyRefused: the worktree is not a registered linked worktree of
            this project, the config cannot be read, an entry is unusable
            (absent, unsafe, or a protected source in copy mode), or a
            placement failed part-way (``placed`` lists what landed). A
            filesystem error anywhere is a refusal, never a raw ``OSError``.
    """
    try:
        return _seed_existing_worktree(worktree, project_root)
    except OSError as exc:
        raise SeedApplyRefused(
            f"a filesystem error stopped the seeding ({type(exc).__name__}: "
            f"{exc.strerror or 'error'}); nothing was placed"
        ) from exc


def _seed_existing_worktree(worktree: Path, project_root: Path) -> list[Path]:
    main = _main_checkout_of(worktree)
    _refuse_another_project(main, project_root)
    config = _load_config(main)
    entries = _seed_entries(config)
    if not entries:
        return []
    guard_options = handler_options(config.handlers.pre_tool_use.get(_SECRET_GUARD_KEY))

    def protected_patterns() -> tuple[str, ...]:
        return sfm.protected_patterns_from_options(guard_options)

    try:
        protected_patterns()
    except sfm.ProtectedSetUnreadable as exc:
        raise SeedApplyRefused(
            f"the secret_file_guard options in the config could not be read ({exc}); "
            "nothing was placed"
        ) from exc
    target = worktree.resolve()
    _refuse_redirected_parents(target, entries)
    try:
        validate_seed_sources(main, entries, protected_patterns=protected_patterns)
        refuse_uncommitted_protected_links(main, entries)
        return seed_worktree(
            main,
            target,
            entries,
            audit=LinkAudit(
                log_path=seed_link_audit_path(main),
                protected_patterns=protected_patterns,
                session_id=None,
                verb=SEED_APPLY_VERB,
            ),
        )
    except SeedPlacementError as exc:
        raise SeedApplyRefused(str(exc), placed=exc.placed) from exc
    except WorktreeSeedError as exc:
        raise SeedApplyRefused(str(exc)) from exc
