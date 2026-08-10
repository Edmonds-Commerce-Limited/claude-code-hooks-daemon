"""Handler to block sudo pip install commands.

This handler prevents the use of sudo with pip install, which creates
system-wide package installations that can conflict with OS package managers
and break system tools.
"""

import re
from typing import Any

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import OPTIONAL_PATH, SUDO_INVOCATION

# `sudo` + any form of pip install.
#
# Two respellings defeated the original `\bsudo\s+(pip3?|...)` anchor, and both
# are the FIRST thing a real user types:
#   sudo -H pip install ...        - sudo takes its own options
#   sudo /usr/bin/pip install ...  - the binary named by path
# OPTIONAL_SUDO covers the former (and is shared with curl_pipe_shell, which
# had already learned this lesson in isolation); OPTIONAL_PATH covers the
# latter for both `pip` and the `python -m pip` spelling.
_SUDO_PIP_PATTERN = SUDO_INVOCATION + OPTIONAL_PATH + r"(?:pip3?|python3?\s+-m\s+pip)\s+install\b"


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
            handler_id=HandlerID.SUDO_PIP,
            priority=Priority.SUDO_PIP,
            terminal=True,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
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
        # get_bash_command is the CANONICAL accessor: it returns None for
        # non-Bash tools and normalises shell line continuations, so a command
        # split across lines is matched in the same form as a one-line one.
        # Reading tool_input directly skipped that and reopened the hole.
        command = get_bash_command(hook_input)
        if not command:
            return False

        return bool(re.search(_SUDO_PIP_PATTERN, command, re.IGNORECASE))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
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

    def get_claude_md(self) -> str | None:
        return (
            "## sudo_pip — sudo pip install is blocked\n\n"
            "`sudo pip install` (and the `sudo pip3` / `sudo python -m pip` / "
            "`sudo python3 -m pip` variants) is blocked. Installing as root corrupts the "
            "system Python managed by the OS package manager and creates "
            "permission/ownership issues that are painful to recover from.\n\n"
            "**Use a virtualenv or `--user` install instead**:\n\n"
            "```\n"
            "python3 -m venv /tmp/venv && /tmp/venv/bin/pip install <package>\n"
            "# or\n"
            "pip install --user <package>\n"
            "```\n\n"
            "Even in a container running as root, `sudo` adds nothing — drop it and use "
            "a venv."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for sudo pip handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="sudo pip install",
                command='echo "sudo pip install requests"',
                description="Blocks sudo pip install (system-wide corruption risk)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"sudo pip install",
                    r"OS package manager",
                    r"virtual environment",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="sudo python3 -m pip install",
                command='echo "sudo python3 -m pip install numpy"',
                description="Blocks sudo python3 -m pip install",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"sudo pip",
                    r"Conflicts.*OS",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
