"""Shared utilities for Stop event handlers.

DRY extraction of common logic used by AutoContinueStopHandler and
HedgingLanguageDetectorHandler. Both handlers need to check stop_hook_active
state and load transcripts — this module provides those as reusable functions.
"""

import json
import logging
import os
from typing import Any, Final

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader

logger = logging.getLogger(__name__)

_STOP_FEEDBACK_PREFIX = "Stop hook feedback:"
_HOOK_BLOCKING_ERROR_TYPE = "hook_blocking_error"
_STOP_EVENT = "Stop"
_DEFAULT_BLOCK_LOOKBACK = 20

# Byte offset representing the start of a file.
_FILE_START_OFFSET: Final[int] = 0
_NEWLINE_BYTE: Final[bytes] = b"\n"
_NEWLINE_STR: Final[str] = "\n"
# Step size for the backward walk. 64 KiB holds far more than 20 transcript
# records in the common case, so the loop almost always runs once.
_TAIL_CHUNK_BYTES: Final[int] = 65_536
# Hard ceiling on the backward walk. Only reached when the trailing records are
# individually enormous (a tool_result carrying megabytes of output). Stopping
# early yields FEWER than ``lookback`` lines rather than degrading to a
# whole-file read — and the block marker this function looks for is always among
# the newest entries, so the newest few megabytes are where it can be.
_MAX_TAIL_SCAN_BYTES: Final[int] = 4_194_304


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


def _read_tail_lines(transcript_path: str, lookback: int) -> list[str]:
    """Return up to the last ``lookback`` complete lines of a file.

    Seeks backwards from EOF in bounded chunks, accumulating until enough
    newlines have been seen. The previous spelling — ``deque(f, maxlen=N)`` —
    declared exactly the same bound but iterated EVERY line of the file to
    honour it: measured at 162 ms against 17 ms for this seek on a 74 MB
    session transcript, and unbounded in growth because transcripts only ever
    append (Plan 00231).

    Reading backwards means the window normally opens mid-record, so the
    leading fragment is discarded — the same correction ``_parse_tail`` makes
    in ``TranscriptReader``. Decoding uses ``errors="replace"`` because a chunk
    boundary can split a multi-byte character; the affected character is always
    inside that discarded leading fragment.

    Args:
        transcript_path: Path to the file to tail.
        lookback: Maximum number of trailing lines to return.

    Returns:
        The trailing lines, oldest first. Fewer than ``lookback`` when the file
        is shorter or when the scan ceiling is reached first.
    """
    with open(transcript_path, "rb") as handle:
        handle.seek(_FILE_START_OFFSET, os.SEEK_END)
        size = handle.tell()
        position = size
        buffer = b""
        while position > _FILE_START_OFFSET and buffer.count(_NEWLINE_BYTE) <= lookback:
            if size - position >= _MAX_TAIL_SCAN_BYTES:
                break
            step = min(_TAIL_CHUNK_BYTES, position)
            position -= step
            handle.seek(position)
            buffer = handle.read(step) + buffer

    lines = buffer.decode("utf-8", errors="replace").split(_NEWLINE_STR)
    if position > _FILE_START_OFFSET:
        # The window opened mid-record; the leading fragment is not a record.
        lines = lines[1:]
    return lines[-lookback:]


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
        tail = _read_tail_lines(transcript_path, lookback)
    except (FileNotFoundError, IsADirectoryError, PermissionError):
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
