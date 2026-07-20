"""Shared utilities for Stop event handlers.

DRY extraction of common logic used by AutoContinueStopHandler and
HedgingLanguageDetectorHandler. Both handlers need to check stop_hook_active
state and load transcripts — this module provides those as reusable functions.
"""

import json
import logging
from collections import deque
from typing import Any

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader

logger = logging.getLogger(__name__)

_STOP_FEEDBACK_PREFIX = "Stop hook feedback:"
_HOOK_BLOCKING_ERROR_TYPE = "hook_blocking_error"
_STOP_EVENT = "Stop"
_DEFAULT_BLOCK_LOOKBACK = 20


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

    Uses a BOUNDED tail read (``load_tail``), not a whole-file parse: every Stop
    handler that calls this only inspects the recent conversation tail (last
    assistant message, last tool_result), and a whole-file parse on a
    multi-hundred-MB transcript blows the client's socket timeout — which the
    daemon then misreports as "not running" (Plan 00177). The tail window is far
    larger than any single message, so the tail accessors are unaffected while
    the dispatch stays in milliseconds regardless of transcript size.

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
    reader.load_tail(str(transcript_path))

    if not reader.is_loaded():
        logger.debug("Transcript not loaded from: %s", transcript_path)
        return None

    return reader


def has_recent_stop_hook_block(
    transcript_path: str | None,
    lookback: int = _DEFAULT_BLOCK_LOOKBACK,
) -> bool:
    """Detect whether the recent transcript tail contains a Stop-hook block marker.

    A genuine Stop-hook re-entry (Claude Code re-fires Stop after a prior block)
    leaves one of two markers in the transcript JSONL:

      1. A user-role entry whose message.content begins with "Stop hook feedback:"
      2. An attachment of type "hook_blocking_error" with hookEvent="Stop"

    Either marker, present within the last ``lookback`` lines of the transcript,
    signals a genuine re-entry. Absence — even when ``stop_hook_active=true`` —
    signals the silent-stop bug where Claude Code spuriously re-fires Stop after
    a tool error or empty turn without a prior block.

    Args:
        transcript_path: Path to the JSONL transcript file (may be None/empty).
        lookback: How many trailing lines to scan. Default: 20.

    Returns:
        True if a block marker is found within the lookback window.
        False on missing path, missing file, decode errors, or no marker.
    """
    if not transcript_path:
        return False

    try:
        with open(transcript_path, encoding="utf-8") as f:
            tail: deque[str] = deque(f, maxlen=lookback)
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return False
    except UnicodeDecodeError:
        return False
    except OSError as exc:
        logger.debug("Failed to read transcript %s: %s", transcript_path, exc)
        return False

    for raw in tail:
        line = raw.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if _entry_has_block_marker(entry):
            return True

    return False


def _entry_has_block_marker(entry: dict[str, Any]) -> bool:
    """Return True if a single transcript entry is a Stop-hook block marker."""
    entry_type = entry.get("type")

    if entry_type == "user":
        message = entry.get("message")
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str) and content.startswith(_STOP_FEEDBACK_PREFIX):
                return True

    if entry_type == "attachment":
        attachment = entry.get("attachment")
        if isinstance(attachment, dict):
            if (
                attachment.get("type") == _HOOK_BLOCKING_ERROR_TYPE
                and attachment.get("hookEvent") == _STOP_EVENT
            ):
                return True

    return False
