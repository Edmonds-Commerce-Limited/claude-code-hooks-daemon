"""PlanWorkflowAssetCheckerHandler - advise when plan-workflow assets are missing.

Plan 00185 Task 3.2. When the plan workflow is enabled in config but the
daemon-owned ``mkplan.bash`` is absent from the plan directory, the plan tooling
is silently broken: ``CLAUDE.md`` and ``plan_number_helper`` point at a
``mkplan.bash`` that does not exist, and journalling is advertised but inert.
This SessionStart advisory surfaces that drift and points at the on-demand fix
(``deploy-plan-workflow``). It never blocks.

Runs on new sessions only. ``mkplan.bash`` (daemon-owned, always deployed when
the workflow is on) is the definitive signal — the journal assets are
client-owned and may be intentionally removed, so their absence alone is not a
trigger; they are only named as also-missing once ``mkplan.bash`` is gone.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.install.plan_workflow import (
    JOURNAL_TEMPLATE_NAME,
    MKPLAN_SCRIPT_NAME,
    PLAN_JOURNALLING_DOC_NAME,
)

logger = logging.getLogger(__name__)

_RESUME_TRANSCRIPT_MIN_BYTES = 100
_DEPLOY_CLI_HINT = "$PYTHON -m claude_code_hooks_daemon.daemon.cli deploy-plan-workflow"


class PlanWorkflowAssetCheckerHandler(Handler):
    """Advise when plan_workflow is enabled but its assets are not provisioned."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_WORKFLOW_ASSET_CHECKER,
            priority=Priority.PLAN_WORKFLOW_ASSET_CHECKER,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.PLANNING,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # Injected by the registry for PLANNING-tagged handlers: the plan
        # directory (relative) when the workflow is enabled, else None.
        self._track_plans_in_project: str | None = None

    def _is_resume_session(self, hook_input: dict[str, Any]) -> bool:
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if not transcript_path:
            return False
        try:
            path = Path(transcript_path)
            return path.exists() and path.stat().st_size > _RESUME_TRANSCRIPT_MIN_BYTES
        except (OSError, ValueError):
            return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if self._is_resume_session(hook_input):
            return False
        # None => plan workflow disabled in config => nothing to check.
        return self._track_plans_in_project is not None

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        plan_dir_rel = self._track_plans_in_project
        if plan_dir_rel is None:  # pragma: no cover - matches() gates this
            return HookResult(decision=Decision.ALLOW, context=[])

        try:
            project_root = ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; skipping plan asset check")
            return HookResult(decision=Decision.ALLOW, context=[])

        plan_dir = project_root / plan_dir_rel
        mkplan = plan_dir / MKPLAN_SCRIPT_NAME
        if mkplan.exists():
            # Daemon-owned scaffolder present => provisioning is intact.
            return HookResult(decision=Decision.ALLOW, context=[])

        # mkplan.bash is missing — the plan tooling is broken. Name every core
        # asset that is also absent so a single deploy fixes them all.
        missing = [f"{plan_dir_rel}/{MKPLAN_SCRIPT_NAME} (plan scaffolder — daemon-owned)"]
        if not (plan_dir / JOURNAL_TEMPLATE_NAME).exists():
            missing.append(
                f"{plan_dir_rel}/{JOURNAL_TEMPLATE_NAME} "
                "(journal marker — gates per-plan JOURNAL/ scaffolding)"
            )
        journalling_doc = plan_dir.parent / PLAN_JOURNALLING_DOC_NAME
        if not journalling_doc.exists():
            missing.append(
                f"{plan_dir.parent.name}/{PLAN_JOURNALLING_DOC_NAME} " "(journalling reference doc)"
            )

        context = [
            "⚠️  PLAN WORKFLOW ASSETS MISSING: plan_workflow is enabled but its "
            "assets are not provisioned.",
            "",
            "CLAUDE.md and plan_number_helper point at a mkplan.bash that does "
            "not exist, so plan creation and journalling are silently broken.",
            "",
            "Missing:",
        ]
        context.extend(f"  ❌ {entry}" for entry in missing)
        context += [
            "",
            "Fix — (re)deploy the assets (idempotent; fills gaps only):",
            "",
            f"  {_DEPLOY_CLI_HINT}",
        ]
        return HookResult(decision=Decision.ALLOW, context=context)

    def get_claude_md(self) -> str | None:
        return (
            "## plan_workflow_asset_checker — plan tooling provisioning alert\n"
            "\n"
            "At session start, when the plan workflow is enabled but the "
            "daemon-owned `mkplan.bash` is missing from the plan directory, this "
            "advisory fires (it never blocks). A missing `mkplan.bash` means "
            "`CLAUDE.md` and `plan_number_helper` reference a scaffolder that "
            "does not exist and journalling is inert.\n"
            "\n"
            "**Fix**: (re)deploy the assets on demand —\n"
            "\n"
            "```\n"
            f"{_DEPLOY_CLI_HINT}\n"
            "```\n"
            "\n"
            "The deploy is idempotent (fills gaps only, never overwrites "
            "client-owned files). Silent when `mkplan.bash` is present or the "
            "workflow is disabled."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="plan workflow asset checker - reports missing assets on new session",
                command='echo "test"',
                description=(
                    "Verifies the handler advises running deploy-plan-workflow when "
                    "the plan workflow is enabled but mkplan.bash is missing."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"PLAN WORKFLOW ASSETS|deploy-plan-workflow"],
                safety_notes="Advisory handler - warns but does not block",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
