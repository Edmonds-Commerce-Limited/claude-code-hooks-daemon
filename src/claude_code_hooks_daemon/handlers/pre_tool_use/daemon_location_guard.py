"""DaemonLocationGuardHandler - prevent running daemon commands from wrong directory."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest


class DaemonLocationGuardHandler(Handler):
    """Prevent agents from cd-ing into .claude/hooks-daemon and running commands.

    This handler blocks attempts to change directory into the hooks-daemon
    directory, which can confuse agents about where to run daemon CLI commands.
    Daemon commands should always be run from the project root.
    """

    # Official upgrade command pattern (whitelisted)
    OFFICIAL_UPGRADE_PATTERN = re.compile(
        r"cd\s+\.claude/hooks-daemon\s+&&\s+git\s+pull\s+&&\s+cd\s+\.\./\.\.\s+&&.*upgrade"
    )

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DAEMON_LOCATION_GUARD,
            priority=Priority.DAEMON_LOCATION_GUARD,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match cd commands into .claude/hooks-daemon directory.

        Blocks:
        - cd .claude/hooks-daemon
        - cd /path/.claude/hooks-daemon
        - cd ./.claude/hooks-daemon
        - Compound commands with && that include cd into hooks-daemon

        Allows:
        - cd to other directories
        - ls/grep/other operations on hooks-daemon directory
        - Official upgrade command pattern
        """
        if hook_input.get("tool_name") != "Bash":
            return False

        command = hook_input.get("tool_input", {}).get("command", "")

        # Whitelist the official upgrade command
        if self.OFFICIAL_UPGRADE_PATTERN.search(command):
            return False

        # Match cd into hooks-daemon directory (relative or absolute paths)
        cd_pattern = re.compile(r"\bcd\s+(?:[./]*|/).*?\.claude/hooks-daemon\b")

        return bool(cd_pattern.search(command))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block cd into hooks-daemon with helpful guidance."""
        command = hook_input.get("tool_input", {}).get("command", "")

        reason = (
            f"🚫 BLOCKED: Attempting to cd into .claude/hooks-daemon/\n\n"
            f"COMMAND: {command}\n\n"
            f"WHY BLOCKED:\n"
            f"  • Daemon CLI commands must be run from PROJECT ROOT, not from .claude/hooks-daemon/\n"
            f"  • Running commands from hooks-daemon directory causes path confusion\n"
            f"  • All daemon operations expect to be run from project root\n"
        )

        guidance = (
            "✅ CORRECT USAGE:\n"
            "  Run daemon commands from project root:\n\n"
            "  PYTHON=/workspace/untracked/venv/bin/python\n"
            "  $PYTHON -m claude_code_hooks_daemon.daemon.cli status\n"
            "  $PYTHON -m claude_code_hooks_daemon.daemon.cli restart\n"
            "  $PYTHON -m claude_code_hooks_daemon.daemon.cli logs\n\n"
            "📦 OFFICIAL UPGRADE COMMAND (whitelisted):\n"
            "  cd .claude/hooks-daemon && git pull && cd ../.. && ./scripts/upgrade.sh\n\n"
            "💡 TIP: Never cd into .claude/hooks-daemon/ unless running the official upgrade command."
        )

        return HookResult(
            decision=Decision.DENY,
            reason=reason,
            guidance=guidance,
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import TestType

        return [
            AcceptanceTest(
                title="daemon location guard blocks cd into hooks-daemon",
                command='echo "cd .claude/hooks-daemon"',
                description=(
                    "Verify handler blocks attempts to cd into .claude/hooks-daemon. "
                    "Should deny with guidance on running daemon commands from project root."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"hooks-daemon",
                    r"PROJECT ROOT",
                    r"CORRECT USAGE",
                ],
                safety_notes="Using echo to test blocking - safe command",
                test_type=TestType.BLOCKING,
                requires_event="PreToolUse:Bash",
            ),
            AcceptanceTest(
                title="daemon location guard allows official upgrade command",
                command='echo "cd .claude/hooks-daemon && git pull && cd ../.. && ./scripts/upgrade.sh"',
                description=(
                    "Verify handler whitelists the official upgrade command pattern. "
                    "Should allow the official upgrade workflow."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Using echo to test - safe command",
                test_type=TestType.BLOCKING,
                requires_event="PreToolUse:Bash",
            ),
        ]
