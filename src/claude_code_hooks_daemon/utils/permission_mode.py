"""Permission-mode detection helpers.

Claude Code reports its current permission mode via the `permission_mode`
field in every hook input (see CLAUDE/Code/HooksSystem.md). Five values
are valid: "default", "plan", "acceptEdits", "dontAsk", "bypassPermissions".

Auto-approving handlers must only fire in `bypassPermissions` mode — in
any other mode the user has not opted out of the per-tool approval flow,
and the daemon must defer to Claude Code's normal prompting.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.constants import HookInputField

BYPASS_PERMISSIONS_MODE = "bypassPermissions"


def is_bypass_mode(hook_input: Any) -> bool:
    """Return True iff Claude Code reports the session is in bypass mode.

    Defensive against missing keys, None values, unexpected types, and
    unrecognised mode strings — anything other than the exact string
    "bypassPermissions" returns False so the caller defers to Claude
    Code's normal approval flow.
    """
    if not isinstance(hook_input, dict):
        return False
    return hook_input.get(HookInputField.PERMISSION_MODE) == BYPASS_PERMISSIONS_MODE
