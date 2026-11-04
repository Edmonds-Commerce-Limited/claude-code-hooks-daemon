"""CleanupAfterMergeHandler - delete the branch a merge just landed (Plan 00558 Task 3.1).

After a ``git merge`` into the default branch or an integration line, each
merged LOCAL branch named on the command line is handed to
``core.branch_cleanup.cleanup_after_merge`` under
``branches.cleanup_after_merge.mode``: ``act`` deletes a branch whose every
commit the target now holds and prints its ``git branch <name> <sha>`` restore
line; ``advise`` prints the delete command; ``off`` is silent. A worktree is
never removed here, and a patch-equivalent branch is left to
``branch-sweep --clean``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.branch_cleanup import (
    cleanup_after_merge,
    merge_target_qualifies,
    render,
)
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_commit_parsing import git_invocations
from claude_code_hooks_daemon.utils.git_repo import GitRepo, branch_ref, run_git
from claude_code_hooks_daemon.utils.git_sync import resolve_default_branch
from claude_code_hooks_daemon.utils.merge_scope import (
    is_git_merge_pull_rebase_command,
    merge_directory,
)

logger = logging.getLogger(__name__)

_MERGE: Final[str] = "merge"

#: Options after which no merge was concluded (or none of a kind that keeps ancestry).
_NOT_A_MERGE: Final[frozenset[str]] = frozenset(
    {"--squash", "--abort", "--continue", "--quit", "--no-commit"}
)

#: Merge options whose value is the NEXT word, so it is not a branch operand.
_TAKES_VALUE: Final[frozenset[str]] = frozenset(
    {
        "-m",
        "-s",
        "-X",
        "-F",
        "--message",
        "--strategy",
        "--strategy-option",
        "--file",
        "--cleanup",
        "--into-name",
    }
)

_HEADER: Final[str] = "BRANCH CLEANUP AFTER MERGE:"


def merge_operands(command: str) -> list[str]:
    """The commits named by the first concluding ``git merge`` in ``command``.

    Gated on git sitting in command position, so ``echo git merge x`` is no merge.
    """
    if not is_git_merge_pull_rebase_command(command):
        return []
    for run in git_invocations(command):
        if run.subcommand != _MERGE:
            continue
        if any(word in _NOT_A_MERGE for word in run.arguments):
            return []
        operands: list[str] = []
        skip_next = False
        for word in run.arguments:
            if skip_next:
                skip_next = False
            elif word in _TAKES_VALUE:
                skip_next = True
            elif not word.startswith("-"):
                operands.append(word)
        return operands
    return []


def _current_branch(directory: Path) -> str | None:
    """The branch checked out in ``directory``; None when detached."""
    result = run_git(directory, "symbolic-ref", "--quiet", "--short", "HEAD")
    return result.stdout.strip() or None if result.returncode == 0 else None


def _local_branches(repo: Path, operands: list[str]) -> list[str]:
    """The operands that name a local branch (a sha or remote ref is not cleaned)."""
    return [
        name
        for name in operands
        if run_git(repo, "show-ref", "--verify", "--quiet", branch_ref(name)).returncode == 0
    ]


class CleanupAfterMergeHandler(PostToolUseHandlerBase):
    """Delete or advise deleting the branch a merge into the default just landed."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.CLEANUP_AFTER_MERGE,
            priority=Priority.CLEANUP_AFTER_MERGE,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL, HandlerTag.GIT],
        )
        # Injected by the registry from the top-level `branches:` block.
        self._branches: BranchesConfig = BranchesConfig()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A Bash ``git merge`` that concludes, unless the mode is ``off``."""
        if self._branches.cleanup_after_merge.mode == "off":
            return False
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        command = get_bash_command(hook_input)
        return command is not None and bool(merge_operands(command))

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Clean the merged branches; context lines say what was done and how to undo it."""
        allow = BlockingResult(decision=Decision.ALLOW)
        cwd = hook_input.get(HookInputField.CWD)
        if not cwd:
            return allow
        command = get_bash_command(hook_input) or ""
        directory = merge_directory(command, cwd)
        repo = GitRepo.resolve_for(directory)
        if repo is None:
            return allow
        target = _current_branch(directory)
        default = resolve_default_branch(self._branches, repo.root)
        if default is None or not merge_target_qualifies(target, self._branches, default):
            return allow
        names = _local_branches(repo.root, merge_operands(command))
        if not names or target is None:
            return allow
        try:
            report = cleanup_after_merge(
                repo.root,
                names,
                config=self._branches,
                target=target,
                mode=self._branches.cleanup_after_merge.mode,
            )
        except RuntimeError as exc:
            log_and_continue(
                logger,
                exc,
                reason="a cleanup that cannot read the repository deletes nothing; "
                "the failure is shown so the branch is cleaned by hand",
            )
            return BlockingResult(
                decision=Decision.ALLOW, context=[_HEADER, f"Nothing deleted: {exc}"]
            )
        lines = render(report)
        if not lines:
            return allow
        return BlockingResult(decision=Decision.ALLOW, context=[_HEADER, *lines])

    def get_claude_md(self) -> str | None:
        """The post-merge cleanup is a standing behaviour worth knowing before a merge."""
        return (
            "## cleanup_after_merge — a merged branch is cleaned up after the merge\n\n"
            "After a `git merge` into the default branch or an integration line, each "
            "merged local branch on the command line is handled per "
            "`branches.cleanup_after_merge.mode`: `act` deletes it when the target holds "
            "every commit and prints `git branch <name> <sha>` to restore it; `advise` "
            f"prints the `{daemon_cli_command_for_docs('delete-branch')}` command; `off` is silent. A "
            "branch checked out in a worktree is never removed here (the worktree "
            "removal is printed for you to run), and a patch-equivalent branch is left "
            f"to `{daemon_cli_command_for_docs('branch-sweep', '--clean')}`, which works behind a recovery "
            "bundle. The remote delete is printed, never run.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One test: a real merge is needed, which the harness cannot fabricate."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="cleanup-after-merge - a merged branch is deleted with a restore line",
                command="On the default branch, run `git merge --no-ff <merged-branch>`",
                harness_cannot_produce=(
                    "The handler reads real refs after a real merge, and the harness's "
                    "fixture allowlist has no `git merge`. Covered by "
                    "tests/unit/handlers/post_tool_use/test_cleanup_after_merge.py, which "
                    "merges in a real repository and asserts the delete, the restore line, "
                    "the advise mode and the silent cases."
                ),
                description=(
                    "The PostToolUse context names the deleted branch and the "
                    "`git branch <name> <sha>` restore line (act), or the delete command "
                    "(advise). A merge into a work branch produces no context."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"BRANCH CLEANUP AFTER MERGE"],
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
            )
        ]
