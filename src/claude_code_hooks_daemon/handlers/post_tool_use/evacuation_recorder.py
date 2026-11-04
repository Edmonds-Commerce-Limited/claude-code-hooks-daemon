"""Record each evacuation for the rest of the turn (Plan 00558 Task 4.5).

After a Bash command that copies a worktree's or branch's work to a landing
nothing tracks (``git diff``, ``format-patch``, ``stash show -p`` or ``show``
by redirect, ``tee`` or ``-o``), the worktree toplevel and branches are kept in
the session's spend-ledger state for the current turn; see
:mod:`core.evacuation_turns`. ``destructive_git`` then denies a later command of
the same turn that destroys that work. Silent: the call is always allowed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.evacuation import evacuations
from claude_code_hooks_daemon.core.evacuation_turns import record_evacuations
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.utils import get_bash_command


class EvacuationRecorderHandler(PostToolUseHandlerBase):
    """Keep the evacuations of this turn for destructive_git's same-turn check."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.EVACUATION_RECORDER,
            priority=Priority.EVACUATION_RECORDER,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL, HandlerTag.GIT],
        )
        self._untracked_override: Path | None = None

    def _untracked(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    @staticmethod
    def _cwd(hook_input: dict[str, Any]) -> Path:
        return Path(str(hook_input.get(HookInputField.CWD) or Path.cwd()))

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A Bash command with an evacuation in it."""
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        command = get_bash_command(hook_input) or ""
        return "git" in command and bool(evacuations(command, self._cwd(hook_input)))

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Record the evacuations; always a silent allow."""
        session_id = hook_input.get(HookInputField.SESSION_ID)
        if isinstance(session_id, str) and session_id:
            raw_agent = hook_input.get(HookInputField.AGENT_ID)
            agent_id = raw_agent if isinstance(raw_agent, str) and raw_agent else None
            command = get_bash_command(hook_input) or ""
            record_evacuations(
                self._untracked(),
                session_id,
                agent_id,
                evacuations(command, self._cwd(hook_input)),
            )
        return BlockingResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        """The record gates a later destruction, so its existence is worth knowing."""
        return (
            "## evacuation_recorder — an evacuated worktree or branch stays protected this turn\n\n"
            "After a command copies a worktree's or branch's work to an untracked file "
            "(`git diff`, `format-patch`, `stash show -p` or `show` by redirect, `tee` or "
            "`-o`; a diff, show or format-patch of committed revisions only is not counted), that worktree and branch are remembered for the current turn (the main "
            "thread's turn ends at your next prompt; a sub-agent's is its lifetime). "
            "`destructive_git` denies `worktree remove`, `branch -d/-D`, `update-ref -d` and "
            "`rm -r` of them in a LATER command of the same turn (R-GIT-EVACUATE-THEN-DESTROY). "
            "Commit or push the work on the lane's branch instead. The recorder never blocks.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One test: the record needs real worktrees, which the harness cannot fabricate."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="evacuation-recorder - an evacuating command is allowed silently",
                command="Run `git diff > untracked/acceptance/x.patch` in a linked worktree",
                harness_cannot_produce=(
                    "The recorder reads real worktrees and git state, which the harness's "
                    "fixture allowlist cannot make. Covered by "
                    "tests/unit/handlers/post_tool_use/test_evacuation_recorder.py and "
                    "tests/unit/core/test_evacuation_turns.py."
                ),
                description=(
                    "The call is allowed with no context; the toplevel and branches are "
                    "written to the session's ledger state for this turn."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
            )
        ]
