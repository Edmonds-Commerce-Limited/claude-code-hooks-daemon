"""Handler to block pip install --break-system-packages flag.

This handler prevents the use of pip's --break-system-packages flag, which
disables the system package manager conflict detection and can corrupt
Python installations managed by the OS package manager.
"""

import re
from typing import Any

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult


class PipBreakSystemHandler(Handler):
    """Block pip install --break-system-packages commands.

    This flag was introduced in pip 22.1 to bypass PEP 668 externally-managed
    environment protections. Using it can:
    - Conflict with system package manager (apt, dnf, etc.)
    - Break OS tools that depend on Python
    - Corrupt system Python installation
    - Cause difficult-to-debug issues

    Priority: 10 (safety-critical)
    Terminal: True (blocks execution)
    """

    def __init__(self) -> None:
        """Initialize handler with safety-critical priority."""
        super().__init__(
            handler_id=HandlerID.PIP_BREAK_SYSTEM,
            priority=Priority.PIP_BREAK_SYSTEM,
            terminal=True,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if command contains pip install --break-system-packages.

        Matches:
        - pip install --break-system-packages
        - pip3 install --break-system-packages
        - python -m pip install --break-system-packages
        - python3 -m pip install --break-system-packages

        Case-insensitive matching.

        Args:
            hook_input: Hook input containing tool_name and tool_input

        Returns:
            True if command uses --break-system-packages flag
        """
        # Only process Bash commands
        if hook_input.get("tool_name") != "Bash":
            return False

        # Extract command
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command")
        if not command:
            return False

        # Pattern: Any form of pip install with --break-system-packages
        # Matches: pip/pip3/python -m pip/python3 -m pip + install + --break-system-packages
        pattern = r"\b(pip3?|python3?\s+-m\s+pip)\s+install\s+.*--break-system-packages"

        return bool(re.search(pattern, command, re.IGNORECASE))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block command and explain why --break-system-packages is dangerous.

        Args:
            hook_input: Hook input containing the dangerous command

        Returns:
            HookResult with deny decision and explanation
        """
        # Safety check: if command doesn't match, allow
        if not self.matches(hook_input):
            return HookResult(decision=Decision.ALLOW)

        command = hook_input.get("tool_input", {}).get("command", "")

        reason = f"""🚫 BLOCKED: pip install --break-system-packages

COMMAND: {command}

WHY BLOCKED:
The --break-system-packages flag disables pip's protection against
conflicting with your system package manager (apt, dnf, pacman, etc.).

Using this flag can:
  • Corrupt your system Python installation
  • Break OS tools that depend on Python
  • Cause conflicts with system package manager
  • Create difficult-to-debug environment issues

SAFE alternatives:
  1. Use a virtual environment (RECOMMENDED):
     python -m venv myenv
     source myenv/bin/activate
     pip install <package>

  2. Use --user flag for user-local install:
     pip install --user <package>

  3. If in a container/isolated environment, ask the human user
     whether it's safe to proceed (they can override if truly needed)

NEVER use --break-system-packages as default behavior."""

        return HookResult(
            decision=Decision.DENY,
            reason=reason,
            context=[],
            guidance=None,
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for pip break system handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="pip install --break-system-packages",
                command='echo "pip install --break-system-packages requests"',
                description="Blocks pip --break-system-packages flag (system corruption risk)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"--break-system-packages",
                    r"system Python installation",
                    r"virtual environment",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="python3 -m pip install --break-system-packages",
                command='echo "python3 -m pip install --break-system-packages numpy"',
                description="Blocks python3 -m pip with --break-system-packages",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"--break-system-packages",
                    r"Corrupt.*system Python",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
