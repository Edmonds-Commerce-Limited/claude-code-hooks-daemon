"""Handler to block chmod 777 and other dangerous permission patterns.

This handler prevents setting overly permissive file permissions that create
security vulnerabilities by allowing anyone to read, write, and execute files.
"""

import re
from typing import Any

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult


class DangerousPermissionsHandler(Handler):
    """Block chmod 777 and dangerous permission commands.

    Blocks patterns like:
    - chmod 777
    - chmod -R 777
    - chmod a+rwx
    - chmod -R a+rwx

    These permissions are almost never correct and create severe security issues:
    - Allow anyone to read, write, and execute
    - Bypass all file permission security
    - Expose sensitive data
    - Violate principle of least privilege

    Priority: 15 (safety-critical, slightly lower than pip/sudo)
    Terminal: True (blocks execution)
    """

    def __init__(self) -> None:
        """Initialize handler with safety-critical priority."""
        super().__init__(
            name=HandlerID.DANGEROUS_PERMISSIONS.display_name,
            priority=Priority.DANGEROUS_PERMISSIONS,
            terminal=True,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if command sets dangerous permissions (777 or a+rwx).

        Matches:
        - chmod 777
        - chmod -R 777
        - chmod a+rwx
        - chmod -R a+rwx

        Case-sensitive for file permissions.

        Args:
            hook_input: Hook input containing tool_name and tool_input

        Returns:
            True if command sets dangerous permissions
        """
        # Only process Bash commands
        if hook_input.get("tool_name") != "Bash":
            return False

        # Extract command
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command")
        if not command:
            return False

        # Pattern: chmod ... (777|a+rwx)
        # Matches chmod with 777 or a+rwx permissions, optionally with -R flag
        pattern = r"\bchmod\b.*\b(777|a\+rwx)\b"

        return bool(re.search(pattern, command))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block command and explain why 777 permissions are dangerous.

        Args:
            hook_input: Hook input containing the dangerous command

        Returns:
            HookResult with deny decision and explanation
        """
        # Safety check: if command doesn't match, allow
        if not self.matches(hook_input):
            return HookResult(decision=Decision.ALLOW)

        command = hook_input.get("tool_input", {}).get("command", "")

        reason = f"""🚫 BLOCKED: chmod 777 - dangerous permissions

COMMAND: {command}

WHY BLOCKED:
Setting 777 (or a+rwx) permissions creates security vulnerabilities:
  • Allows anyone to read, write, and execute the file
  • Bypasses all file permission security
  • Can expose sensitive data
  • Violates principle of least privilege
  • Often indicates a misunderstanding of permissions

CORRECT permissions:
  • Directories: 755 (owner: rwx, others: r-x)
    chmod 755 mydir/

  • Executable files: 755 (owner: rwx, others: r-x)
    chmod 755 script.sh

  • Regular files: 644 (owner: rw, others: r)
    chmod 644 config.json

  • Private files: 600 (owner: rw, others: none)
    chmod 600 secret.key

If you need broader access, ask the human user for the specific use case.
The correct solution is almost never 777."""

        return HookResult(
            decision=Decision.DENY,
            reason=reason,
            context=[],
            guidance=None,
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for dangerous permissions handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="chmod 777",
                command='echo "chmod 777 /tmp/test_file.txt"',
                description="Blocks chmod 777 (security vulnerability)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"chmod 777",
                    r"security vulnerabilities",
                    r"principle of least privilege",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
            ),
            AcceptanceTest(
                title="chmod a+rwx",
                command='echo "chmod a+rwx /tmp/test_script.sh"',
                description="Blocks chmod a+rwx (equivalent to 777)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"dangerous permissions",
                    r"anyone to read, write, and execute",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
            ),
        ]
