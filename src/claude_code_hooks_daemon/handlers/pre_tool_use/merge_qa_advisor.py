"""MergeQaAdvisorHandler - a work branch merged with no recorded green targeted QA run.

Ledger 00474 N278: a branch was merged while its ``llm_qa.py changed`` run was
still queued behind the host-wide QA lock, the coordinator checked only the
touched tests, and ``main`` took three static-check failures. Nothing stopped a
merge that had no recorded pass (Plan 00475 Task 4.2).

``llm_qa.py changed`` records the commit it passed on in
``refs/integration/changed-green/<branch>``. A ref, not the per-tool
``untracked/qa/provenance.json``, because that file is written under the
checkout the run happened in, which for a work branch is its own worktree, not
the checkout the coordinator merges from. Refs are shared by every worktree.

On a Bash ``git merge`` of a work branch (``worktree-*``, local or
``origin/worktree-*``) this resolves the ref to a commit and reads that record.
It is advisory only, and silent when the record names that commit, when the ref
is not a work branch, and on anything it cannot read (fail open: it advises).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Final, NamedTuple

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.handlers.session_start.branch_count_advisor import (
    WORK_BRANCH_PREFIX,
)
from claude_code_hooks_daemon.utils.git_commit_parsing import GitInvocation, git_invocations
from claude_code_hooks_daemon.utils.git_invocation_directory import (
    invocation_directory,
    placement_problem,
)
from claude_code_hooks_daemon.utils.git_repo import HEADS_PREFIX, run_git

logger = logging.getLogger(__name__)

#: The ref ``scripts/qa/llm_qa.py`` writes after a passing run of the whole
#: ``changed`` selection. The script cannot be imported here, so a test pins
#: this to its ``changed_green_ref``.
CHANGED_GREEN_REF_TEMPLATE: Final[str] = "refs/integration/changed-green/{branch}"

_MERGE: Final[str] = "merge"
# `git merge` flags that end or resume a merge rather than start one.
_NOT_A_NEW_MERGE: Final[frozenset[str]] = frozenset({"--abort", "--continue", "--quit"})
# `git merge` options whose value is the NEXT word, so it is not a ref.
_VALUE_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        "-m",
        "-F",
        "-s",
        "-X",
        "--message",
        "--file",
        "--strategy",
        "--strategy-option",
        "--into-name",
        "--cleanup",
    }
)
_OPTION_END: Final[str] = "--"

_REMOTE: Final[str] = "origin"
_REMOTES_PREFIX: Final[str] = f"refs/remotes/{_REMOTE}/"
# A work branch as `git merge` can name it: bare, `refs/heads/`, `origin/` or
# `refs/remotes/origin/`. The prefix is the one branch_count_advisor counts.
_WORK_REF: Final[re.Pattern[str]] = re.compile(
    rf"^(?:(?P<heads>{re.escape(HEADS_PREFIX)})|(?P<remote>(?:refs/remotes/)?{_REMOTE}/))?"
    rf"(?P<branch>{re.escape(WORK_BRANCH_PREFIX)}\S+)$"
)

_SHORT_SHA: Final[int] = 12
_ICON: Final[str] = "🔍"

# CLAUDE/QA.md, "Before Merging: the Coordinator's Check": what to run when the
# targeted result is missing. Each names its scope, because three of them scan
# the whole project and take no file list.
_STATIC_CHECKS: Final[tuple[str, ...]] = (
    "ruff check <touched python files>",
    "black --check --target-version py311 <touched python files>",
    "mypy <touched source files>",
    "python3 scripts/qa/run_pyright_check.py --json",
    "python3 scripts/qa/audit_error_hiding.py",
    "python3 scripts/qa/check_input_contract.py",
    "shellcheck -x <touched shell files>",
    "pytest <the touched tests, by path>",
)


class _WorkRef(NamedTuple):
    """A merged ref that names a work branch: the branch, and its fully-qualified ref."""

    branch: str
    ref: str


def _merged_refs(arguments: tuple[str, ...]) -> list[str]:
    """The refs ``git merge`` is asked to merge: its positional words."""
    refs: list[str] = []
    skip_next = False
    options_ended = False
    for word in arguments:
        if skip_next:
            skip_next = False
        elif options_ended or not word.startswith("-"):
            refs.append(word)
        elif word == _OPTION_END:
            options_ended = True
        elif word in _VALUE_OPTIONS:
            skip_next = True
    return refs


def _work_ref(name: str) -> _WorkRef | None:
    """``name`` as a work branch, or None when it is any other ref."""
    found = _WORK_REF.match(name)
    if found is None:
        return None
    branch = found.group("branch")
    prefix = _REMOTES_PREFIX if found.group("remote") else HEADS_PREFIX
    return _WorkRef(branch, f"{prefix}{branch}")


def _merges(command: str) -> list[GitInvocation]:
    """Each ``git merge`` in ``command`` that starts a merge."""
    return [
        run
        for run in git_invocations(command)
        if run.subcommand == _MERGE and not _NOT_A_NEW_MERGE.intersection(run.arguments)
    ]


def _commit_of(directory: Path, ref: str) -> str | None:
    """The commit ``ref`` names in ``directory``, or None when git cannot say."""
    result = run_git(
        directory,
        "rev-parse",
        "--verify",
        "--quiet",
        f"{ref}^{{commit}}",
        timeout=Timeout.GIT_CONTEXT,
    )
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else None


class MergeQaAdvisorHandler(PreToolUseHandlerBase):
    """Advise the static checks to run before merging a work branch with no recorded green run."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MERGE_QA_ADVISOR,
            priority=Priority.MERGE_QA_ADVISOR,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.GIT,
                HandlerTag.QA_ENFORCEMENT,
                HandlerTag.WORKFLOW,
                HandlerTag.NON_TERMINAL,
            ],
        )

    @staticmethod
    def _cwd(hook_input: dict[str, Any]) -> Path:
        cwd = hook_input.get(HookInputField.CWD)
        if isinstance(cwd, str) and cwd:
            return Path(cwd)
        return ProjectContext.project_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a Bash command that starts a ``git merge``; git is asked in handle()."""
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        command = get_bash_command(hook_input)
        return command is not None and bool(_merges(command))

    def _unrecorded(self, run: GitInvocation, cwd: Path) -> list[tuple[str, str]]:
        """``(branch, head)`` for each merged work branch with no green record at its head."""
        if placement_problem(run) is not None:
            return []
        directory = invocation_directory(run, cwd)
        unrecorded: list[tuple[str, str]] = []
        for name in _merged_refs(run.arguments):
            work = _work_ref(name)
            if work is None:
                continue
            head = _commit_of(directory, work.ref)
            if head is None:
                continue
            recorded = _commit_of(directory, CHANGED_GREEN_REF_TEMPLATE.format(branch=work.branch))
            if recorded != head:
                unrecorded.append((work.branch, head))
        return unrecorded

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Name each merged work branch's head that has no green ``changed`` record."""
        command = get_bash_command(hook_input) or ""
        cwd = self._cwd(hook_input)
        unrecorded: list[tuple[str, str]] = []
        for run in _merges(command):
            unrecorded.extend(self._unrecorded(run, cwd))
        if not unrecorded:
            return GatingResult(decision=Decision.ALLOW)
        return GatingResult(decision=Decision.ALLOW, context=[self._advice(unrecorded)])

    @staticmethod
    def _advice(unrecorded: list[tuple[str, str]]) -> str:
        heads = "\n".join(f"  - {branch} at {head}" for branch, head in unrecorded)
        checks = "\n".join(f"  {check}" for check in _STATIC_CHECKS)
        return (
            f"{_ICON} MERGE WITHOUT A RECORDED TARGETED QA RUN\n\n"
            f"No green `llm_qa.py changed` run is recorded for:\n{heads}\n\n"
            "Merge on the agent's reported commit with a green `changed` on it. With "
            "that result missing, do not merge on trust and do not run the full gate; "
            "run the static checks on the touched files first (CLAUDE/QA.md, "
            "'Before Merging: the Coordinator's Check'), from the project root:\n"
            f"{checks}\n\n"
            "Then `./scripts/qa/llm_qa.py changed` on the merged head. A passing run "
            "on a clean tree records its head, and this advisory goes quiet for it.\n\n"
            "Advisory only - proceeding as requested."
        )

    def get_claude_md(self) -> str | None:
        return (
            "## merge_qa_advisor — merge a work branch with its targeted QA recorded\n\n"
            "A Bash `git merge` of a work branch (`worktree-*`, local or `origin/worktree-*`) "
            "whose head has no recorded green `llm_qa.py changed` run is flagged "
            "(advisory, never blocked). The advisory names the head and the static "
            "checks to run first, from CLAUDE/QA.md, 'Before Merging: the Coordinator's "
            "Check'.\n\n"
            "A passing `changed` run on a clean tree records its head in "
            "`refs/integration/changed-green/<branch>`, which every worktree shares. "
            "Commit before the run: a dirty tree records nothing. Silent when the "
            "record names the head, for any other branch, and when git cannot answer."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return the acceptance test for the merge QA advisor."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        probe = "worktree-acceptance-probe"
        return [
            AcceptanceTest(
                title="merge of a work branch with no recorded green changed run",
                command=f"git merge --no-ff --no-commit {probe}",
                dispatch_as_bash=True,
                description=(
                    "Advises the static checks to run when the merged work branch's head has "
                    "no recorded green `llm_qa.py changed` run. The probe branch is at HEAD, "
                    "so the merge itself is a no-op."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"MERGE WITHOUT A RECORDED", r"llm_qa\.py changed"],
                safety_notes=(
                    "The probe branch points at HEAD, so merging it changes nothing; "
                    "the advisory never blocks"
                ),
                setup_commands=[f"git branch {probe}"],
                cleanup_commands=[f"git branch -d {probe}"],
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
