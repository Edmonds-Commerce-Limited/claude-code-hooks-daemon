"""Shared utilities for Stop event handlers.

DRY extraction of common logic used by AutoContinueStopHandler and
HedgingLanguageDetectorHandler. Both handlers need to check stop_hook_active
state and load transcripts — this module provides those as reusable functions.
"""

import logging
from typing import Any

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader

logger = logging.getLogger(__name__)


def is_stop_hook_active(hook_input: dict[str, Any]) -> bool:
    """Check if stop hook is in re-entry state (prevents infinite loops).

    Claude Code may send this field as snake_case (stop_hook_active) or
    camelCase (stopHookActive). We check BOTH variants.

    Args:
        hook_input: Hook input dictionary

    Returns:
        True if stop hook is active (re-entry detected)
    """
    return bool(
        hook_input.get("stop_hook_active", False) or hook_input.get("stopHookActive", False)
    )


def get_transcript_reader(hook_input: dict[str, Any]) -> TranscriptReader | None:
    """Load a TranscriptReader from hook_input's transcript_path.

    Args:
        hook_input: Hook input dictionary containing transcript_path

    Returns:
        Loaded TranscriptReader, or None if path missing/invalid/file not found
    """
    transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
    if not transcript_path:
        logger.debug("No transcript_path in hook_input")
        return None

    reader = TranscriptReader()
    reader.load(str(transcript_path))

    if not reader.is_loaded():
        logger.debug("Transcript not loaded from: %s", transcript_path)
        return None

    return reader
