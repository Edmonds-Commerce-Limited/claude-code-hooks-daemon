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

from pathlib import Path

import yaml

from claude_code_hooks_daemon.config.models import Config, handler_options
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.worktree_seed import SeedEntry, parse_seed_config
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.git_repo import parse_worktree_porcelain, run_git
from claude_code_hooks_daemon.utils.worktree_seeding import (
    LinkAudit,
    WorktreeSeedError,
    seed_link_audit_path,
    seed_worktree,
    validate_seed_sources,
)

#: The audit verb of a link placed by this route, distinct from creation's.
SEED_APPLY_VERB = "seed-worktree"

#: Where the project's daemon config lives, relative to its main checkout.
_CONFIG_RELATIVE = Path(".claude") / "hooks-daemon.yaml"

_HANDLER_KEY = "worktree_create"
_SEED_OPTION = "seed"
_SECRET_GUARD_KEY = "secret_file_guard"


class SeedApplyRefused(RuntimeError):
    """The worktree, the config or a seed entry cannot be honoured; nothing was placed
    unless the message says which entries were."""


def _has_control_character(text: str) -> bool:
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in text)


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
    """The main checkout's daemon config, read STRICTLY: no fallback to defaults."""
    path = main / _CONFIG_RELATIVE
    try:
        return Config.load(path)
    except (OSError, RuntimeError, ValueError, yaml.YAMLError) as exc:
        raise SeedApplyRefused(
            f"the daemon config at {path} could not be loaded ({type(exc).__name__}), "
            "so the seed list cannot be read"
        ) from exc


def _seed_entries(config: Config) -> list[SeedEntry]:
    options = handler_options(config.handlers.worktree_create.get(_HANDLER_KEY))
    return parse_seed_config(options.get(_SEED_OPTION))


def seed_existing_worktree(worktree: Path) -> list[Path]:
    """Place the configured seed entries into the registered ``worktree``.

    Args:
        worktree: A linked worktree of a repository whose main checkout holds a
            daemon config. The only input: nothing here names what to place.

    Returns:
        The destinations created, in configured order; empty when nothing is
        configured or every destination already exists.

    Raises:
        SeedApplyRefused: the worktree is not a registered linked worktree, the
            config cannot be read, an entry is unusable (absent, unsafe, or a
            protected source in copy mode), or a link's audit line could not be
            written (entries placed before it stay placed).
    """
    main = _main_checkout_of(worktree)
    config = _load_config(main)
    entries = _seed_entries(config)
    if not entries:
        return []
    guard_options = handler_options(config.handlers.pre_tool_use.get(_SECRET_GUARD_KEY))

    def protected_patterns() -> tuple[str, ...]:
        return sfm.protected_patterns_from_options(guard_options)

    try:
        validate_seed_sources(main, entries, protected_patterns=protected_patterns)
        return seed_worktree(
            main,
            worktree.resolve(),
            entries,
            audit=LinkAudit(
                log_path=seed_link_audit_path(main),
                protected_patterns=protected_patterns,
                session_id=None,
                verb=SEED_APPLY_VERB,
            ),
        )
    except WorktreeSeedError as exc:
        raise SeedApplyRefused(str(exc)) from exc
