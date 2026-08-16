"""DaemonLocationGuardHandler - prevent running daemon commands from wrong directory."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.utils.cli_command import (
    daemon_cli_command,
    daemon_cli_command_for_docs,
)

# Match a `cd` whose TARGET is the .claude/hooks-daemon/ directory (or a path
# inside it). The target is a single token that contains no whitespace or
# command separators, so a `cd` into a SAFE directory cannot reach across a
# `;`/`&&`/`|` to a later reference of the config FILE. The directory boundary
# after `hooks-daemon` is a path separator, whitespace, command separator, quote
# or end-of-string — never a `.`, so the config files `.claude/hooks-daemon.yaml`
# and `.claude/hooks-daemon.yaml.example` do NOT match.
_CD_INTO_DAEMON_DIR = re.compile(
    r"\bcd\s+[^\s;&|]*\.claude/hooks-daemon(?:/[^\s;&|]*)?(?=[\s;&|\"']|$)"
)


class DaemonLocationGuardHandler(Handler):
    """Prevent agents from cd-ing into .claude/hooks-daemon and running commands.

    This handler blocks attempts to change directory into the hooks-daemon
    directory, which can confuse agents about where to run daemon CLI commands.
    Daemon commands should always be run from the project root.
    """

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
        """
        if hook_input.get("tool_name") != "Bash":
            return False

        command = hook_input.get("tool_input", {}).get("command", "")

        return bool(_CD_INTO_DAEMON_DIR.search(command))

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
            f"  {daemon_cli_command('status')}\n"
            f"  {daemon_cli_command('restart')}\n"
            f"  {daemon_cli_command('logs')}\n\n"
            "📦 CORRECT UPGRADE PROCESS:\n\n"
            "  # Download latest upgrade script\n"
            "  curl -fsSL https://raw.githubusercontent.com/anthropics/claude-code-hooks-daemon/main/scripts/upgrade.sh -o /tmp/upgrade.sh\n\n"
            "  # Review it\n"
            "  less /tmp/upgrade.sh\n\n"
            "  # Run it (script handles all git operations)\n"
            "  bash /tmp/upgrade.sh --project-root /workspace\n\n"
            "  # Clean up\n"
            "  rm /tmp/upgrade.sh\n\n"
            "💡 The upgrade script handles all git operations internally.\n"
            "   You never need to cd into .claude/hooks-daemon for upgrades.\n\n"
            "⚠️  Manual upgrade (last resort only):\n"
            "    If the script fails, you can temporarily disable this handler:\n"
            "    .claude/hooks-daemon.yaml → daemon_location_guard.enabled: false"
        )

        return HookResult(
            decision=Decision.DENY,
            reason=reason,
            guidance=guidance,
        )

    def get_claude_md(self) -> str | None:
        return (
            "## daemon_location_guard — do not cd into .claude/hooks-daemon/\n\n"
            "Bash commands that change directory into `.claude/hooks-daemon/` (or `cd` "
            "into a daemon-internal subdirectory and then run something) are blocked. "
            "The daemon is an upstream dependency that must remain untouched in client repos.\n\n"
            "**Run daemon CLI from the project root instead** — it always works regardless "
            "of cwd:\n\n"
            "```\n"
            f"{daemon_cli_command_for_docs('status')}\n"
            f"{daemon_cli_command_for_docs('restart')}\n"
            f"{daemon_cli_command_for_docs('logs')}\n"
            "```\n\n"
            "If you need to inspect daemon source for debugging, use `Read` from the project "
            "root with the absolute path — never `cd` in. Do NOT edit anything inside "
            "`.claude/hooks-daemon/`; changes will be overwritten on the next upgrade."
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import RecommendedModel, TestType

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
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
