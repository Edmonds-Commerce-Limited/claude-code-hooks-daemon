"""ValidatePlanNumberHandler - validates plan folder numbering BEFORE directory creation."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField, Priority, ToolName
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_path, get_workspace_root


class ValidatePlanNumberHandler(Handler):
    """
    Validate plan folder numbering to ensure sequential plans.

    IMPORTANT: This runs as PreToolUse (BEFORE directory creation) to avoid
    the timing bug where PostToolUse sees the just-created directory as existing.

    The bug scenario (PostToolUse - WRONG):
    1. User finds highest plan: 060
    2. User creates CLAUDE/Plan/061-new/ (correct: 060 + 1)
    3. PostToolUse runs AFTER directory exists
    4. Handler sees 061 as existing, says "use 062" (FALSE WARNING!)

    The fix (PreToolUse - CORRECT):
    1. User finds highest plan: 060
    2. PreToolUse runs BEFORE mkdir/write
    3. Handler sees highest as 060, validates 061 is correct
    4. No false warning - operation proceeds

    SKIP VALIDATION FOR:
    - Files in .claude/commands/ (slash command documentation)
    - Files in .claude/hooks/ (hook documentation)
    - Bash heredoc content (documentation examples)
    """

    def __init__(self) -> None:
        super().__init__(
            name="validate-plan-number",
            priority=Priority.VALIDATE_PLAN_NUMBER,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.PLANNING,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        self.workspace_root = get_workspace_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if creating a plan folder."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        # Check Write operations
        if tool_name == ToolName.WRITE:
            file_path = get_file_path(hook_input)
            if file_path:
                # Skip documentation/command files
                if self._is_documentation_file(file_path):
                    return False

                # Match plan folder creation
                if re.search(r"CLAUDE/Plan/(\d{3})-([^/]+)/", file_path):
                    return True

        # Check Bash mkdir commands
        if tool_name == ToolName.BASH:
            command = get_bash_command(hook_input)
            if command:
                # Skip heredoc commands (documentation)
                if self._is_heredoc_command(command):
                    return False

                # Match mkdir for plan folders
                if re.search(r"mkdir.*?CLAUDE/Plan/(\d{3})-([^\s/]+)", command):
                    return True

        return False

    def _is_documentation_file(self, file_path: str) -> bool:
        """Check if file is documentation (skip validation for these)."""
        # Normalize path
        path_lower = file_path.lower()

        # Skip slash command files
        if "/.claude/commands/" in path_lower:
            return True

        # Skip hook documentation
        return bool(
            "/.claude/hooks/" in path_lower
            and (path_lower.endswith(".md") or path_lower.endswith("readme"))
        )

    def _is_heredoc_command(self, command: str) -> bool:
        """Check if bash command is a heredoc (cat > file << EOF)."""
        # Match heredoc patterns: cat > file << 'EOF' or cat > file << EOF
        return bool(re.search(r'<<\s*["\']?\w+["\']?', command))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Validate plan number is sequential."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        plan_number = None
        plan_name = None

        # Extract plan number and name
        if tool_name == ToolName.WRITE:
            file_path = get_file_path(hook_input)
            if file_path:
                match = re.search(r"CLAUDE/Plan/(\d{3})-([^/]+)/", file_path)
                if match:
                    plan_number = int(match.group(1))
                    plan_name = match.group(2)

        elif tool_name == ToolName.BASH:
            command = get_bash_command(hook_input)
            if command:
                match = re.search(r"mkdir.*?CLAUDE/Plan/(\d{3})-([^\s/]+)", command)
                if match:
                    plan_number = int(match.group(1))
                    plan_name = match.group(2)

        if not plan_number:
            return HookResult(decision=Decision.ALLOW)

        # Get highest existing plan number
        highest = self._get_highest_plan_number()
        expected_number = highest + 1

        # Validate number
        if plan_number != expected_number:
            error_message = f"""
PLAN NUMBER INCORRECT

You are creating: CLAUDE/Plan/{plan_number:03d}-{plan_name}/
Highest existing plan: {highest:03d}
Expected next number: {expected_number:03d}

BOTH active plans (CLAUDE/Plan/) AND completed plans (CLAUDE/Plan/Completed/) were checked.

HOW TO FIND CORRECT NUMBER:

Run this command BEFORE creating a plan:
```bash
find CLAUDE/Plan -maxdepth 2 -type d -name '[0-9]*' | grep -oP '/\\K\\d{{3}}(?=-)' | sort -n | tail -1
```

This searches BOTH directories and returns the highest number.
Next plan number = highest + 1

YOU MUST FIX THIS NOW:

Use the correct plan number: {expected_number:03d}

Example:
```bash
mkdir -p CLAUDE/Plan/{expected_number:03d}-{plan_name}
```

See: CLAUDE/Plan/CLAUDE.md for full instructions
"""

            return HookResult(decision=Decision.ALLOW, context=[error_message])

        # Number is correct
        return HookResult(decision=Decision.ALLOW)

    def _get_highest_plan_number(self) -> int:
        """Find highest plan number from both active and completed plans."""
        plan_root = self.workspace_root / "CLAUDE/Plan"

        if not plan_root.exists():
            return 0

        plan_dirs = []

        # Active plans
        for item in plan_root.iterdir():
            if item.is_dir() and re.match(r"^\d{3}-", item.name):
                plan_dirs.append(item.name)

        # Completed plans
        completed_dir = plan_root / "Completed"
        if completed_dir.exists():
            for item in completed_dir.iterdir():
                if item.is_dir() and re.match(r"^\d{3}-", item.name):
                    plan_dirs.append(item.name)

        if not plan_dirs:
            return 0

        # Extract numbers and find highest
        numbers = []
        for dirname in plan_dirs:
            match = re.match(r"^(\d{3})-", dirname)
            if match:
                numbers.append(int(match.group(1)))

        return max(numbers) if numbers else 0
