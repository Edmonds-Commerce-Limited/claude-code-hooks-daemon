"""CheckContext builders for the docs QA surfaces (Plan 00284).

Mirrors :mod:`claude_code_hooks_daemon.plan_qa.context`:

- :func:`edit_context` is HOT-PATH cheap: no filesystem scan — the EDIT
  stage only needs the would-be file content.
- :func:`sweep_context` takes an ALREADY-BUILT :class:`DocCorpus`
  (:func:`docs_qa.corpus.build_and_save_corpus`) — building the corpus is
  the caller's job, so this stays a pure constructor.
- :func:`staged_context` is a stub: the STAGED (git-commit-gate) surface is
  not implemented in this slice (Plan 00284 Task 3.1a); it raises
  ``NotImplementedError`` so a caller cannot silently no-op on it.
"""

from pathlib import Path
from typing import NoReturn

from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.types import CheckContext


def edit_context(
    project_root: Path,
    policy: DocumentationPolicy,
    file_path: Path,
    file_content: str,
    file_exists_before: bool,
    file_content_before: str | None = None,
) -> CheckContext:
    """Build the EDIT-stage context: would-be file content only."""
    return CheckContext(
        project_root=project_root,
        policy=policy,
        file_path=file_path,
        file_content=file_content,
        file_exists_before=file_exists_before,
        file_content_before=file_content_before,
    )


def sweep_context(
    project_root: Path,
    policy: DocumentationPolicy,
    corpus: DocCorpus,
) -> CheckContext:
    """Build the SWEEP-stage context from an already-built corpus."""
    return CheckContext(project_root=project_root, policy=policy, corpus=corpus)


def staged_context(project_root: Path, policy: DocumentationPolicy) -> NoReturn:
    """STAGED-stage context builder — not implemented in this slice.

    The ``docs-qa --check-staged`` CLI action and the future
    ``docs_qa_commit_gate`` handler both surface this as an explicit "not
    implemented" result rather than calling this and letting it crash
    uncaught.
    """
    raise NotImplementedError(
        "STAGED-stage docs QA context is not implemented in this slice "
        "(Plan 00284 Task 3.1a) — see CLAUDE/Plan/00284-documentation-ssot-"
        "enforcement/PLAN.md Task 3.1e"
    )
