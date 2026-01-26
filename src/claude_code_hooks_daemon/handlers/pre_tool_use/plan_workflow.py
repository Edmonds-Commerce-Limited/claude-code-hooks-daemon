"""PlanWorkflowHandler - provides guidance for plan creation."""

from typing import Any

from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_path


class PlanWorkflowHandler(Handler):
    """Provide guidance when creating plan files."""

    def __init__(self) -> None:
        super().__init__(name="plan-workflow-guidance", priority=45, terminal=False)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing PLAN.md in CLAUDE/Plan/ directory."""
        tool_name = hook_input.get("tool_name")
        if tool_name != "Write":
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

        return HookResult(decision=Decision.ALLOW, guidance=guidance)
