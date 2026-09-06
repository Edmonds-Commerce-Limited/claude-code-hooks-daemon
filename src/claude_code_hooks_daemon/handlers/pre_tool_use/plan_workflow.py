"""PlanWorkflowHandler - provides guidance for plan creation."""

from typing import Any, ClassVar, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler import WorkspaceScope
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.plan_qa.remedy import remedy_markdown_list
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# Fallback plan directory, used only when no ProjectLayout facade was
# injected. Mirrors PlanWorkflowConfig.directory's default exactly.
_FALLBACK_PLAN_DIR: Final[str] = "CLAUDE/Plan"
_FALLBACK_WORKFLOW_DOCS: Final[str] = "CLAUDE/PlanWorkflow.md"

#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR: Final[str] = "acceptance-test-planwf"


class PlanWorkflowHandler(PreToolUseHandlerBase):
    """Provide guidance when creating plan files."""

    # REPO-scoped: the plan tree is repository-singular (see
    # CLAUDE/Code/WorkspaceResolution.md).
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.REPO

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_WORKFLOW,
            priority=Priority.PLAN_WORKFLOW,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.PLANNING,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def _plan_dir(self) -> str:
        """Configured plan directory (facade, or the matching default)."""
        layout = self._project_layout
        return layout.plan_dir if layout is not None else _FALLBACK_PLAN_DIR

    def _workflow_docs(self) -> str:
        """Configured workflow document (facade, or the matching default).

        Quoting this rather than a literal is what keeps the guidance honest:
        the plan-workflow bootstrap deploys the document to exactly this path
        (Plan 00334), so a hardcoded ``CLAUDE/PlanWorkflow.md`` would name a
        file that does not exist in any project configured otherwise.
        """
        layout = self._project_layout
        return layout.workflow_docs if layout is not None else _FALLBACK_WORKFLOW_DOCS

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing PLAN.md in the configured plan directory."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name != ToolName.WRITE:
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        # Match {plan_dir}/*/PLAN.md (case-insensitive)
        normalized = file_path.replace("\\", "/")
        plan_dir_marker = f"{self._plan_dir()}/"
        return plan_dir_marker in normalized and normalized.lower().endswith("/plan.md")

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Provide guidance about plan workflow."""
        file_path = get_file_path(hook_input)

        guidance = (
            f"Creating plan file: {file_path}\n\n"
            "📋 Plan Workflow Reminders:\n"
            "  • Use task status icons: ⬜ (not started), 🔄 (in progress), ✅ (completed)\n"
            "  • Include Success Criteria section\n"
            "  • Break tasks into manageable phases\n"
            "  • Update task status as you work\n\n"
            f"See {self._workflow_docs()} for full guidelines."
        )

        return GatingResult(decision=Decision.ALLOW, context=[guidance])

    def get_claude_md(self) -> str | None:
        return (
            "## plan_workflow — PLAN.md, supporting docs and JOURNAL/ obey "
            "DIFFERENT contracts\n\n"
            "Confusing these is the single most common plan-hygiene failure: "
            "narrative AND durable detail both get crammed into `PLAN.md` until "
            "it is tens of KB of stale log. Each file has a WRITE contract and a "
            "READ contract, and the read contract is what justifies the write "
            "contract.\n\n"
            "| | `PLAN.md` | `SOME-DOC.md` | `JOURNAL/NNNNN-Journal-YY-MM-DD.md` |\n"
            "| --- | --- | --- | --- |\n"
            "| **Write** | Commit if dirty, EDIT IN PLACE, commit. Rewrite freely — "
            "git holds the history | EDIT IN PLACE, freely — a named supporting "
            "document, not a log | APPEND ONLY. Never edit or remove an earlier "
            "entry; corrections are new dated entries at the bottom |\n"
            "| **Content** | LEAN, surgical, always correct — current truth only: "
            "goals, decisions, task tree, status | Durable detail that is current "
            "but too big for the task list: research output, findings, decisions "
            "and their reasoning, drafts, evidence tables | What actually "
            "happened: dated progress, findings, incidents, hand-offs |\n"
            "| **Read** | Read IN FULL every session — it is your grounding | ON "
            "DEMAND, only when its link from `PLAN.md` is followed | NEVER read "
            "whole. `tail -n N` the newest day-file, grep it, or send a sub-agent "
            "for deep archaeology |\n"
            "| **Size** | Bounded — see tiers below | UNBOUNDED — never opened by "
            "a session that doesn't follow its link, so it costs that session "
            "nothing | UNBOUNDED by design. Length is never a problem; never tidy "
            "or trim a journal |\n\n"
            "**Why the asymmetry**: a plan is re-read in full at the start of every "
            "session that touches it, so every KB is a recurring context cost paid "
            "before any work starts. A supporting doc and a journal are both only "
            "ever read ON DEMAND — one via its link, the other by tailing/grepping "
            "— so both are safe to grow forever. This is the same "
            "progressive-disclosure argument the `markdown_organization` handler "
            "already makes for `.claude/rules/*.md`.\n\n"
            "**Size tiers on `PLAN.md`** (bytes OR lines, whichever trips first): "
            "advisory above 18,000 bytes / 350 lines; escalated warning above "
            "25,000 / 500; edits BLOCKED above 35,000 / 900.\n\n"
            "**When a plan gets too big there are three remedies, and NONE is "
            "deletion**:\n\n"
            f"{remedy_markdown_list()}\n\n"
            "**Only an edit that GROWS the file can be blocked.** Shrinking it is "
            "silent and a same-size edit (ticking a checkbox) only advises — so an "
            "oversized plan can always be updated and refactored down. If a plan "
            "genuinely warrants its size, record why in the file: "
            "`<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: <reason> -->`.\n\n"
            "**Task status icons**: ⬜ not started, 🔄 in progress, ✅ complete. "
            "Include a Success Criteria section and break work into phases.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Plan Workflow."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Writing to PLAN.md file",
                command=(
                    "Use the Write tool to write to "
                    f"{scratch_path(_FIXTURE_DIR, 'CLAUDE', 'Plan', '099-test', 'PLAN.md')}"
                    " with content '# Plan 099: Test Plan\\n\\n**Status**: Not Started'"
                ),
                description="Provides plan workflow guidance when writing PLAN.md (advisory)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"[Pp]lan", r"[Ww]orkflow"],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. Advisory handler "
                    "allows write and adds guidance. No setup mkdir: the Write tool "
                    "creates the missing parent directories itself, which also avoids "
                    "plan_number_helper reading a literal `mkdir .../CLAUDE/Plan/099-test` "
                    "as a hand-rolled plan-folder creation now that the fixture resolves "
                    "inside the repository."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[],
                cleanup_commands=[f"rm -rf untracked/scratch/{_FIXTURE_DIR}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
