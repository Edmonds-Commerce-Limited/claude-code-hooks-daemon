"""Shared session-classification helpers for SessionStart handlers.

DRY extraction: every SessionStart handler that needs to distinguish a
resumed session from a genuinely new one independently duplicated the same
transcript-size heuristic. This module is the single source of truth for
that check.
"""

from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HookInputField

# A transcript file at or below this size is treated as belonging to a NEW
# session (empty, or the small initial stub Claude Code writes before the
# first turn completes), not a resumed one with prior conversation content.
RESUME_SESSION_MIN_TRANSCRIPT_BYTES: Final[int] = 100


def is_resume_session(hook_input: dict[str, Any]) -> bool:
    """Check if this is a resumed session (transcript exists with content).

    Args:
        hook_input: SessionStart hook input

    Returns:
        True if resume, False if new session
    """
    transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
    if not transcript_path:
        return False

    try:
        path = Path(transcript_path)
        if not path.exists():
            return False

        # If file exists and has content (> threshold bytes), it's a resume
        return path.stat().st_size > RESUME_SESSION_MIN_TRANSCRIPT_BYTES

    except (OSError, ValueError):
        return False
