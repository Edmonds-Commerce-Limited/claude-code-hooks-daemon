"""RoutineQaSweepHandler — the routine dead-man's switch (Plan 00412 Task 2.5).

Every other part of the Routine system reports what the records SAY. This one
reports what they do not contain.

A run that never happened leaves no record at all, so its absence is not
observable from the records themselves (D6) — which is exactly why "never ran"
was kept out of the run-state vocabulary rather than added to it. Something
OUTSIDE the records has to know a routine exists and assert that a run is
overdue, and session start is where that happens: it is the one surface the
daemon executes itself, rather than one it can only hope fired (D9).

Silent when the tree is clean, and deliberately so. A handler that speaks every
session becomes scenery, which is the problem Plan 00416 exists to fix; an
advisory nobody reads is worth what no advisory is worth.

Never raises. A sweep that dies reports nothing — and so does a healthy tree.
Those two outcomes must never be the same, which is this plan's central
argument applied to its own reporting surface.
"""

import logging
from datetime import date
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.routines.git_ancestry import GitAncestry
from claude_code_hooks_daemon.routines.qa import RoutineFinding, sweep
from claude_code_hooks_daemon.routines.resolver import list_routines, routines_dir
from claude_code_hooks_daemon.utils.cli_command import (
    daemon_cli_command,
    daemon_cli_command_for_docs,
)
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)


class RoutineQaSweepHandler(SessionStartHandlerBase):
    """Advisory SessionStart sweep over the Routine tree (silent when clean)."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ROUTINE_QA_SWEEP,
            priority=Priority.ROUTINE_QA_SWEEP,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.PLANNING,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def get_default_enabled(self) -> bool:
        """Opt-in: most projects have no Routine tree.

        Returns:
            False. Firing for a project that declares no routines would be
            noise on day one, and a handler learned as noise is not read later
            when it has something to say.
        """
        return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Fire on a new session for a project that declares routines.

        Args:
            hook_input: The SessionStart payload.

        Returns:
            False on a resumed session (it already saw the report) and for a
            project with no routines (nothing can be failing).
        """
        if is_resume_session(hook_input):
            return False
        return bool(list_routines(ProjectContext.project_root()))

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Report drift, or say nothing at all.

        Args:
            hook_input: The SessionStart payload.

        Returns:
            An ALLOW with the findings, or an ALLOW with empty context when
            the tree is clean. Never a block: a stale routine is a thing to
            fix, not a reason to wedge a session.
        """
        project_root = ProjectContext.project_root()
        try:
            findings = sweep(
                project_root,
                today=date.today(),
                ancestry=GitAncestry(project_root),
            )
        except OSError as error:
            # Reported, not swallowed and not raised. Silence here would be
            # indistinguishable from a clean tree, which is the one outcome
            # this whole design refuses to allow.
            logger.warning(
                "routine_qa_sweep: could not read %s (%s)", routines_dir(project_root), error
            )
            return AdvisoryResult(
                decision=Decision.ALLOW,
                context=[
                    f"⚠️  ROUTINE QA: could not read {routines_dir(project_root)} ({error}).",
                    "The sweep could not run, which is NOT the same as finding nothing.",
                ],
            )

        if not findings:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        return AdvisoryResult(decision=Decision.ALLOW, context=_render(findings))

    def get_claude_md(self) -> str | None:
        """Guidance for the generated CLAUDE.md block."""
        return (
            "## routine_qa_sweep — recurring work that has stopped recurring\n"
            "\n"
            "At session start this reports drift across `CLAUDE/Routine/`, and is "
            "**silent when the tree is clean**.\n"
            "\n"
            "A Routine is recurring work that never completes — a Plan finishes, a "
            "Routine recurs. The findings all share one shape: **the failure they "
            "catch leaves no trace.** A run that never happened writes no record, so "
            "the absence cannot be seen in the records themselves; an obligation that "
            "quietly stopped being met looks exactly like one being met.\n"
            "\n"
            "- `routine-never-run` — declared active, no record at all.\n"
            "- `routine-overdue` — past its period PLUS its grace. Only a run that "
            "FINISHED counts; a run that merely started proves somebody began.\n"
            "- `routine-run-gap` — commits between two runs that neither covered.\n"
            "- `routine-ledger-unreadable` — a hand-edited row in `RUNS/`.\n"
            "- `routine-not-configured` — the ROUTINE.md header does not declare a "
            "Status or Trigger the checks recognise, so the routine is invisible to "
            "every other check here.\n"
            "\n"
            "Re-check after fixing: "
            f"`{daemon_cli_command_for_docs('routine-qa')}`.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """The one behaviour worth proving against a live session."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="routine-qa sweep - session start drift report",
                command='echo "session start"',
                description=(
                    "On a NEW session in a project with a CLAUDE/Routine/ tree and "
                    "drift present, the SessionStart context contains a 'ROUTINE QA' "
                    "block naming each routine, what is wrong and how to fix it. On a "
                    "clean tree the handler stays silent -- which is the property that "
                    "keeps it worth reading."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"ROUTINE QA|routine-qa"],
                safety_notes="Advisory handler - never blocks",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]


def _render(findings: list[RoutineFinding]) -> list[str]:
    """The advisory block for ``findings``.

    Args:
        findings: What the sweep reported; never empty here.

    Returns:
        Context lines, one finding per pair, with the re-check command last.
    """
    lines = [f"📋 ROUTINE QA: {len(findings)} finding(s) in CLAUDE/Routine/:"]
    for finding in findings:
        lines.append(f"  • {finding.routine}: {finding.message}")
        lines.append(f"    → {finding.remediation}")
    lines.append("")
    lines.append("Full report / re-check after fixing: " + daemon_cli_command("routine-qa"))
    return lines
