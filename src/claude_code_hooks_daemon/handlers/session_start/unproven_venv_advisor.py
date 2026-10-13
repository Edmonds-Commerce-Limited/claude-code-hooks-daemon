"""UnprovenVenvAdvisorHandler - venvs the code cannot prove stale (Plan 00517 Task 4.2).

Removal of a venv needs a positive finding: a readable ``lock_hash`` that
differs from the current source's, on this view's slug. A venv with missing or
unreadable metadata, or another checkout view's slug, gives the code nothing to
prove, so nothing removes it automatically, and before this advisory nothing
mentioned it either: it stayed on disk, unexplained, until someone noticed.

This handler puts each one in front of the running agent at session start with
the facts that decide it (the processes using it, its interpreter and version,
its age, its slug and the view it belongs to) and the exact command that removes
it. The agent investigates, and removes a venv only once it has confirmed it is
safe. Silent when there are none (Lean SessionStart, Plan 00128).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir
from claude_code_hooks_daemon.daemon.paths import (
    VENV_UNPROVEN,
    classify_untracked_venvs,
    gather_venv_evidence,
    project_path_slug,
    unproven_report_lines,
)
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command


class UnprovenVenvAdvisorHandler(SessionStartHandlerBase):
    """List venvs the code cannot prove stale, with evidence and the removal command."""

    def __init__(self) -> None:
        """Initialise as a non-terminal, silent-when-clean advisory."""
        super().__init__(
            handler_id=HandlerID.UNPROVEN_VENV_ADVISOR,
            priority=Priority.UNPROVEN_VENV_ADVISOR,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.ENVIRONMENT,
                HandlerTag.NON_TERMINAL,
            ],
        )
        #: Set in tests so the scan needs no initialised ProjectContext.
        self.workspace_root: Path | None = None

    def _project_root(self) -> Path | None:
        """The project root, or None when the daemon has not initialised one."""
        if self.workspace_root is not None:
            return self.workspace_root
        if not ProjectContext.is_initialized():
            return None
        return ProjectContext.project_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every session start, including resumes: a venv left behind outlives the session."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Report each UNPROVEN venv with evidence; nothing when there are none."""
        root = self._project_root()
        if root is None:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        daemon_dir = get_untracked_dir(root).parent
        unproven = [
            verdict.path
            for verdict in classify_untracked_venvs(daemon_dir)
            if verdict.verdict == VENV_UNPROVEN
        ]
        if not unproven:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        evidence = gather_venv_evidence(unproven, project_path_slug(daemon_dir))
        lines = unproven_report_lines(
            evidence,
            lambda venv: daemon_cli_command("prune-venvs", "--unproven", str(venv), "--force"),
        )
        return AdvisoryResult(decision=Decision.ALLOW, context=lines)

    def get_acceptance_tests(self) -> list[Any]:
        """One CONTEXT case: an UNPROVEN venv is listed with evidence at session start."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="unproven venv advisor - lists venvs the code cannot prove stale",
                command='echo "test"',
                description=(
                    "With a venv under the daemon's untracked/ whose metadata is "
                    "missing or unreadable, or whose slug belongs to another view, "
                    "session start lists it with the processes using it, its "
                    "interpreter, age and view, and the exact removal command. "
                    "Silent when there are none."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"UNPROVEN venv"],
                safety_notes="Advisory only - never removes a venv.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SessionStart event (new session only)",
                requires_main_thread=False,
            ),
        ]

    def get_claude_md(self) -> str | None:
        """No resident guidance: the report carries its own instructions when it fires."""
        return None
