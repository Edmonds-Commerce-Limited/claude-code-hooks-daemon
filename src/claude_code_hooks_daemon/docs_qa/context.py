"""CheckContext builders for the docs QA surfaces (Plan 00284).

Mirrors :mod:`claude_code_hooks_daemon.plan_qa.context`:

- :func:`edit_context` is HOT-PATH cheap: no filesystem scan — the EDIT
  stage only needs the would-be file content.
- :func:`sweep_context` takes an ALREADY-BUILT :class:`DocCorpus`
  (:func:`docs_qa.corpus.build_and_save_corpus`) — building the corpus is
  the caller's job, so this stays a pure constructor.
- :func:`staged_context` (Task 3.1e) builds the staged-tree view via
  :class:`~claude_code_hooks_daemon.plan_qa.gitfacts.GitFacts` — the SAME
  read-only git plumbing plan_qa's commit gate uses (routed through
  ``run_git``, never a raw subprocess spawn; reused directly rather than
  reimplemented, matching how ``docs_qa.corpus`` already reuses
  ``plan_qa.model.lines_outside_fences``).
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.types import CheckContext
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts

_MARKDOWN_SUFFIX: Final[str] = ".md"
_DELETE_STATUS: Final[str] = "D"


def edit_context(
    project_root: Path,
    policy: DocumentationPolicy,
    file_path: Path,
    file_content: str,
    file_exists_before: bool,
    file_content_before: str | None = None,
    corpus: DocCorpus | None = None,
) -> CheckContext:
    """Build the EDIT-stage context: would-be file content, optionally with a corpus.

    ``corpus`` is optional and only used by checks that need reverse-index
    lookups (``quote-source-stale``); the primary EDIT-stage checks
    (``pointer-resolves``, ``generated-doc-hand-edit``, ``rules-file-shape``,
    ``quote-drift``) never need it — file-existence and quote verification
    both read directly from disk. A caller wanting reverse lookups should
    pass a CHEAP corpus (:func:`docs_qa.corpus.load_or_cold_corpus`), never
    one built inside this call — see the cold-index rule.
    """
    return CheckContext(
        project_root=project_root,
        policy=policy,
        file_path=file_path,
        file_content=file_content,
        file_exists_before=file_exists_before,
        file_content_before=file_content_before,
        corpus=corpus,
    )


def sweep_context(
    project_root: Path,
    policy: DocumentationPolicy,
    corpus: DocCorpus,
) -> CheckContext:
    """Build the SWEEP-stage context from an already-built corpus."""
    return CheckContext(project_root=project_root, policy=policy, corpus=corpus)


def staged_context(
    project_root: Path,
    policy: DocumentationPolicy,
    commit_message: str | None = None,
    pathspecs: Sequence[str] | None = None,
) -> CheckContext:
    """Build the STAGED-stage context: the commit's staged ``.md`` content.

    ``pathspecs`` mirrors :class:`GitFacts`'s own contract: when the
    inspected ``git commit`` invocation names paths directly, the STAGED
    view is scoped to exactly those paths' working-tree-vs-HEAD content
    (what THIS commit will actually contain), not the whole index.
    """
    gitfacts = GitFacts(project_root, pathspecs=pathspecs)
    staged_documents: dict[str, str] = {}
    for change in gitfacts.staged_changes():
        if change.status == _DELETE_STATUS:
            continue
        if not change.path.endswith(_MARKDOWN_SUFFIX):
            continue
        if pathspecs:
            # A pathspec'd commit ships the CURRENT WORKING TREE content of
            # that path (see GitFacts.staged_changes' own docstring) --
            # `git show :path` would read the INDEX instead, which can
            # disagree with what this commit actually contains.
            try:
                content: str | None = (project_root / change.path).read_text(encoding="utf-8")
            except OSError:
                content = None
        else:
            content = gitfacts.staged_file_text(change.path)
        if content is not None:
            staged_documents[change.path] = content
    return CheckContext(
        project_root=project_root,
        policy=policy,
        staged_documents=staged_documents,
        gitfacts=gitfacts,
        commit_message=commit_message,
    )
