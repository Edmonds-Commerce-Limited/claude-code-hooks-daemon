"""Handler to advise on global npm package installations.

This handler provides advisory guidance (non-blocking) when global npm/yarn
packages are installed, suggesting npx as a modern alternative that avoids
global namespace pollution and version conflicts.
"""

import re

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult


class GlobalNpmAdvisorHandler(Handler):
    """Advise on global npm/yarn package installations.

    Provides non-blocking advice for patterns like:
    - npm install -g
    - yarn global add

    Global packages can cause:
    - Version conflicts between projects
    - Difficult package management
    - Global namespace pollution
    - Hard-to-reproduce environments

    Priority: 40 (workflow advice)
    Terminal: False (non-blocking, allows execution)
    """

    def __init__(self) -> None:
        """Initialize handler with workflow advisory priority."""
        super().__init__(
            name=HandlerID.GLOBAL_NPM_ADVISOR.display_name,
            priority=Priority.GLOBAL_NPM_ADVISOR,
            terminal=False,  # Non-blocking
        )

    def matches(self, hook_input: dict) -> bool:
        """Check if command installs global npm/yarn packages.

        Matches:
        - npm install -g
        - npm i -g
        - yarn global add

        Case-insensitive matching.

        Args:
            hook_input: Hook input containing tool_name and tool_input

        Returns:
            True if command installs global packages
        """
        # Only process Bash commands
        if hook_input.get("tool_name") != "Bash":
            return False

        # Extract command
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command")
        if not command:
            return False

        # Pattern: npm install/i -g OR yarn global add
        pattern = r"\b(npm\s+(install|i)\s+-g|yarn\s+global\s+add)\b"

        return bool(re.search(pattern, command, re.IGNORECASE))

    def handle(self, hook_input: dict) -> HookResult:
        """Provide advice about npx alternative (non-blocking).

        Args:
            hook_input: Hook input containing the command

        Returns:
            HookResult with allow decision and advisory context
        """
        # Safety check: if command doesn't match, allow silently
        if not self.matches(hook_input):
            return HookResult(decision=Decision.ALLOW)

        command = hook_input.get("tool_input", {}).get("command", "")

        # Extract package name if possible
        package_match = re.search(
            r"(?:npm\s+(?:install|i)\s+-g|yarn\s+global\s+add)\s+(\S+)",
            command,
            re.IGNORECASE,
        )
        package_name = package_match.group(1) if package_match else "<package>"

        advisory = f"""💡 ADVISORY: Global npm install detected

COMMAND: {command}

CONSIDERATION:
Global npm packages can cause version conflicts and management issues.

ALTERNATIVE (consider using):
  npx {package_name}  # Runs package without global install

Benefits of npx:
  • No global namespace pollution
  • Always uses latest version (or specify version)
  • No installation required
  • Better for one-time commands and tools

Global installs are sometimes necessary for:
  • Development tools you use across all projects
  • CLI tools you run frequently
  • System-wide utilities

Proceeding with global install..."""

        return HookResult(
            decision=Decision.ALLOW,
            reason="",
            context=[advisory],
            guidance=None,
        )
