"""Handler to block piping curl/wget output directly to shell.

This handler prevents the dangerous practice of piping network content directly
to bash/sh, which executes untrusted remote code without any inspection and is
a common vector for malware and system compromise.
"""

import re

from claude_code_hooks_daemon.constants.decision import Decision
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult


class CurlPipeShellHandler(Handler):
    """Block curl/wget piped to shell commands.

    Blocks patterns like:
    - curl ... | bash
    - curl ... | sh
    - wget ... | bash
    - wget ... | sh
    - curl ... | sudo bash (especially dangerous)

    These patterns are extremely dangerous because they:
    - Execute untrusted remote code without inspection
    - Provide no opportunity to verify what will be executed
    - Can compromise the entire system
    - Are common vectors for malware and exploits

    Priority: 10 (safety-critical)
    Terminal: True (blocks execution)
    """

    def __init__(self) -> None:
        """Initialize handler with safety-critical priority."""
        super().__init__(
            name=HandlerID.CURL_PIPE_SHELL.display_name,
            priority=Priority.CURL_PIPE_SHELL,
            terminal=True,
        )

    def matches(self, hook_input: dict) -> bool:
        """Check if command pipes curl/wget to shell.

        Matches:
        - curl ... | bash
        - curl ... | sh
        - wget ... | bash
        - wget ... | sh
        - curl ... | sudo bash
        - wget ... | sudo sh

        Case-insensitive matching.

        Args:
            hook_input: Hook input containing tool_name and tool_input

        Returns:
            True if command pipes network content to shell
        """
        # Only process Bash commands
        if hook_input.get("tool_name") != "Bash":
            return False

        # Extract command
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command")
        if not command:
            return False

        # Pattern: (curl|wget) ... | (sudo)? (bash|sh)
        # Matches piping curl or wget output to bash or sh, optionally with sudo
        pattern = r"\b(curl|wget)\b.*\|\s*(sudo\s+)?(bash|sh)\b"

        return bool(re.search(pattern, command, re.IGNORECASE))

    def handle(self, hook_input: dict) -> HookResult:
        """Block command and explain why piping to shell is dangerous.

        Args:
            hook_input: Hook input containing the dangerous command

        Returns:
            HookResult with deny decision and explanation
        """
        # Safety check: if command doesn't match, allow
        if not self.matches(hook_input):
            return HookResult(decision=Decision.ALLOW)

        command = hook_input.get("tool_input", {}).get("command", "")

        reason = f"""🚫 BLOCKED: Piping network content to shell

COMMAND: {command}

WHY BLOCKED:
Piping content from curl/wget directly to bash/sh is a massive security risk:
  • Executes untrusted remote code without inspection
  • No opportunity to verify what will be executed
  • Can compromise your entire system
  • Common vector for malware and exploits

SAFE alternative:
  1. Download the script first:
     curl -O https://example.com/install.sh

  2. Inspect the downloaded file:
     cat install.sh
     # Read and understand what it does

  3. Then execute if safe:
     bash install.sh

NEVER pipe network content directly to a shell."""

        return HookResult(
            decision=Decision.DENY,
            reason=reason,
            context=[],
            guidance=None,
        )
