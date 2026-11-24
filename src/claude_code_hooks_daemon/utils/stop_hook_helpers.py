"""Shared utilities for Stop event handlers.

DRY extraction of common logic used by Stop handlers that need to check
stop_hook_active state and load transcripts. Extracted when three handlers
shared it; ``AutoContinueStopHandler`` is now its only importer (Plan 00237
removed the other two, which were unreachable behind it), so the sharing is
latent rather than live. The module stays as a public ``utils`` export that a
project-level Stop handler can use, and because the next Stop handler will
need exactly this.
"""

import json
import logging
import os
from typing import Any, Final

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

_STOP_FEEDBACK_PREFIX = "Stop hook feedback:"
_HOOK_BLOCKING_ERROR_TYPE = "hook_blocking_error"
_STOP_EVENT = "Stop"
_QUEUED_COMMAND_TYPE = "queued_command"
_QUEUED_PROMPT_MODE = "prompt"
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

_TASK_STATUS_KEY: Final[str] = "status"
_TASK_RUNNING: Final[str] = "running"


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


def reported_background_tasks(hook_input: dict[str, Any]) -> list[Any]:
    """The Stop payload's ``background_tasks`` list, or ``[]`` for "no information".

    The field is CONDITIONAL (``contracts/claude-code-hooks/Stop.json``): absent
    means *unknown*, never *empty*, and a non-list value is malformed. All three
    of absent, empty and malformed return ``[]`` because every caller's response
    to them is identical.
    """
    tasks = hook_input.get(HookInputField.BACKGROUND_TASKS)
    return tasks if isinstance(tasks, list) else []


def running_background_tasks(hook_input: dict[str, Any]) -> list[dict[str, Any]]:
    """The reported background tasks that are dicts carrying ``status == "running"``."""
    return [
        task
        for task in reported_background_tasks(hook_input)
        if isinstance(task, dict) and task.get(_TASK_STATUS_KEY) == _TASK_RUNNING
    ]


def has_running_background_task(hook_input: dict[str, Any]) -> bool:
    """True when a reported background task carries ``status == "running"``."""
    return bool(running_background_tasks(hook_input))


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


def transcript_is_readable(transcript_path: str | None) -> bool:
    """Return True when the transcript file can be opened for reading.

    Separates "the transcript cannot be read" (no path, missing file, a
    directory, no permission) from "the transcript was read and holds no block
    marker". ``has_recent_stop_hook_block`` returns False for both; a Stop
    handler that must stand down on a re-entry it cannot verify needs to tell
    them apart (N411).

    Args:
        transcript_path: Path to the JSONL transcript file (may be None/empty).

    Returns:
        True if the file opens for reading, False otherwise.
    """
    if not transcript_path:
        return False
    try:
        with open(transcript_path, "rb"):
            return True
    except OSError:
        return False


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
        log_and_continue(
            logger,
            exc,
            reason=f"an unreadable transcript {transcript_path} shows no recent stop-hook block (False), so the stop proceeds on its other signals",
            level=logging.DEBUG,
        )
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


def recent_stop_hook_block_texts(
    transcript_path: str | None,
    lookback: int = _DEFAULT_BLOCK_LOOKBACK,
) -> tuple[str, ...]:
    """The text of every Stop-hook block marker in the recent tail, oldest first.

    Same markers and window as :func:`has_recent_stop_hook_block`, but returns
    what each block SAID, so a handler can tell its own refusal (by rule id)
    from another handler's (Plan 00636 F3). An attachment whose blocking error
    carries no readable text yields ``""``.

    Returns:
        The texts, or ``()`` on a missing path or file. Other read errors raise
        ``OSError``: a caller that must stand down on an unverifiable re-entry
        checks :func:`transcript_is_readable` first and treats a raise the same.
    """
    return _block_texts(transcript_path, lookback, since_last_prompt=False)


def recent_stop_hook_block_texts_this_chain(
    transcript_path: str | None,
    lookback: int = _DEFAULT_BLOCK_LOOKBACK,
) -> tuple[str, ...]:
    """Like :func:`recent_stop_hook_block_texts`, but only the CURRENT stop chain's blocks.

    A stop chain is the run of turns since the last real user prompt: a prompt
    (a cron tick or a human message) starts a new chain, while a Stop-hook
    feedback entry and a tool result do not. Blocks before that prompt belong to
    an earlier chain and are dropped (Plan 00636 N5). With no prompt in the
    window the whole window is the chain.
    """
    return _block_texts(transcript_path, lookback, since_last_prompt=True)


def _block_texts(
    transcript_path: str | None, lookback: int, *, since_last_prompt: bool
) -> tuple[str, ...]:
    """The block marker texts in the tail, optionally only those after the last real prompt."""
    if not transcript_path:
        return ()
    try:
        tail = _read_tail_lines(transcript_path, lookback)
    except (FileNotFoundError, IsADirectoryError):
        return ()
    texts: list[str] = []
    for raw in tail:
        line = raw.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            log_and_continue(
                logger,
                exc,
                reason="a transcript line that is not JSON (a torn tail write) carries no block marker, so it is skipped",
                level=logging.DEBUG,
            )
            continue
        if isinstance(entry, dict):
            text = _entry_block_text(entry)
            if text is not None:
                texts.append(text)
            elif since_last_prompt and _entry_is_real_prompt(entry):
                texts.clear()
    return tuple(texts)


def _entry_is_real_prompt(entry: dict[str, Any]) -> bool:
    """Whether an entry starts a new stop chain.

    Counted: any user message with text (a human message, a cron tick, a task
    notification, a bus delivery, an ``isMeta`` notice) and a prompt the human
    typed mid-continuation, which Claude Code records only as a
    ``queued_command`` attachment. Not counted: a tool result, and an
    auto-compaction summary (``isCompactSummary``). Over-counting costs at most
    one extra refusal, bounded by Claude Code's consecutive-block override.
    """
    if entry.get("type") == "attachment":
        attachment = entry.get("attachment")
        return (
            isinstance(attachment, dict)
            and attachment.get("type") == _QUEUED_COMMAND_TYPE
            and attachment.get("commandMode") == _QUEUED_PROMPT_MODE
        )
    if entry.get("type") != "user" or entry.get("isCompactSummary") is True:
        return False
    message = entry.get("message")
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "text" for b in content)
    return False


def _entry_block_text(entry: dict[str, Any]) -> str | None:
    """The text of a Stop-hook block marker entry, or None when it is not one."""
    entry_type = entry.get("type")

    if entry_type == "user":
        message = entry.get("message")
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str) and content.startswith(_STOP_FEEDBACK_PREFIX):
                return content

    if entry_type == "attachment":
        attachment = entry.get("attachment")
        if (
            isinstance(attachment, dict)
            and attachment.get("type") == _HOOK_BLOCKING_ERROR_TYPE
            and attachment.get("hookEvent") == _STOP_EVENT
        ):
            error = attachment.get("blockingError")
            if isinstance(error, dict):
                error = error.get("blockingError")
            return error if isinstance(error, str) else ""

    return None


def _entry_has_block_marker(entry: dict[str, Any]) -> bool:
    """Return True if a single transcript entry is a Stop-hook block marker."""
    return _entry_block_text(entry) is not None
