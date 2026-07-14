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
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Protocol

from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.model import README_FILENAME, PlanTree
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex
from claude_code_hooks_daemon.plan_qa.types import CheckContext


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


def _tree_and_readme(
    project_root: Path,
    plan_dir_rel: str,
    policy: QaPolicy,
) -> tuple[PlanTree, ReadmeIndex | None]:
    """Scan the plan tree and parse the index README when present.

    Raises:
        FileNotFoundError: when the configured plan directory is missing —
            FAIL FAST; callers surface it as a structural problem.
    """
    plan_dir = project_root / plan_dir_rel
    tree = PlanTree.scan(
        plan_dir,
        completed_dir=policy.completed_dir,
        cancelled_dir=policy.cancelled_dir,
        extra_root_files=policy.extra_root_files,
    )
    readme_path = plan_dir / README_FILENAME
    readme = ReadmeIndex.parse(readme_path.read_text()) if readme_path.is_file() else None
    return tree, readme


def _with_journal(context: CheckContext, policy: QaPolicy) -> CheckContext:
    """Stamp the flattened journal policy (Plan 00163) onto a built context.

    Kept as one typed helper so all three surfaces thread the six journal
    knobs identically without repetition — ``dataclasses.replace`` type-checks
    each field, so no suppression is needed.
    """
    journal = policy.journal
    return replace(
        context,
        journal_enabled=journal.enabled,
        journal_mode=journal.mode,
        journal_dir_name=journal.dir_name,
        journal_freshness_days=journal.freshness_days,
        journal_enforce_on_completion=journal.enforce_on_completion,
        journal_grandfather_before=journal.grandfather_before,
    )


def sweep_context(
    project_root: Path,
    plan_dir_rel: str,
    policy: QaPolicy,
    today: date,
) -> CheckContext:
    """Build the Stage 3 (SWEEP) context: full tree + readme + git facts."""
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
        ),
        policy,
    )


def staged_context(
    project_root: Path,
    plan_dir_rel: str,
    policy: QaPolicy,
    commit_message: str | None = None,
) -> CheckContext:
    """Build the Stage 2 (COMMIT) context: staged git facts + tree views."""
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
            commit_message=commit_message,
        ),
        policy,
    )


def edit_context(
    project_root: Path,
    plan_dir_rel: str,
    policy: QaPolicy,
    file_path: Path,
    file_content: str,
    file_exists_before: bool,
    file_content_before: str | None = None,
    today: date | None = None,
) -> CheckContext:
    """Build the Stage 1 (EDIT) context: would-be file content only.

    ``file_content_before`` (Plan 00163) is the pre-edit on-disk content the
    surface already read; the append-only journal check consults it so it
    stays a pure function. ``None`` for a creation. ``today`` is supplied by
    the (impure) handler so the day-file-naming check stays deterministic.
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
        ),
        policy,
    )
