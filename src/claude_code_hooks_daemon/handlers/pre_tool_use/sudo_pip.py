"""Handler to block sudo pip install commands.

This handler prevents the use of sudo with pip install, which creates
system-wide package installations that can conflict with OS package managers
and break system tools.
"""

import re

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult


class SudoPipHandler(Handler):
    """Block sudo pip install commands.

    System-wide pip installs using sudo can:
    - Conflict with OS package manager (apt, dnf, etc.)
    - Break OS tools that depend on Python packages
    - Create permission and ownership issues
    - Bypass externally-managed environment protections

    Priority: 10 (safety-critical)
    Terminal: True (blocks execution)
    """

    def __init__(self) -> None:
        """Initialize handler with safety-critical priority."""
        super().__init__(
            name=HandlerID.SUDO_PIP.display_name,
            priority=Priority.SUDO_PIP,
            terminal=True,
        )

    def matches(self, hook_input: dict) -> bool:
        """Check if command contains sudo pip install.

        Matches:
        - sudo pip install
        - sudo pip3 install
        - sudo python -m pip install
        - sudo python3 -m pip install

        Case-insensitive matching.

        Args:
            hook_input: Hook input containing tool_name and tool_input

        Returns:
            True if command uses sudo pip install
        """
        # Only process Bash commands
        if hook_input.get("tool_name") != "Bash":
            return False

        # Extract command
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command")
        if not command:
            return False

        # Pattern: sudo + any form of pip install
        # Matches: sudo pip/pip3/python -m pip/python3 -m pip + install
        pattern = r"\bsudo\s+(pip3?|python3?\s+-m\s+pip)\s+install\b"

        return bool(re.search(pattern, command, re.IGNORECASE))

    def handle(self, hook_input: dict) -> HookResult:
        """Block command and explain why sudo pip install is dangerous.

        Args:
            hook_input: Hook input containing the dangerous command

        Returns:
            HookResult with deny decision and explanation
        """
        # Safety check: if command doesn't match, allow
        if not self.matches(hook_input):
            return HookResult(decision=Decision.ALLOW)

        command = hook_input.get("tool_input", {}).get("command", "")

        reason = f"""🚫 BLOCKED: sudo pip install

COMMAND: {command}

WHY BLOCKED:
System-wide pip installs using sudo can cause serious problems:
  • Conflicts with your OS package manager (apt, dnf, pacman, etc.)
  • Breaks OS tools that depend on specific Python package versions
  • Creates permission and ownership issues
  • Bypasses PEP 668 externally-managed environment protections

SAFE alternatives:
  1. Use a virtual environment (RECOMMENDED):
     python -m venv myenv
     source myenv/bin/activate
     pip install <package>

  2. Use --user flag for user-local install:
     pip install --user <package>

  3. Use your OS package manager:
     sudo apt install python3-<package>  # Debian/Ubuntu
     sudo dnf install python3-<package>  # Fedora/RHEL

NEVER use sudo pip install as default behavior."""

        return HookResult(
            decision=Decision.DENY,
            reason=reason,
            context=[],
            guidance=None,
        )
