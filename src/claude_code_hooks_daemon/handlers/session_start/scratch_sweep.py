"""ScratchSweepHandler - the session's scratch directory at SessionStart (Plan 00627).

DESIGN.md section 7: each session works in its own directory under the scratch
root of the checkout it starts in, ``untracked/scratch/s-<UTC>-<sid8>/``, with a
daemon-written manifest recording the session id, birth, checkout and branch.
This handler creates it (idempotent per session id, so resume and compact reuse
it) and announces it as "your scratch directory", with the ``scratch new``
command that makes a recorded entry inside it.

It fires on every source because a compaction drops the earlier announcement.
It never raises and never blocks: a failure to create the directory is said in
one line, and an unusable session id is silent. Section 10 names this ONE
handler for the scratch summary too; Task 5.2 adds that report here.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.scratch_session import (
    SessionError,
    check_session_id,
    ensure_session_dir,
)
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.git_repo import GitRepo
from claude_code_hooks_daemon.utils.git_sync import current_branch
from claude_code_hooks_daemon.utils.scratch_dir import ensure_scratch_dir

logger = logging.getLogger(__name__)

_ICON = "🗒️"


class ScratchSweepHandler(SessionStartHandlerBase):
    """Create and announce this session's scratch directory."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SCRATCH_SWEEP,
            priority=Priority.SCRATCH_SWEEP,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL, HandlerTag.WORKFLOW],
        )

    def _get_project_root(self) -> Path:
        try:
            return ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; using cwd for the scratch directory")
            return Path.cwd()

    def _checkout(self, hook_input: dict[str, Any]) -> Path:
        """The checkout the session starts in: its cwd's worktree of THIS project, else the project root."""
        project_root = self._get_project_root()
        cwd = hook_input.get(HookInputField.CWD)
        if not isinstance(cwd, str) or not cwd:
            return project_root
        found = GitRepo.resolve_for(Path(cwd))
        project = GitRepo.resolve_for(project_root)
        if found is None or project is None:
            return project_root
        if found.main_worktree_root().resolve() != project.main_worktree_root().resolve():
            return project_root
        return found.root

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every source: compact drops the earlier announcement."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Create the directory if absent and say where it is; one line on failure."""
        session_id = hook_input.get(HookInputField.SESSION_ID)
        if not isinstance(session_id, str):
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        try:
            check_session_id(session_id)
        except SessionError:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        checkout = self._checkout(hook_input)
        try:
            ensure_scratch_dir(checkout)
            made = ensure_session_dir(
                checkout / ProjectPath.SCRATCH_DIR,
                session_id,
                now=datetime.now(UTC),
                checkout=str(checkout),
                branch=current_branch(checkout),
            )
        except (SessionError, OSError) as exc:
            reason = str(exc) if isinstance(exc, SessionError) else type(exc).__name__
            logger.info("scratch session directory not created: %s", reason)
            return AdvisoryResult(
                decision=Decision.ALLOW,
                context=[f"{_ICON} Scratch session directory not created: {reason}"],
            )
        command = daemon_cli_command_for_docs("scratch", "new")
        return AdvisoryResult(
            decision=Decision.ALLOW,
            context=[
                f"{_ICON} Your scratch directory: {made.path}",
                f"   Make each piece of throwaway work an entry in it: `{command} <name> "
                "--purpose '...' [--plan NNNNN]` prints the path. Entries expire after "
                "their TTL; anything worth keeping is filed where git carries it.",
            ],
        )

    def get_claude_md(self) -> str | None:
        """The session scratch directory is a standing convention."""
        command = daemon_cli_command_for_docs("scratch", "new")
        return (
            "## scratch_sweep — your session's scratch directory\n\n"
            "At every SessionStart the daemon creates (once per session id) and announces "
            "`untracked/scratch/s-<UTC>-<first 8 of the session id>/` in the checkout the "
            "session starts in, with a daemon-written `.scratch-session.json` manifest. Put "
            f"throwaway work there as entries made by `{command} <name> --purpose '...' "
            "[--plan NNNNN] [--ttl-hours N]`, which records each entry's birth, purpose, plan "
            "and TTL and prints its path; a sub-agent in a worktree gets the same directory "
            "name in its own checkout. Scratch expires: anything worth keeping is filed where "
            "git carries it (a plan's `subagent-reports/`, a journal entry, a test). "
            "Advisory only; never blocks."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance test: the directory is announced, never blocks."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="scratch sweep - announces the session scratch directory",
                command='echo "test"',
                description=(
                    "On SessionStart the handler creates this session's directory under "
                    "untracked/scratch/ (idempotent) and announces it as 'Your scratch "
                    "directory', with the `scratch new` command. It never blocks."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"Your scratch directory|scratch session directory"],
                safety_notes="Creates one ignored directory under untracked/scratch/",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
