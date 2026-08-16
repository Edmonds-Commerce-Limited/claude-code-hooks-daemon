"""PlanQaSweepHandler — Stage 3 plan QA sweep at session start (Plan 00144).

Runs the whole-tree plan QA check catalogue (the same cross-file invariants
the commit gate enforces, plus staleness/dormancy/claim advisories) against
the configured plan directory and injects ONE compact drift report as
advisory context. Silent when the tree is clean; new sessions only (a
resumed session already saw the report).

Policy comes from ``plan_workflow.qa`` via the registry's PLANNING-tag
injection (``_plan_qa`` / ``_track_plans_in_project``) — zero per-handler
options.
"""

import logging
from datetime import date
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.plan_qa.context import sweep_context
from claude_code_hooks_daemon.plan_qa.report import format_advisory
from claude_code_hooks_daemon.plan_qa.runner import run_stage
from claude_code_hooks_daemon.plan_qa.types import Stage
from claude_code_hooks_daemon.utils.cli_command import (
    daemon_cli_command,
    daemon_cli_command_for_docs,
)
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)
_SWEEP_MODE_ADVISE: Final[str] = "advise"


def _cli_hint() -> str:
    """Re-check directive naming the deployed wrapper (Plan 00192).

    Computed on demand rather than at import: the wrapper path depends on the
    install mode, which ``ProjectContext`` only knows after daemon startup.
    """
    return "Full report / re-check after fixing: " + daemon_cli_command("plan-qa", "--sweep")


class PlanQaSweepHandler(Handler):
    """Advisory SessionStart sweep over the plan tree (silent when clean)."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_QA_SWEEP,
            priority=Priority.PLAN_QA_SWEEP,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.PLANNING,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # Injected by the registry for PLANNING-tagged handlers.
        self._track_plans_in_project: str | None = None
        self._plan_qa: Any = None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if is_resume_session(hook_input):
            return False
        if self._track_plans_in_project is None:
            return False
        policy = self._plan_qa
        if policy is None or not policy.enabled:
            return False
        return bool(policy.sweep_mode == _SWEEP_MODE_ADVISE)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        plan_dir_rel = self._track_plans_in_project
        if plan_dir_rel is None:  # pragma: no cover - matches() gates this
            return HookResult(decision=Decision.ALLOW, context=[])

        project_root = ProjectContext.project_root()
        try:
            context = sweep_context(
                project_root=project_root,
                plan_dir_rel=plan_dir_rel,
                policy=self._plan_qa,
                today=date.today(),
            )
        except FileNotFoundError:
            # Structural finding, not a crash: the configured plan dir is gone.
            return HookResult(
                decision=Decision.ALLOW,
                context=[
                    f"⚠️  PLAN QA: configured plan directory {plan_dir_rel}/ does not exist.",
                    f"Create it (plus {self._plan_qa.completed_dir}/ and README.md) or fix "
                    "plan_workflow.directory in .claude/hooks-daemon.yaml.",
                ],
            )

        findings = run_stage(Stage.SWEEP, context)
        if not findings:
            return HookResult(decision=Decision.ALLOW, context=[])

        return HookResult(
            decision=Decision.ALLOW,
            context=[format_advisory(findings), "", _cli_hint()],
        )

    def get_claude_md(self) -> str | None:
        return (
            "## plan_qa_sweep — plan-tree drift report at session start\n"
            "\n"
            "At the start of each new session the plan directory is swept with the\n"
            "plan QA check catalogue. That covers the cross-file invariants\n"
            "(index/folder bijection, number collisions, statistics recount,\n"
            "archive structure, status-vs-location coherence, staleness) AND the\n"
            "document-level rules applied to every PLAN.md already on disk —\n"
            "status line present, status token in the enum, header/body coherence,\n"
            "task grammar, path existence, journal day-file naming. Findings are\n"
            "injected once as advisory context — the sweep never blocks.\n"
            "\n"
            "**A rule that only fires at write time cannot see what predates it.**\n"
            "The document-level checks run on BOTH surfaces for that reason, so a\n"
            "violation introduced before the rule existed — or by a `git mv`, a\n"
            "merge, or any path other than a Write/Edit tool call — is still\n"
            "reported. The rules that are deliberately edit-only are the ones\n"
            "about the ACT of writing (editing an archived plan, rewriting a\n"
            "journal, growing an oversized document); each records its reason in\n"
            "`plan_qa/checks/common.py`.\n"
            "\n"
            "**When a drift report appears**: fix the listed findings (each names\n"
            "its exact remediation) as part of your plan housekeeping, then\n"
            "re-check with:\n"
            "\n"
            "```\n"
            f"{daemon_cli_command_for_docs('plan-qa', '--sweep')}\n"
            "```\n"
            "\n"
            "The CLI exits 1 while findings remain (CI-able). Single-file lint:\n"
            "`plan-qa --lint <PLAN.md>`; staged-commit check: `plan-qa --check-staged`.\n"
            "Policy lives under `plan_workflow.qa` in `.claude/hooks-daemon.yaml`\n"
            "(archive dir names, staleness window, legacy/collision allowlists)."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="plan-qa sweep - session start drift report",
                command='echo "session start"',
                description=(
                    "On a NEW session in a project with plan QA enabled and plan-tree "
                    "drift present, the SessionStart context contains a 'Plan QA drift "
                    "report' block naming check ids and remediations. On a clean tree "
                    "the handler stays silent."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"Plan QA drift report|plan-qa --sweep"],
                safety_notes="Advisory handler - never blocks",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
