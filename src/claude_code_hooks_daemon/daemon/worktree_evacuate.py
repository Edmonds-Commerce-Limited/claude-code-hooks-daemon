"""Evacuate a linked worktree's scratch so ``worktree-reap --reap`` can remove it (Plan 00627 Task 6.2).

The only caller is ``cmd_worktree_reap``, and only when every path a removal
would lose is under ``untracked/scratch/``. Root-level entries only; the gate
(:mod:`core.worktree_scratch_evacuation`) refuses a session directory, and
every other hold, before anything is asked.

Order, per worktree: preconditions, GNU tar, one fresh classification and the
all-or-nothing gate, then the typed question at a terminal. Only after a yes
is the main checkout's store opened (opening creates it, so no refusal path
reaches it), and one ``apply_sweep`` runs with expiry off, bound to the consent
decided before the question. Every entry must come back ``archived``;
otherwise the worktree is kept and each archive made is named with its
restore command. The question can wait indefinitely, so every keep predicate
(live processes, work-queue holds, git locks, reapability) is read again after
the answer, before packing, and again with the blockers before removal: only a
worktree nothing keeps reaches ``git worktree remove``.

A TTY does not prove a human (DESIGN.md section 13, F-BYPS F2): this gate has
the same limit as ``scratch-sweep --apply``'s and does not widen it.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import shlex
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from claude_code_hooks_daemon.core.worktree_scratch_evacuation import (
    EvacuationGate,
    evacuation_gate,
)
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.git_repo import GitRepo, parse_worktree_porcelain, run_git
from claude_code_hooks_daemon.utils.path_containment import path_relative_to

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.worktree_reaping import WorktreeState

_LOG = logging.getLogger(__name__)

SCRATCH_PREFIX: Final[str] = "untracked/scratch/"
_SCRATCH_RELATIVE: Final[str] = "untracked/scratch"
_KEEP: Final[str] = "KEEP   "
#: A leftover claim is done when removed after its archive, or renamed back
#: (then judged again, and required to be archived, as an entry).
_RESUME_DONE: Final[frozenset[str]] = frozenset({"removed", "renamed-back"})

Confirm = Callable[[str, EvacuationGate], bool]


@dataclass(frozen=True)
class EvacuateSeams:
    """Test seams; the defaults are the real terminal, clock, processes and git."""

    confirm: Confirm | None = None
    wall_clock: Callable[[], float] = time.time
    #: Must be non-empty when given: an empty map reads as "liveness unknown".
    process_cwds: Callable[[], Mapping[int, Path]] | None = None
    git_runner: Callable[..., Any] | None = None
    tar_path: str | None = None
    #: ``apply_sweep``'s crash seam: called after each claim, pack and record append.
    after_step: Callable[[str, str], None] | None = None


@dataclass(frozen=True)
class Evacuation:
    """``evacuated`` only when every entry was archived; ``lines`` are printed as given."""

    evacuated: bool
    lines: tuple[str, ...]


def only_scratch(blockers: Sequence[str]) -> bool:
    """True when there are blockers and every one is the scratch root or under it."""
    return bool(blockers) and all(
        blocker == SCRATCH_PREFIX or blocker.startswith(SCRATCH_PREFIX) for blocker in blockers
    )


def human_command(name: str) -> str:
    """The command a human runs at a terminal to evacuate and reap ``name``.

    The builder joins words with spaces and quotes nothing, and the line is
    pasted into a shell, so the outside name is quoted here.
    """
    return daemon_cli_command_for_docs("worktree-reap", "--reap", "--only", shlex.quote(name))


def confirm_evacuate_interactively(
    relative_worktree: str,
    gate: EvacuationGate,
    *,
    stdin: Any = None,
    stdout: Any = None,
    prompt_stream: Any = None,
) -> bool:
    """True only when a human at a terminal types ``evacuate <relative_worktree>``.

    The rules of ``confirm_apply_interactively``: both stdin and stdout must be
    terminals; end of input, any other text or a non-terminal stream is a
    refusal. No flag, variable, file or config key stands in for it.
    """
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    prompt_stream = prompt_stream if prompt_stream is not None else sys.stderr
    if not (stdin.isatty() and stdout.isatty()):
        return False
    phrase = f"evacuate {relative_worktree}"
    verdicts = ", ".join(f"{verdict} {count}" for verdict, count in gate.by_verdict)
    prompt_stream.write(
        f"worktree-reap --reap evacuates the scratch of {relative_worktree}: "
        f"{gate.entries} entries ({gate.not_due} not yet due; {verdicts}) are archived "
        "into the main checkout's store, each printed with its restore command, and the "
        "worktree is then removed.\n"
        f"Type '{phrase}' to go ahead: "
    )
    prompt_stream.flush()
    return bool(stdin.readline().strip() == phrase)


def evacuate_scratch(
    main: Path,
    state: WorktreeState,
    *,
    reap: bool,
    seams: EvacuateSeams | None = None,
    recheck: Callable[[], str | None] | None = None,
) -> Evacuation:
    """Evacuate ``state``'s scratch root into ``main``'s store, or say why not.

    ``recheck`` runs after a yes and before anything is packed: the question
    waits as long as the human takes, so the caller's keep predicates are read
    again, and any reason it returns keeps the scratch untouched.
    """
    seams = seams or EvacuateSeams()
    name = state.name

    def keep(*reasons: str) -> Evacuation:
        return Evacuation(False, tuple(f"{_KEEP} {name}: evacuation refused: {r}" for r in reasons))

    refusal, relative = _precondition_refusal(main, state.path, seams)
    if refusal:
        return keep(refusal)
    from claude_code_hooks_daemon.config.models import Config
    from claude_code_hooks_daemon.core.untracked_roots import resolve_sweep_root

    worktree = state.path
    config = Config.load_or_default(main / ".claude" / "hooks-daemon.yaml")
    root = worktree / "untracked" / "scratch"
    sweep_root = resolve_sweep_root(
        root,
        project_root=worktree,
        config=config.scratch,
        reference_roots=tuple(config.reference_repos.roots),
    )
    if sweep_root.refusal or sweep_root.apply_refusal:
        return keep(str(sweep_root.refusal or sweep_root.apply_refusal))
    if sweep_root.ttl_hours is None:
        return keep(f"{root} is never cleared by TTL; a human moves it")
    tar = None
    if reap:
        from claude_code_hooks_daemon.core.scratch_archive_pack import PackRefused, find_gnu_tar

        try:
            tar = find_gnu_tar(seams.tar_path)
        except PackRefused as exc:
            return keep(str(exc))
    sources = _sources(main, worktree, config, seams)
    report = sources.classify(sweep_root)
    gate = evacuation_gate(
        report, ttl_hours=float(sweep_root.ttl_hours), max_inodes=sources.max_inodes
    )
    if gate.blockers:
        return keep(*gate.blockers)
    names = ", ".join(row.name for row in report.rows)
    if not reap or tar is None:
        return Evacuation(
            False,
            (
                f"OFFER   {name}: --reap at a terminal asks to archive {gate.entries} scratch "
                f"entries ({gate.not_due} not yet due) into the main checkout's store: {names}",
            ),
        )
    if not (seams.confirm or confirm_evacuate_interactively)(relative, gate):
        return keep(
            "no typed confirmation at a terminal (stdin and stdout both a TTY); nothing was "
            f"changed; a human runs `{human_command(name)}`"
        )
    changed = recheck() if recheck is not None else None
    if changed:
        return keep(f"after the answer: {changed}; nothing was changed")
    return _pack(sources, sweep_root, gate, tar, name, seams.after_step)


def _precondition_refusal(main: Path, worktree: Path, seams: EvacuateSeams) -> tuple[str, str]:
    """``(refusal, worktree path relative to main)``; the refusal is "" when every check holds."""
    found = GitRepo.resolve_for(main)
    if (
        not (main / ".git").is_dir()
        or found is None
        or found.main_worktree_root().resolve() != main.resolve()
    ):
        return f"{main} is not the main checkout; evacuation runs from there only", ""
    listing = (seams.git_runner or run_git)(main, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return f"git worktree list failed: {listing.stderr.strip()}", ""
    records = [
        record
        for record in parse_worktree_porcelain(listing.stdout)
        if record.path.resolve() == worktree.resolve()
    ]
    if len(records) != 1 or worktree.resolve() == main.resolve():
        return f"{worktree} is not one registered linked worktree of {main}", ""
    if records[0].prunable or records[0].locked:
        return f"{worktree} is prunable or locked", ""
    try:
        relative = path_relative_to(worktree.resolve(), main.resolve()).as_posix()
    except ValueError:
        return f"{worktree} is not inside {main}, so it has no phrase to type", ""
    root = worktree / "untracked" / "scratch"
    if (worktree / "untracked").is_symlink() or root.is_symlink() or not root.is_dir():
        return f"{root} is not a real directory", ""
    return "", relative


def _sources(main: Path, worktree: Path, config: Any, seams: EvacuateSeams) -> Any:
    """The worktree's facts, reading the background records of BOTH checkouts."""
    from claude_code_hooks_daemon.daemon.cli import (
        SCRATCH_SWEEP_DEFAULT_MAX_INODES,
        SCRATCH_SWEEP_DEFAULT_SECONDS,
        _ScratchSources,
    )

    main_sources = _ScratchSources(
        repo=main,
        config=config,
        budget_seconds=SCRATCH_SWEEP_DEFAULT_SECONDS,
        max_inodes=SCRATCH_SWEEP_DEFAULT_MAX_INODES,
        scandir=os.scandir,
        wall_clock=seams.wall_clock,
        budget_clock=time.monotonic,
        process_cwds=seams.process_cwds,
        git_runner=seams.git_runner,
        store_checkout=main,
    )
    return dataclasses.replace(
        main_sources, repo=worktree, extra_background=(main_sources.background_file,)
    )


