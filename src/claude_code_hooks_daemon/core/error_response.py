#!/usr/bin/env python3
"""CLI utility for generating hook error responses.

Used by bash hook scripts when the daemon fails to start or respond.
Ensures DRY - single source of truth for error message formatting.

Usage:
    python -m claude_code_hooks_daemon.core.error_response <event_name> <error_type> <error_details>

Example:
    python -m claude_code_hooks_daemon.core.error_response Stop daemon_startup_failed "Failed to start"
"""

import json
import sys
from typing import Any

from claude_code_hooks_daemon.core.hook_result import HookResult


def generate_daemon_error_response(
    event_name: str, error_type: str, error_details: str
) -> dict[str, Any]:
    """Generate proper error response for daemon failures.

    Args:
        event_name: Hook event type (PreToolUse, Stop, etc.)
        error_type: Error type identifier
        error_details: Detailed error message

    Returns:
        JSON-serializable dict in proper hook response format
    """
    # Create error context with enhanced messaging for daemon failures
    context_lines = [
        "⚠️ HOOKS DAEMON ERROR - PROTECTION NOT ACTIVE ⚠️",
        "",
        f"ERROR TYPE: {error_type}",
        f"ERROR DETAILS: {error_details}",
        "",
        "🛑 CRITICAL: You MUST stop work immediately.",
        "",
        "The hooks daemon is not functioning. This means:",
        "- Destructive git operations are NOT being blocked",
        "- Code quality checks are NOT running",
        "- Safety guardrails are NOT active",
        "",
        "RECOMMENDED ACTIONS:",
        "1. STOP all current tasks immediately",
        "2. Inform the user that hooks protection is down",
        "3. Run: python -m claude_code_hooks_daemon.daemon.cli status",
        "4. Run: python -m claude_code_hooks_daemon.daemon.cli logs",
        "5. Check daemon installation in .claude/hooks-daemon/",
        "6. Restart daemon: python -m claude_code_hooks_daemon.daemon.cli restart",
        "",
        "DO NOT continue work until hooks are verified working.",
    ]

    # For Stop/SubagentStop events, we need deny decision to show the error
    # (allow with context doesn't display for Stop events in Claude Code)
    if event_name in ("Stop", "SubagentStop"):
        result = HookResult.deny(
            reason="Hooks daemon not running - protection not active",
            context=context_lines,
        )
    else:
        # For other events, use standard error result (fail-open with context)
        result = HookResult.allow(context=context_lines)

    # Convert to proper Claude Code format
    return result.to_json(event_name)


def main() -> None:
    """Main entry point for CLI."""
    if len(sys.argv) != 4:
        print(
            "Usage: python -m claude_code_hooks_daemon.core.error_response "
            "<event_name> <error_type> <error_details>",
            file=sys.stderr,
        )
        sys.exit(1)

    event_name = sys.argv[1]
    error_type = sys.argv[2]
    error_details = sys.argv[3]

    response = generate_daemon_error_response(event_name, error_type, error_details)
    print(json.dumps(response))


if __name__ == "__main__":
    main()
