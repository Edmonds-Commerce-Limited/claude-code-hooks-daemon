"""MergeQaReportHandler — post-hoc plan/docs QA report after a merge (Plan 00373 Phase 3).

``plan_qa_commit_gate``, ``docs_qa_commit_gate`` and ``staged_lint_gate`` all
key on a ``git commit`` Bash command. A ``git merge``, ``git pull`` or
``git rebase`` creates a commit WITHOUT ever invoking ``git commit``, so none
of those three gates ever sees it. Live consequence on this repo: merge
``a85e00e8`` resurrected an archived plan folder with no ``PLAN.md``, and four
plan-QA findings about it went unreported through a full QA run, a green CI
run and a release-slate check — caught only at the NEXT SessionStart sweep.

This handler closes that gap from the other side: it does not try to block a
merge before it runs (the merge's result does not exist until the merge does),
it reports what the merge just brought in, in the same post-hoc idiom
``lint_on_edit`` already uses for a Write/Edit — the write has landed, this is
a failure report to repair, not a rollback.

**Attribution, not a bare re-run of the sweeps.** Running the full plan-QA and
docs-QA sweep catalogues after every merge and reporting everything they find
would re-surface pre-existing drift on every single merge — the noise failure
that gets an advisory ignored. Instead, ``git diff --name-only ORIG_HEAD HEAD``
names exactly what THIS merge/pull/rebase changed (git sets ``ORIG_HEAD`` for
all three), and only a finding attributable to one of those paths is reported.
A finding carrying a path is attributable when a changed path equals it or is
nested under it; a finding with no path (a tree-level check such as
``no-new-collisions``/``stats-recount``) is attributable when the operation
changed anything inside that check's corpus. Silent when nothing moved
(``ORIG_HEAD`` absent, equal to ``HEAD``, or git fails) and silent when nothing
attributable is found — a session's next SessionStart sweep still catches
whatever this handler correctly declines to blame on THIS operation.

Plan QA findings are not uniform about ``Finding.path`` (documented on
``plan_qa.runner._excluded``): a tree-level check carries the bare plan
FOLDER name, a document-level check carries a project-relative path. Both
forms are tried when testing attribution, mirroring that same precedent
rather than inventing a second one. Docs QA findings are uniformly
project-relative.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.docs_qa.context import sweep_context as docs_sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import build_and_save_corpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.report import format_advisory as format_docs_advisory
from claude_code_hooks_daemon.docs_qa.runner import run_stage as run_docs_stage
from claude_code_hooks_daemon.docs_qa.types import CheckStage as DocsCheckStage
from claude_code_hooks_daemon.docs_qa.types import Finding as DocsFinding
from claude_code_hooks_daemon.plan_qa.context import sweep_context as plan_sweep_context
from claude_code_hooks_daemon.plan_qa.report import format_advisory as format_plan_advisory
from claude_code_hooks_daemon.plan_qa.runner import run_stage as run_plan_stage
from claude_code_hooks_daemon.plan_qa.types import Finding as PlanFinding
from claude_code_hooks_daemon.plan_qa.types import Stage as PlanStage
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command
from claude_code_hooks_daemon.utils.command_evasion import (
    ENV_PREFIX,
    GIT_INVOCATION,
    normalise_line_continuations,
)
from claude_code_hooks_daemon.utils.git_repo import GitRepo, run_git
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

_CWD_FIELD: Final[str] = "cwd"

# A newline separates commands exactly as `;` does (same lesson
# `staged_lint_gate`/`verification_result_gate` already encode), and
# `&&`/`||`/`|` each start a new command span within a statement.
_SEGMENT_SEPARATORS: Final[tuple[str, ...]] = ("||", "&&", "|", ";", "\n")

_GIT_MERGE_PULL_REBASE_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^\s*{ENV_PREFIX}{GIT_INVOCATION}(?:merge|pull|rebase)(?=\s|$)"
)

_SWEEP_MODE_ADVISE: Final[str] = "advise"
_MARKDOWN_SUFFIX: Final[str] = ".md"

# Mirrors docs_qa_sweep's index location: rebuilt here too, since this
# handler runs the same SWEEP-stage docs QA catalogue independently of
# whether the SessionStart sweep has run yet this session.
_INDEX_DIR_NAME: Final[str] = "docs-qa"
_INDEX_FILE_NAME: Final[str] = "index.json"

_HEADER: Final[str] = (
    "MERGE QA REPORT: this operation created a commit WITHOUT invoking "
    "`git commit`, so plan_qa_commit_gate/docs_qa_commit_gate/staged_lint_gate "
    "never saw it (Plan 00373). Findings below are only what THIS "
    "merge/pull/rebase introduced -- pre-existing drift is unaffected and "
    "still surfaces at the next SessionStart sweep."
)


def _is_git_merge_pull_rebase_command(command: str) -> bool:
    """Whether any segment of ``command`` is a ``git merge``/``pull``/``rebase``.

    Evasion-resistant via the same fragments `staged_lint_gate` uses: global
    options (`git -C`), an `env`/`VAR=` prefix, and line continuations
    (normalised before segmenting).
    """
    normalised = normalise_line_continuations(command)
    for segment in split_unquoted(normalised, _SEGMENT_SEPARATORS):
        if _GIT_MERGE_PULL_REBASE_PATTERN.search(segment.strip()):
            return True
    return False


def _changed_paths(project_root: Path) -> frozenset[str]:
    """Repo-relative paths ``ORIG_HEAD..HEAD`` touched; empty when unavailable.

    Empty covers every silent case in ONE return: ``ORIG_HEAD`` absent (git
    exits non-zero — unknown revision), git failing outright (also non-zero),
    and ``ORIG_HEAD`` resolving to the same commit as ``HEAD`` (nothing to
    diff, empty stdout). A caller need only check truthiness.
    """
    result = run_git(project_root, "diff", "--name-only", "ORIG_HEAD", "HEAD")
    if result.returncode != 0:
        return frozenset()
    return frozenset(line.strip() for line in result.stdout.splitlines() if line.strip())


def _changed_path_is_or_is_under(candidate: str, changed: frozenset[str]) -> bool:
    """Whether some changed path equals ``candidate`` or is nested under it."""
    normalised = candidate.rstrip("/")
    prefix = normalised + "/"
    return any(path == normalised or path.startswith(prefix) for path in changed)


def _plan_finding_attributable(
    finding: PlanFinding, changed: frozenset[str], plan_dir_rel: str
) -> bool:
    """Whether ``finding`` is attributable to what this operation changed.

    No path (a tree-level check) is attributable when the operation changed
    anything under the plan directory. A path is tried BOTH as given (a
    document-level check's project-relative ``rel_path``) and re-rooted under
    the plan directory (a tree-level check's bare folder name) — the same
    non-uniformity ``plan_qa.runner._excluded`` already documents and handles
    the same way, rather than inventing a second convention for it.
    """
    if finding.path is None:
        return _changed_path_is_or_is_under(plan_dir_rel, changed)
    rerooted = f"{plan_dir_rel.rstrip('/')}/{finding.path}"
    return _changed_path_is_or_is_under(finding.path, changed) or _changed_path_is_or_is_under(
        rerooted, changed
    )


def _docs_finding_attributable(finding: DocsFinding, changed: frozenset[str]) -> bool:
    """Whether ``finding`` is attributable to what this operation changed.

    Docs QA findings carry a uniform project-relative path (unlike plan QA's
    two-shaped ``path``), so no re-rooting is needed. No path (a tree-level
    check) is attributable when the operation touched any markdown file at
    all -- the docs corpus is markdown-scoped by construction.
    """
    if finding.path is None:
        return any(path.endswith(_MARKDOWN_SUFFIX) for path in changed)
    return _changed_path_is_or_is_under(finding.path, changed)


def _plan_qa_cli_hint() -> str:
    """Re-check directive naming the deployed wrapper (mirrors plan_qa_sweep)."""
    return "Full report / re-check: " + daemon_cli_command("plan-qa", "--sweep")


def _docs_qa_cli_hint() -> str:
    """Re-check directive naming the deployed wrapper (mirrors docs_qa_sweep)."""
    return "Full report / re-check: " + daemon_cli_command("docs-qa", "--sweep")


class MergeQaReportHandler(PostToolUseHandlerBase):
    """Post-hoc plan/docs QA report over what a merge/pull/rebase just introduced.

    ADVISORY ONLY: never blocks, never denies, never terminal. Runs the
    plan-QA and docs-QA SWEEP-stage catalogues in process (the same ones the
    SessionStart sweeps run) and reports only the findings attributable to
    ``ORIG_HEAD..HEAD`` — see the module docstring for the attribution rule.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MERGE_QA_REPORT,
            priority=Priority.MERGE_QA_REPORT,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.GIT,
                HandlerTag.PLANNING,
                HandlerTag.DOCUMENTATION,
            ],
        )
        # Injected by the registry for PLANNING-tagged handlers.
        self._track_plans_in_project: str | None = None
        self._plan_qa: Any = None
        # Injected by the registry for DOCUMENTATION-tagged handlers.
        self._documentation: DocumentationPolicy | None = None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        if not self._any_corpus_active():
            return False
        command = get_bash_command(hook_input)
        if not command:
            return False
        return _is_git_merge_pull_rebase_command(command)

    def _any_corpus_active(self) -> bool:
        """Whether either sweep catalogue would actually run.

        Cheap gate before any git subprocess runs: a project with plan QA
        and docs QA both off (or both swept elsewhere) has nothing this
        handler could ever report.
        """
        plan_active = (
            self._track_plans_in_project is not None
            and self._plan_qa is not None
            and self._plan_qa.enabled
            and self._plan_qa.sweep_mode == _SWEEP_MODE_ADVISE
        )
        policy = self._documentation
        docs_active = (
            policy is not None and policy.enabled and policy.qa.sweep_mode == _SWEEP_MODE_ADVISE
        )
        return plan_active or docs_active

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        project_root = ProjectContext.project_root()
        if self._is_foreign_repo(hook_input, project_root):
            return BlockingResult(decision=Decision.ALLOW)

        changed = _changed_paths(project_root)
        if not changed:
            return BlockingResult(decision=Decision.ALLOW)

        sections: list[str] = []
        sections.extend(self._plan_section(project_root, changed))
        sections.extend(self._docs_section(project_root, changed))
        if not sections:
            return BlockingResult(decision=Decision.ALLOW)

        return BlockingResult(decision=Decision.ALLOW, context=[_HEADER, *sections])

    def _plan_section(self, project_root: Path, changed: frozenset[str]) -> list[str]:
        plan_dir_rel = self._track_plans_in_project
        policy = self._plan_qa
        if (
            plan_dir_rel is None
            or policy is None
            or not policy.enabled
            or policy.sweep_mode != _SWEEP_MODE_ADVISE
        ):
            return []
        try:
            context = plan_sweep_context(
                project_root=project_root,
                plan_dir_rel=plan_dir_rel,
                policy=policy,
                today=date.today(),
                layout=self._project_layout,
                exclude_paths=self._project_exclude_paths,
            )
        except FileNotFoundError:
            # The configured plan dir does not exist -- nothing to attribute
            # to this merge; the SessionStart sweep already reports this
            # structurally on its own surface.
            return []
        findings = run_plan_stage(PlanStage.SWEEP, context)
        attributable = [
            finding
            for finding in findings
            if _plan_finding_attributable(finding, changed, plan_dir_rel)
        ]
        if not attributable:
            return []
        return [format_plan_advisory(attributable), _plan_qa_cli_hint()]

    def _docs_section(self, project_root: Path, changed: frozenset[str]) -> list[str]:
        policy = self._documentation
        if policy is None or not policy.enabled or policy.qa.sweep_mode != _SWEEP_MODE_ADVISE:
            return []
        index_path = ProjectContext.daemon_untracked_dir() / _INDEX_DIR_NAME / _INDEX_FILE_NAME
        corpus = build_and_save_corpus(project_root, policy, index_path)
        context = docs_sweep_context(
            project_root=project_root, policy=policy, corpus=corpus, layout=self._project_layout
        )
        findings = run_docs_stage(DocsCheckStage.SWEEP, context)
        attributable = [
            finding for finding in findings if _docs_finding_attributable(finding, changed)
        ]
        if not attributable:
            return []
        return [format_docs_advisory(attributable), _docs_qa_cli_hint()]

    @staticmethod
    def _is_foreign_repo(hook_input: dict[str, Any], project_root: Path) -> bool:
        """True when the command runs inside a repo other than the project's.

        Mirrors `staged_lint_gate._is_foreign_repo`: nested/vendor repos and
        other worktrees own their own history.
        """
        cwd_raw = hook_input.get(_CWD_FIELD)
        if not cwd_raw:
            return False
        repo = GitRepo.resolve_for(Path(cwd_raw))
        return repo is not None and repo.root != project_root

    def get_claude_md(self) -> str | None:
        return (
            "## merge_qa_report — post-hoc plan/docs QA report after a merge\n"
            "\n"
            "`plan_qa_commit_gate`, `docs_qa_commit_gate` and `staged_lint_gate` "
            "all key on a `git commit` Bash command; `git merge`/`git pull`/"
            "`git rebase` create a commit WITHOUT ever invoking `git commit`, so "
            "none of them sees it. This handler runs AFTER such an operation and "
            "reports only the plan-QA/docs-QA findings attributable to "
            "`ORIG_HEAD..HEAD` — what the operation actually introduced, not the "
            "whole tree's pre-existing drift. Silent when nothing moved or "
            "nothing attributable was found; a session's next SessionStart sweep "
            "(`plan_qa_sweep`/`docs_qa_sweep`) still catches everything else.\n"
            "\n"
            "This is a POST-hoc report, in the same idiom as `lint_on_edit`: the "
            "merge has already landed, so the fix is to repair the named finding "
            "and re-check with the printed CLI command, never to try to undo the "
            "merge over this advisory.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="merge-qa-report - reports drift a merge introduces, silent otherwise",
                command=(
                    "On a branch that resurrects an unindexed plan folder (a "
                    "folder with no PLAN.md and no README row), run "
                    "`git merge --no-ff <branch>` on main"
                ),
                harness_cannot_produce=(
                    "This handler reads `git diff --name-only ORIG_HEAD HEAD` "
                    "against the REAL repository, so the precondition is a real "
                    "merge that actually sets `ORIG_HEAD` -- the harness's "
                    "fixture allowlist has no `git merge`, and there is no way "
                    "to fabricate `ORIG_HEAD` without performing one. Covered by "
                    "tests/unit/handlers/post_tool_use/test_merge_qa_report.py, "
                    "which performs real merges against disposable git "
                    "repositories and asserts both that introduced drift is "
                    "reported and that unrelated pre-existing drift stays "
                    "silent."
                ),
                description=(
                    "The PostToolUse context contains a 'MERGE QA REPORT' block "
                    "naming the check id and the resurrected folder; a merge "
                    "that introduces nothing plan/docs-QA-relevant produces no "
                    "context at all."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[
                    r"MERGE QA REPORT|row-folder-bijection|pointer-resolves"
                ],
                safety_notes="Advisory handler — never blocks; revert the test merge after.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