def _pack(
    sources: Any,
    sweep_root: Any,
    gate: EvacuationGate,
    tar: Any,
    name: str,
    after_step: Callable[[str, str], None] | None,
) -> Evacuation:
    """One ``apply_sweep`` under the main store's lock, bound to ``gate.consent``."""
    from claude_code_hooks_daemon.core.scratch_archive import (
        ArchiveStore,
        StoreBusy,
        StoreRefused,
    )
    from claude_code_hooks_daemon.core.scratch_archive_apply import (
        ApplyFacts,
        ApplySettings,
        apply_sweep,
    )
    from claude_code_hooks_daemon.core.scratch_archive_facts import LazyReferences, entry_in_use
    from claude_code_hooks_daemon.core.scratch_references import build_references

    resolved = Path(sweep_root.path).resolve()

    def entry_live(entry: str) -> bool:
        return entry_in_use(
            entry,
            root=resolved,
            relative_root=_SCRATCH_RELATIVE,
            reading=sources.cwds(),
            background=sources.background(),
        )

    facts = ApplyFacts(
        classify=lambda: sources.classify(sweep_root),
        entry_live=entry_live,
        referenced=LazyReferences(
            lambda: build_references(sources.project_git(), _SCRATCH_RELATIVE)
        ),
    )
    settings = ApplySettings(
        root=Path(sweep_root.path),
        original_prefix=_SCRATCH_RELATIVE,
        checkout=str(sources.repo.resolve()),
        tar=tar,
        max_inodes=sources.max_inodes,
        retention_hours=sources.retention_hours(),
        clock=sources.now,
        empty_session_hours=None,
        pressure=gate.consent,
        expire=False,
    )
    try:
        with ArchiveStore.open(sources.store_path) as store, store.lock():
            if after_step is None:
                result = apply_sweep(store, facts, settings)
            else:
                result = apply_sweep(store, facts, settings, after_step=after_step)
    except (StoreRefused, StoreBusy, OSError) as exc:
        _LOG.warning("worktree-reap: evacuation of %s refused: %s", name, exc)
        return Evacuation(False, (f"{_KEEP} {name}: evacuation refused: {exc}",))
    restore = daemon_cli_command_for_docs("scratch-sweep", "restore")
    # A killed earlier run's claim is listed as a row and finished by resume, not
    # in ``entries``: once removed it is archived; renamed back, it is an entry again.
    finished = [
        (resumed.name, resumed.removed.archive_id)
        for resumed in result.resumed
        if resumed.outcome == "removed" and resumed.removed is not None
    ]
    archived = finished + [
        (outcome.name, outcome.archive_id) for outcome in result.entries if outcome.archive_id
    ]
    lines = [
        f"ARCHIVED {name}: {entry} archive {archive_id}; restore it from the "
        f"main checkout with `{restore} {shlex.quote(archive_id)}`"
        for entry, archive_id in archived
    ]
    unfinished = [
        f"{outcome.name}: {outcome.outcome}" + (f" ({outcome.reason})" if outcome.reason else "")
        for outcome in result.entries
        if outcome.outcome != "archived"
    ] + [
        f"{resumed.name}: leftover claim {resumed.outcome}"
        + (f" ({resumed.reason})" if resumed.reason else "")
        for resumed in result.resumed
        if resumed.outcome not in _RESUME_DONE
    ]
    if not result.complete:
        unfinished.append("run incomplete: " + "; ".join(result.incomplete_reasons))
    acted = len(result.entries) + len(finished)
    if acted < gate.entries:
        unfinished.append(f"{gate.entries - acted} entries were not acted on")
    lines.extend(f"{_KEEP} {name}: evacuation refused: {reason}" for reason in unfinished)
    return Evacuation(not unfinished, tuple(lines))
