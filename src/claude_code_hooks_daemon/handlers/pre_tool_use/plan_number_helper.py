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

from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.handlers.utils.plan_numbering import get_next_plan_number


class PlanNumberHelperHandler(Handler):
    """Detect bash commands attempting to discover plan numbers and provide correct answer."""

    def __init__(self) -> None:
        """Initialize handler."""
        super().__init__(
            name="plan-number-helper",
            priority=30,  # Run before markdown_organization (35)
            terminal=False,  # Advisory only, don't block
            tags=["workflow", "advisory", "planning"],
        )

        # Configuration attributes (set by registry after instantiation)
        self._workspace_root: Path = Path.cwd()
        self._track_plans_in_project: str | None = None  # Path to plan folder or None

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
        if hook_input.get("tool_name") != "Bash":
            return False

        command = hook_input.get("tool_input", {}).get("command", "")
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

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Provide correct next plan number in context.

        Args:
            hook_input: Hook input data

        Returns:
            HookResult with ALLOW decision and helpful context
        """
        # Get next plan number
        try:
            plan_base = self._workspace_root / self._track_plans_in_project
            next_number = get_next_plan_number(plan_base)

            context_message = (
                f"💡 Next plan number is {next_number}. "
                f"Use this instead of bash commands to discover plan numbers."
            )

            return HookResult.allow(context=[context_message])

        except Exception as e:
            # Gracefully handle errors - provide default context
            context_message = (
                f"⚠️ Could not determine next plan number ({e}). "
                f"Starting from 00001 if this is a new project."
            )

            return HookResult.allow(context=[context_message])
