"""Record who created and who touched a branch (Plan 00558 Task 4.2).

After a git command that creates a branch, the creator record
(``hooksDaemonCreator``, ``hooksDaemonCreated``, ``hooksDaemonRoute``) is written
once the ref is confirmed. After a git command that changes the checked-out
branch's history, or a Write/Edit/NotebookEdit, this session and agent are added
to that branch's ``hooksDaemonTouchedBy`` record, once per branch per session.
Both live in git config; see :mod:`core.branch_records`. Silent: every failure is
logged and the call is allowed.
"""

from __future__ import annotations

import logging
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
from claude_code_hooks_daemon.core.branch_records import record_creation, record_touch
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.git_branch_creation import created_branches
from claude_code_hooks_daemon.utils.git_commit_parsing import GitInvocation, git_invocations
from claude_code_hooks_daemon.utils.git_invocation_directory import (
    invocation_directory,
    placement_problem,
)
from claude_code_hooks_daemon.utils.git_repo import GitRepo, run_git

logger = logging.getLogger(__name__)

#: git subcommands that change the checked-out branch's history or position.
TOUCH_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {
        "commit",
        "merge",
        "rebase",
        "cherry-pick",
        "am",
        "revert",
        "reset",
        "switch",
        "checkout",
        "pull",
    }
)

#: File tools and the tool-input field naming the file each one writes.
_FILE_FIELDS: Final[dict[str, str]] = {
    ToolName.WRITE: "file_path",
    ToolName.EDIT: "file_path",
    ToolName.NOTEBOOK_EDIT: "notebook_path",
}


def _current_branch(directory: Path) -> str | None:
    """The branch checked out in ``directory``; None when detached or unreadable."""
    result = run_git(directory, "symbolic-ref", "--quiet", "--short", "HEAD")
    return result.stdout.strip() or None if result.returncode == 0 else None


class BranchTouchRecorderHandler(PostToolUseHandlerBase):
    """Write the creator and touch records of the branches a call created or changed."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BRANCH_TOUCH_RECORDER,
            priority=Priority.BRANCH_TOUCH_RECORDER,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL, HandlerTag.GIT],
        )
        self._untracked_override: Path | None = None

    def _untracked(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    @staticmethod
    def _file_path(hook_input: dict[str, Any]) -> str | None:
        field = _FILE_FIELDS.get(str(hook_input.get(HookInputField.TOOL_NAME)))
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        if field is None or not isinstance(tool_input, dict):
            return None
        value = tool_input.get(field)
        return value if isinstance(value, str) and value else None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A git creation or touch command, or a file write."""
        if hook_input.get(HookInputField.TOOL_NAME) == ToolName.BASH:
            command = get_bash_command(hook_input) or ""
            return bool(created_branches(command)) or any(
                run.subcommand in TOUCH_SUBCOMMANDS for run in git_invocations(command)
            )
        return self._file_path(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Write the records; always a silent allow."""
        allow = BlockingResult(decision=Decision.ALLOW)
        session_id = hook_input.get(HookInputField.SESSION_ID)
        if not isinstance(session_id, str) or not session_id:
            return allow
        raw_agent = hook_input.get(HookInputField.AGENT_ID)
        agent_id = raw_agent if isinstance(raw_agent, str) and raw_agent else None
        file_path = self._file_path(hook_input)
        if file_path is not None:
            self._touch(Path(file_path).parent, session_id, agent_id)
            return allow
        command = get_bash_command(hook_input) or ""
        cwd = Path(str(hook_input.get(HookInputField.CWD) or Path.cwd()))
        for creation in created_branches(command):
            directory = self._directory(creation.invocation, cwd)
            record_creation(
                directory,
                creation.name,
                session_id=session_id,
                agent_id=agent_id,
                route=creation.route,
            )
        for run in git_invocations(command):
            if run.subcommand in TOUCH_SUBCOMMANDS:
                self._touch(self._directory(run, cwd), session_id, agent_id)
        return allow

    @staticmethod
    def _directory(run: GitInvocation, cwd: Path) -> Path:
        return cwd if placement_problem(run, cwd) else invocation_directory(run, cwd)

    def _touch(self, directory: Path, session_id: str, agent_id: str | None) -> None:
        repo = GitRepo.resolve_for(directory)
        if repo is None:
            return
        branch = _current_branch(repo.root)
        if branch is None:
            logger.debug("branch_touch_recorder: %s has no branch checked out", repo.root)
            return
        record_touch(
            repo.root,
            branch,
            session_id=session_id,
            agent_id=agent_id,
            untracked=self._untracked(),
        )

    def get_claude_md(self) -> str | None:
        """The records are read by other guards, so their meaning is worth knowing."""
        return (
            "## branch_touch_recorder — who created and who touched a branch\n\n"
            "After a git command creates a branch, its creator is written to git config: "
            "`branch.<name>.hooksDaemonCreator` (`<session>:<agent>`, agent empty on the "
            "main thread), `hooksDaemonCreated` (unix time) and `hooksDaemonRoute` "
            "(`switch`, `checkout`, `branch`, `worktree`, or `worktree_create` from the "
            "WorktreeCreate event). A branch that already has a creator is never claimed "
            "again. A `commit`, `merge`, `rebase`, `cherry-pick`, `am`, `revert`, `reset`, "
            "`switch`, `checkout` or `pull`, and any Write/Edit/NotebookEdit, adds this "
            "session and agent to the checked-out branch's `hooksDaemonTouchedBy`, once per "
            "branch per session. WorktreeRemove deletes a merged branch only when its route "
            "is `worktree_create` (or, with no record at all, by its `<slug>-<8 hex>` name). "
            "Do not edit these keys by hand. The recorder never blocks.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One test: the records need real refs, which the harness cannot fabricate."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="branch-touch-recorder - a new branch gets a creator record",
                command="Run `git switch -c <new-branch>`, then `git config --get-regexp hooksdaemon`",
                harness_cannot_produce=(
                    "The recorder reads and writes real refs and git config after a real "
                    "branch creation, which the harness's fixture allowlist cannot make. "
                    "Covered by tests/unit/handlers/post_tool_use/test_branch_touch_recorder.py "
                    "and tests/unit/core/test_branch_records.py, which create branches in a "
                    "real repository and assert the creator, route and touch keys."
                ),
                description=(
                    "The config listing shows hooksDaemonCreator, hooksDaemonCreated, "
                    "hooksDaemonRoute=switch and hooksDaemonTouchedBy for the new branch. "
                    "The handler adds no context."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
            )
        ]
