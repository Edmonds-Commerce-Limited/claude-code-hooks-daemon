"""PlanWorkflowHandler - provides guidance for plan creation."""

from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_path


class PlanWorkflowHandler(Handler):
    """Provide guidance when creating plan files."""

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

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing PLAN.md in CLAUDE/Plan/ directory."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name != ToolName.WRITE:
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        # Match CLAUDE/Plan/*/PLAN.md (case-insensitive)
        normalized = file_path.replace("\\", "/")
        return "CLAUDE/Plan/" in normalized and normalized.lower().endswith("/plan.md")

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Provide guidance about plan workflow."""
        file_path = get_file_path(hook_input)

        guidance = (
            f"Creating plan file: {file_path}\n\n"
            "📋 Plan Workflow Reminders:\n"
            "  • Use task status icons: ⬜ (not started), 🔄 (in progress), ✅ (completed)\n"
            "  • Include Success Criteria section\n"
            "  • Break tasks into manageable phases\n"
            "  • Update task status as you work\n\n"
            "See CLAUDE/PlanWorkflow.md for full guidelines."
        )

        return HookResult(decision=Decision.ALLOW, context=[guidance])

    def get_claude_md(self) -> str | None:
        return (
            "## plan_workflow — PLAN.md and JOURNAL/ obey OPPOSITE contracts\n\n"
            "Confusing these two is the single most common plan-hygiene failure: "
            "narrative gets appended to `PLAN.md` until it is tens of KB of stale "
            "log. Each file has a WRITE contract and a READ contract, and the read "
            "contract is what justifies the write contract.\n\n"
            "| | `PLAN.md` | `JOURNAL/NNNNN-Journal-YY-MM-DD.md` |\n"
            "| --- | --- | --- |\n"
            "| **Write** | Commit if dirty, EDIT IN PLACE, commit. Rewrite freely — "
            "git holds the history | APPEND ONLY. Never edit or remove an earlier "
            "entry; corrections are new dated entries at the bottom |\n"
            "| **Content** | LEAN, surgical, always correct — current truth only: "
            "goals, decisions, task tree, status | What actually happened: dated "
            "progress, findings, incidents, hand-offs |\n"
            "| **Read** | Read IN FULL every session — it is your grounding | NEVER "
            "read whole. `tail -n N` the newest day-file, grep it, or send a "
            "sub-agent for deep archaeology |\n"
            "| **Size** | Bounded — see tiers below | UNBOUNDED by design. Length is "
            "never a problem; never tidy or trim a journal |\n\n"
            "**Why the asymmetry**: a plan is re-read in full at the start of every "
            "session that touches it, so every KB is a recurring context cost paid "
            "before any work starts. A journal is only ever sampled, so it is safe "
            "to grow forever.\n\n"
            "**Size tiers on `PLAN.md`** (bytes OR lines, whichever trips first): "
            "advisory above 18,000 bytes / 350 lines; escalated warning above "
            "25,000 / 500; edits BLOCKED above 35,000 / 900.\n\n"
            "**When a plan gets too big there are exactly two remedies, and "
            "NEITHER is deletion**:\n\n"
            "1. **Relocate** the narrative into this plan's `JOURNAL/` day-file.\n"
            "2. **Split** the plan if the task tree itself is the bulk — an "
            "over-scoped plan is not fixed by better journalling.\n\n"
            "Shrinking edits are never blocked, so an oversized plan can always be "
            "refactored down. If a plan genuinely warrants its size, record why in "
            "the file: `<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: <reason> -->`.\n\n"
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
                    "Use the Write tool to write to /tmp/acceptance-test-planwf/CLAUDE/Plan/099-test/PLAN.md"
                    " with content '# Plan 099: Test Plan\\n\\n**Status**: Not Started'"
                ),
                description="Provides plan workflow guidance when writing PLAN.md (advisory)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"[Pp]lan", r"[Ww]orkflow"],
                safety_notes="Uses /tmp path - safe. Advisory handler allows write and adds guidance.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-planwf/CLAUDE/Plan/099-test"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-planwf"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
