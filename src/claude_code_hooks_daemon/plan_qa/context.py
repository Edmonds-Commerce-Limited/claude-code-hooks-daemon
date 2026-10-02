"""CheckContext builders for the three plan QA surfaces (Plan 00144).

The daemon config model (``PlanWorkflowQaConfig``) is duck-typed here via
:class:`QaPolicy` so this package keeps zero pydantic/daemon coupling — any
object carrying the policy field names works (the real config model, a test
stand-in, or plain values loaded elsewhere).

Surface cost profile:

- :func:`edit_context` is HOT-PATH cheap: no filesystem scan, no git
  subprocess — Stage 1 checks only need the would-be file content.
- :func:`staged_context` / :func:`sweep_context` scan the plan tree, parse
  the README, and construct :class:`GitFacts` — acceptable for commit gates
  and session sweeps, never for per-edit dispatch.

Which tree a surface judges (ledger 00474 N244, N245): the sweep and the edit
read the DISK; a bare ``git commit`` reads the INDEX, because the commit
records the index and a gate that read the disk would judge a tree no commit
holds. Not covered, and read from the disk as before: the pathspec and
``--include`` forms (they record working-tree content over the index),
operations the same command performs before committing
(``git add x && git commit``), ``git commit -a``, and the checks that open
files themselves rather than asking the tree (``path-existence``,
``plan-doc-size``, ``journal-entry-ordering``, ``same-commit-plan-doc``, and
the journal day-file lookups in ``checks/common.py``).
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.model import PLAN_DOC_FILENAME, README_FILENAME, PlanTree
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex
from claude_code_hooks_daemon.plan_qa.tree_view import DiskTreeView, IndexTreeView, TreeView
from claude_code_hooks_daemon.plan_qa.types import CheckContext, PlanDocSizeLimits
from claude_code_hooks_daemon.utils.authored_paths import authored_path
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to, path_relative_to

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.project_layout import ProjectLayout


class JournalPolicy(Protocol):
    """Structural view of the journal policy (mirrors PlanWorkflowQaJournalConfig)."""

    @property
    def enabled(self) -> bool: ...

    @property
    def mode(self) -> str: ...

    @property
    def dir_name(self) -> str: ...

    @property
    def freshness_days(self) -> int: ...

    @property
    def enforce_on_completion(self) -> bool: ...

    @property
    def grandfather_before(self) -> int: ...

    @property
    def today_only_mode(self) -> str: ...


class PlanDocSizePolicy(Protocol):
    """Structural view of the plan-doc size policy (Plan 00190)."""

    @property
    def enabled(self) -> bool: ...

    @property
    def advisory_bytes(self) -> int: ...

    @property
    def advisory_lines(self) -> int: ...

    @property
    def warning_bytes(self) -> int: ...

    @property
    def warning_lines(self) -> int: ...

    @property
    def block_bytes(self) -> int: ...

    @property
    def block_lines(self) -> int: ...


class QaPolicy(Protocol):
    """Structural view of the plan QA policy (mirrors PlanWorkflowQaConfig)."""

    @property
    def completed_dir(self) -> str: ...

    @property
    def cancelled_dir(self) -> str | None: ...

    @property
    def require_terminal_date(self) -> bool: ...

    @property
    def staleness_days(self) -> int: ...

    @property
    def legacy_plan_allowlist(self) -> Sequence[int]: ...

    @property
    def collision_allowlist(self) -> Sequence[int]: ...

    @property
    def extra_root_files(self) -> Sequence[str]: ...

    @property
    def journal(self) -> JournalPolicy: ...

    @property
    def plan_doc_size(self) -> PlanDocSizePolicy: ...


def _normalised_exclude_paths(exclude_paths: Sequence[str] | None) -> tuple[str, ...]:
    """The project-wide ``daemon.exclude_paths`` as the tuple the context carries.

    Plan 00362 Task 2.9. The tree and README views are deliberately NOT
    filtered by it: removing a folder the index still lists would make the
    cross-file checks report the index as wrong (a row with no folder, a
    statistics block that no longer recounts). The exclusion is applied by
    :func:`plan_qa.runner.run_stage` to the FINDINGS instead, so an excluded
    plan is never reported on while every whole-tree invariant still sees
    the tree as it is.
    """
    return () if exclude_paths is None else tuple(exclude_paths)


def _committed_view(
    project_root: Path, plan_dir: Path, policy: QaPolicy, gitfacts: GitFacts
) -> TreeView | None:
    """The plan directory as the commit will record it, or ``None`` if git cannot say.

    Ledger 00474 N244. Two git spawns however many plan folders there are: one
    ``ls-files -s`` for the listing, one ``cat-file --batch`` for every document
    the scan parses (each ``PLAN.md`` and the two index READMEs).

    ``None`` is an unreadable index, and the caller keeps reading the disk, as it
    did before this view existed: fail-open stays fail-open.
    """
    if not path_is_relative_to(plan_dir, project_root):
        return None
    prefix = path_relative_to(plan_dir, project_root).as_posix()
    listing = gitfacts.index_listing(prefix)
    if listing is None:
        return None
    index_readmes = {
        f"{prefix}/{README_FILENAME}",
        f"{prefix}/{policy.completed_dir}/{README_FILENAME}",
    }
    wanted = [
        path
        for path in listing
        if path.rsplit("/", 1)[-1] == PLAN_DOC_FILENAME or path in index_readmes
    ]
    texts = gitfacts.index_texts(listing, wanted)
    if texts is None:
        return None
    # Git cannot record an empty directory, so an archive directory a project
    # keeps empty until its first plan is archived is in no listing. It is the
    # plan directory's own structure, not a plan, and no commit could add it
    # without a placeholder file: keep it where the disk has it.
    archive_dirs = [
        authored_path(plan_dir, name)
        for name in (policy.completed_dir, policy.cancelled_dir)
        if name is not None
    ]
    return IndexTreeView(
        files=[project_root / path for path in listing],
        texts={project_root / path: text for path, text in texts.items()},
        empty_dirs=[directory for directory in archive_dirs if directory.is_dir()],
    )


def _tree_and_readme(
    project_root: Path,
    plan_dir_rel: str,
    policy: QaPolicy,
    committed_from: GitFacts | None = None,
) -> tuple[PlanTree, ReadmeIndex | None]:
    """Scan the plan tree and parse the index README when present.

    ``committed_from`` makes the scan read the INDEX through that
    :class:`GitFacts` instead of the disk (ledger 00474 N244): the commit gate
    judges the tree the commit will record. ``None`` reads the disk, which is
    right for a sweep, and is what a commit gate falls back to when git cannot
    produce the listing.

    Raises:
        FileNotFoundError: when the configured plan directory is missing —
            FAIL FAST; callers surface it as a structural problem. For a
            committed view that means the commit records nothing under it.
    """
    # Normalised, NOT contained, and the difference is deliberate. Containment
    # is used where a "not there" branch already exists to fall into (the
    # corpus trees, the journal dirs); here there is none, so refusing an
    # escaping plan dir would mean INVENTING a failure behaviour for a
    # misconfigured tree -- a decision that belongs with the wider
    # config-validation question, not smuggled into a path-hygiene pass.
    plan_dir = authored_path(project_root, plan_dir_rel)
    view: TreeView | None = (
        _committed_view(project_root, plan_dir, policy, committed_from)
        if committed_from is not None
        else None
    )
    if view is None:
        view = DiskTreeView()
    tree = PlanTree.scan(
        plan_dir,
        completed_dir=policy.completed_dir,
        cancelled_dir=policy.cancelled_dir,
        extra_root_files=policy.extra_root_files,
        view=view,
    )
    readme_path = authored_path(plan_dir, README_FILENAME)
    readme = ReadmeIndex.parse(view.read_text(readme_path)) if view.is_file(readme_path) else None

    # Plan 00310: aged-out completed rows live verbatim in an archive index
    # inside the completed dir (CLAUDE/Plan/Completed/README.md). Merge its
    # rows into the primary ReadmeIndex so row-folder-bijection (and any
    # other check keyed on ``readme.rows``/``readme.numbers()``) still sees
    # them — otherwise every archived plan reads as unindexed the moment its
    # row ages out of the main file. Stats and ``lines`` stay sourced from
    # the PRIMARY file only: those drive checks (index-row-length,
    # stats-recount) that are about the primary index's own text/counts, not
    # the union of both files. Archive row links are relative to the
    # completed dir, not ``plan_dir`` — rewritten here so link resolution
    # (relative to ``plan_dir``) still finds the real folder.
    archive_path = authored_path(plan_dir, f"{policy.completed_dir}/{README_FILENAME}")
    if readme is not None and view.is_file(archive_path):
        archive_readme = ReadmeIndex.parse(view.read_text(archive_path))
        rewritten_rows = tuple(
            replace(row, link=f"{policy.completed_dir}/{row.link}") if row.link else row
            for row in archive_readme.rows
        )
        readme = replace(readme, rows=readme.rows + rewritten_rows)

    return tree, readme


def _with_journal(context: CheckContext, policy: QaPolicy) -> CheckContext:
    """Stamp the journal (Plan 00163) and size (Plan 00190) policy onto a context.

    Kept as one typed helper so all three surfaces thread these knobs
    identically without repetition — ``dataclasses.replace`` type-checks each
    field, so no suppression is needed.
    """
    journal = policy.journal
    size = policy.plan_doc_size
    return replace(
        context,
        journal_enabled=journal.enabled,
        journal_mode=journal.mode,
        journal_dir_name=journal.dir_name,
        journal_freshness_days=journal.freshness_days,
        journal_enforce_on_completion=journal.enforce_on_completion,
        journal_grandfather_before=journal.grandfather_before,
        journal_today_only_mode=journal.today_only_mode,
        plan_doc_size=PlanDocSizeLimits(
            enabled=size.enabled,
            advisory_bytes=size.advisory_bytes,
            advisory_lines=size.advisory_lines,
            warning_bytes=size.warning_bytes,
            warning_lines=size.warning_lines,
            block_bytes=size.block_bytes,
            block_lines=size.block_lines,
        ),
    )


def sweep_context(
    project_root: Path,
    plan_dir_rel: str,
    policy: QaPolicy,
    today: date,
    layout: "ProjectLayout | None" = None,
    exclude_paths: Sequence[str] | None = None,
) -> CheckContext:
    """Build the Stage 3 (SWEEP) context: full tree + readme + git facts.

    ``layout`` (Plan 00288) is threaded straight through when the calling
    surface has a :class:`~claude_code_hooks_daemon.core.project_layout.ProjectLayout`
    available -- no check consults it yet (consumption refactors are later
    plan tasks), this only makes it AVAILABLE on the context.
    ``exclude_paths`` is the project-wide ``daemon.exclude_paths`` (Plan
    00362 Task 2.9); the runner drops every finding about an excluded path.
    """
    excluded = _normalised_exclude_paths(exclude_paths)
    tree, readme = _tree_and_readme(project_root, plan_dir_rel, policy)
    return _with_journal(
        CheckContext(
            project_root=project_root,
            plan_dir_rel=plan_dir_rel,
            completed_dir=policy.completed_dir,
            cancelled_dir=policy.cancelled_dir,
            require_terminal_date=policy.require_terminal_date,
            staleness_days=policy.staleness_days,
            legacy_plan_allowlist=frozenset(policy.legacy_plan_allowlist),
            collision_allowlist=frozenset(policy.collision_allowlist),
            tree=tree,
            readme=readme,
            gitfacts=GitFacts(project_root),
            today=today,
            layout=layout,
            exclude_paths=excluded,
        ),
        policy,
    )


def staged_context(
    project_root: Path,
    plan_dir_rel: str,
    policy: QaPolicy,
    commit_message: str | None = None,
    pathspecs: Sequence[str] | None = None,
    layout: "ProjectLayout | None" = None,
    exclude_paths: Sequence[str] | None = None,
    include: bool = False,
    directory: Path | None = None,
    extra_directories: Sequence[Path] = (),
) -> CheckContext:
    """Build the Stage 2 (COMMIT) context: staged git facts + tree views.

    Args:
        directory: Where the commit's pathspecs are read from (ledger 00474
            N299: ``cd sub && git commit f.txt`` names ``sub/f.txt``); the
            project root when omitted.
        extra_directories: The other directories the command may have run in
            (a ``cd`` that may not have taken effect); what the pathspecs name
            in any of them is judged.
        pathspecs: The commit's explicit pathspec arguments, when the
            inspected ``git commit`` invocation names paths directly
            (``git commit <pathspec>...``). Threaded straight into
            :class:`GitFacts` so ``staged_changes()`` reflects what THIS
            commit will actually contain — the working tree for those
            paths, not just the index. ``None`` (a bare commit) preserves
            the original index-based behaviour.
        layout: Optional ProjectLayout facade (Plan 00288), made AVAILABLE
            on the context; no check consults it yet.
        exclude_paths: The project-wide ``daemon.exclude_paths`` (Plan 00362
            Task 2.9); the runner drops every finding about an excluded path.
        include: ``git commit --include <pathspec>...``: the commit records
            the index with the named paths' working-tree content laid over it,
            not HEAD with them replaced. Meaningful only with ``pathspecs``.
    """
    excluded = _normalised_exclude_paths(exclude_paths)
    gitfacts = GitFacts(
        project_root,
        pathspecs=pathspecs,
        include=include,
        directory=directory,
        extra_directories=extra_directories,
    )
    # A bare commit records the INDEX, so the tree is read from it. A
    # `git commit <pathspec>` (or `--include`) records the WORKING-TREE content
    # of the named paths, which no listing of the index describes, so those
    # forms read the disk (see the module note on what is not covered).
    tree, readme = _tree_and_readme(
        project_root, plan_dir_rel, policy, committed_from=None if pathspecs else gitfacts
    )
    return _with_journal(
        CheckContext(
            project_root=project_root,
            plan_dir_rel=plan_dir_rel,
            completed_dir=policy.completed_dir,
            cancelled_dir=policy.cancelled_dir,
            require_terminal_date=policy.require_terminal_date,
            staleness_days=policy.staleness_days,
            legacy_plan_allowlist=frozenset(policy.legacy_plan_allowlist),
            collision_allowlist=frozenset(policy.collision_allowlist),
            tree=tree,
            readme=readme,
            gitfacts=gitfacts,
            commit_message=commit_message,
            layout=layout,
            exclude_paths=excluded,
        ),
        policy,
    )


def edit_context(
    project_root: Path,
    plan_dir_rel: str,
    policy: QaPolicy,
    file_path: Path,
    file_content: str,
    file_exists_before: bool | None,
    file_content_before: str | None = None,
    today: date | None = None,
    layout: "ProjectLayout | None" = None,
    exclude_paths: Sequence[str] | None = None,
) -> CheckContext:
    """Build the Stage 1 (EDIT) context: would-be file content only.

    ``file_content_before`` (Plan 00163) is the pre-edit on-disk content the
    surface already read; the append-only journal check consults it so it
    stays a pure function. ``None`` for a creation. ``today`` is supplied by
    the (impure) handler so the day-file-naming check stays deterministic.
    ``layout`` (Plan 00288) is optional and made AVAILABLE on the context;
    no check consults it yet. ``exclude_paths`` is the project-wide
    ``daemon.exclude_paths`` (Plan 00362 Task 2.9); the runner runs no check
    at all when ``file_path`` is excluded.
    """
    return _with_journal(
        CheckContext(
            project_root=project_root,
            plan_dir_rel=plan_dir_rel,
            completed_dir=policy.completed_dir,
            cancelled_dir=policy.cancelled_dir,
            require_terminal_date=policy.require_terminal_date,
            staleness_days=policy.staleness_days,
            legacy_plan_allowlist=frozenset(policy.legacy_plan_allowlist),
            collision_allowlist=frozenset(policy.collision_allowlist),
            file_path=file_path,
            file_content=file_content,
            file_exists_before=file_exists_before,
            file_content_before=file_content_before,
            today=today,
            layout=layout,
            exclude_paths=_normalised_exclude_paths(exclude_paths),
        ),
        policy,
    )
