"""Plan Number Helper Handler.

Prevents Claude from using broken bash commands to discover plan numbers.
Instead of letting Claude use commands like:
    ls -d CLAUDE/Plan/0* 2>/dev/null | sort -V | tail -1

Which are broken (wrong glob patterns, ignore Completed/, etc.), this handler
detects these attempts and injects the correct next plan number into context.

Non-blocking (advisory only) - provides context but doesn't prevent execution.
"""

import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.utils.plan_numbering import get_next_plan_number


class PlanNumberHelperHandler(Handler):
    """Detect bash commands attempting to discover plan numbers and provide correct answer."""

    def __init__(self) -> None:
        """Initialize handler."""
        super().__init__(
            handler_id=HandlerID.PLAN_NUMBER_HELPER,
            priority=Priority.PLAN_NUMBER_HELPER,  # Run before markdown_organization (35)
            terminal=True,  # Block broken commands that return incorrect plan numbers
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.PLANNING],
            shares_options_with="markdown_organization",  # Inherit config from parent (config key)
        )

        # Configuration attributes (set by registry after instantiation)
        self._workspace_root: Path = ProjectContext.project_root()
        self._track_plans_in_project: str | None = None  # Path to plan folder or None
        self._plan_workflow_docs: str | None = None  # Path to workflow doc or None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match bash commands attempting to discover plan numbers.

        Args:
            hook_input: Hook input data

        Returns:
            True if this is a bash command trying to discover plan numbers
        """
        # Only active when planning mode is enabled
        if not self._track_plans_in_project:
            return False

        # Only match Bash tool
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False

        command = hook_input.get(HookInputField.TOOL_INPUT, {}).get("command", "")
        if not command:
            return False

        # Get the plan directory path (relative to workspace)
        plan_dir = self._track_plans_in_project

        # Pattern detection: Commands trying to discover plan numbers
        # These patterns indicate Claude is trying to find the latest plan

        # 1. ls with glob patterns on plan directory
        ls_patterns = [
            rf"ls\s+.*{re.escape(plan_dir)}/\*",  # ls CLAUDE/Plan/*
            rf"ls\s+.*{re.escape(plan_dir)}/0\*",  # ls CLAUDE/Plan/0*
            rf"ls\s+.*{re.escape(plan_dir)}/\[0-9\]",  # ls CLAUDE/Plan/[0-9]*
        ]

        for pattern in ls_patterns:
            if re.search(pattern, command):
                return True

        # 2. find commands on plan directory
        find_patterns = [
            rf"find\s+{re.escape(plan_dir)}",
        ]

        for pattern in find_patterns:
            if re.search(pattern, command):
                return True

        # 3. Glob expansion (echo, printf with plan directory globs)
        # Match patterns like: echo CLAUDE/Plan/0*, echo CLAUDE/Plan/*, echo CLAUDE/Plan/[0-9]*
        glob_patterns = [
            rf"echo\s+.*{re.escape(plan_dir)}/[0-9\*\[]",  # echo with glob chars
            rf"printf\s+.*{re.escape(plan_dir)}/[0-9\*\[]",  # printf with glob chars
        ]

        for pattern in glob_patterns:
            if re.search(pattern, command):
                return True

        # 4. Commands with sort and tail on plan directory output
        # This catches complex pipelines like: ls ... | sort -V | tail -1
        if plan_dir in command and "sort" in command and "tail" in command:
            # Additional check: make sure it's actually trying to get latest
            if re.search(r"tail\s+-\d+", command) or "tail -1" in command:
                return True

        # 5. ls on plan directory piped to grep with number patterns
        # This catches: ls CLAUDE/Plan/ | grep -E '^[0-9]+' or similar
        if re.search(rf"ls\s+.*{re.escape(plan_dir)}", command) and "grep" in command:
            # Check if grep is filtering for numbers (common pattern)
            if re.search(r"grep.*['\"]?\^?\[?0-9\]?", command):
                return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block broken command and provide correct next plan number.

        Args:
            hook_input: Hook input data

        Returns:
            HookResult with DENY decision and helpful reason
        """
        # Precondition: matches() ensures _track_plans_in_project is not None
        assert self._track_plans_in_project is not None, "Handler called without matches check"

        # Get next plan number
        try:
            plan_base = self._workspace_root / self._track_plans_in_project
            next_number = get_next_plan_number(plan_base)

            reason_message = (
                f"🚫 BLOCKED: This command won't find all plans (misses subdirectories like Completed/).\n\n"
                f"💡 Next plan number is {next_number}. "
                f"Use this instead of bash commands to discover plan numbers."
            )

            # Add workflow docs reference if configured
            if self._plan_workflow_docs:
                workflow_path = self._workspace_root / self._plan_workflow_docs
                if workflow_path.exists():
                    reason_message += (
                        f"\n📖 See `{self._plan_workflow_docs}` for plan structure and conventions."
                    )

            return HookResult.deny(reason=reason_message)

        except Exception as e:
            # Gracefully handle errors - still block the broken command
            reason_message = (
                f"🚫 BLOCKED: This command won't find all plans.\n\n"
                f"⚠️ Could not determine next plan number ({e}). "
                f"Starting from 00001 if this is a new project."
            )

            return HookResult.deny(reason=reason_message)
