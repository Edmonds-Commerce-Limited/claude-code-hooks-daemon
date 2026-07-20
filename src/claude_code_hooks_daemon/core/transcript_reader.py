"""JSONL transcript reader for Claude Code conversation transcripts.

Lazy, cached parser that provides read-only access to conversation
history for cross-handler analysis via the DaemonDataLayer.

Usage:
    reader = TranscriptReader()
    reader.load("/path/to/transcript.jsonl")
    messages = reader.get_messages()
    tools = reader.get_tool_uses()
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants.tools import ToolName

logger = logging.getLogger(__name__)

# Byte offset representing the start of a file — no realignment needed here.
_FILE_START_OFFSET = 0
# Newline byte used to realign a mid-line seek to the next full JSONL record.
_NEWLINE_BYTE = b"\n"
# Newline used to split a decoded tail chunk into individual JSONL records.
_NEWLINE_STR = "\n"
# Default bounded tail-read window for load_tail(). 1 MiB is far larger than any
# assistant text message or tool_result, so the recent-conversation accessors the
# Stop handlers need (last assistant message, last tool_result) are always inside
# it — while a multi-hundred-MB transcript is never parsed whole (Plan 00177).
_DEFAULT_TAIL_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class ContentBlock:
    """A single content block from within a message.

    Messages in real Claude Code transcripts contain arrays of content blocks,
    each of which is either a text block or a tool_use block.

    Attributes:
        block_type: Block type ("text", "tool_use", etc.)
        text: Text content (for "text" blocks)
        tool_name: Tool name (for "tool_use" blocks)
        tool_input: Tool input data (for "tool_use" blocks)
        raw: Original parsed dict for accessing extra fields
    """

    block_type: str
    text: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass(frozen=True, slots=True)
class TranscriptMessage:
    """A single message from the conversation transcript.

    Attributes:
        role: Message role (human, assistant)
        content: Message text content (concatenated from text blocks)
        raw: Original parsed JSON dict for accessing extra fields
        content_blocks: Parsed content blocks from the message
        uuid: Unique identifier from the transcript entry (None if absent)
    """

    role: str
    content: str
    raw: dict[str, Any] = field(repr=False)
    content_blocks: tuple[ContentBlock, ...] = ()
    uuid: str | None = None


@dataclass(frozen=True, slots=True)
class ToolUse:
    """A tool use entry from the conversation transcript.

    Attributes:
        tool_name: Name of the tool (Bash, Write, Read, etc.)
        tool_input: Tool input data dictionary
        raw: Original parsed JSON dict for accessing extra fields
    """

    tool_name: str
    tool_input: dict[str, Any]
    raw: dict[str, Any] = field(repr=False)


class TranscriptReader:
    """Lazy, cached parser for Claude Code JSONL transcripts.

    Key design decisions:
    - Lazy loading: Don't parse until first query
    - Cached: Parse once, cache results until transcript path changes
    - Read-only: Never modify transcript files
    - Streaming: Read JSONL lines one at a time (not entire file into memory)
    """

    __slots__ = ("_loaded", "_messages", "_path", "_tool_uses")

    def __init__(self) -> None:
        """Initialise with empty state."""
        self._path: str | None = None
        self._loaded = False
        self._messages: list[TranscriptMessage] = []
        self._tool_uses: list[ToolUse] = []

    def load(self, transcript_path: str) -> None:
        """Load and parse a JSONL transcript file.

        If the same path is loaded again, uses cached results.
        If a different path is loaded, resets and re-parses.
        If the file doesn't exist, stays unloaded.

        Args:
            transcript_path: Absolute path to .jsonl transcript file
        """
        # Same path - use cache
        if self._path == transcript_path and self._loaded:
            return

        # Reset state for new path
        self._messages = []
        self._tool_uses = []
        self._path = transcript_path
        self._loaded = False

        try:
            path = Path(transcript_path)
            if not path.exists():
                logger.warning("Transcript file not found: %s", transcript_path)
                return
        except Exception as e:
            logger.debug("TranscriptReader: Error checking path %s: %s", transcript_path, e)
            return

        self._parse(path)
        self._loaded = True

        logger.debug(
            "TranscriptReader: Loaded %d messages and %d tool uses from %s",
            len(self._messages),
            len(self._tool_uses),
            transcript_path,
        )

    def load_tail(self, transcript_path: str, max_bytes: int = _DEFAULT_TAIL_BYTES) -> None:
        """Load and parse only the last ``max_bytes`` of a JSONL transcript.

        Unlike ``load()``, which materialises the ENTIRE file, ``load_tail()``
        seeks to ``max(0, size - max_bytes)`` and parses only the trailing
        records. The Stop hot path needs only the recent conversation tail (last
        assistant message, last tool_result), so a bounded read keeps a Stop
        dispatch in milliseconds even on a multi-hundred-MB transcript — the
        whole-file parse otherwise blows the client socket timeout and is
        misreported as a dead daemon (Plan 00177).

        Always re-reads (no path cache short-circuit): the freshness poll that
        calls this must observe freshly-appended content on each invocation.

        The trailing records populate the SAME ``self._messages`` /
        ``self._tool_uses`` lists that every accessor reads, so ``load_tail()``
        is transparently substitutable for ``load()`` for any consumer that only
        inspects the recent tail.

        Args:
            transcript_path: Absolute path to .jsonl transcript file
            max_bytes: Maximum number of trailing bytes to read and parse
        """
        self._messages = []
        self._tool_uses = []
        self._path = transcript_path
        self._loaded = False

        try:
            path = Path(transcript_path)
            if not path.exists():
                logger.warning("Transcript file not found: %s", transcript_path)
                return
            size = path.stat().st_size
        except Exception as e:
            # Parity with load(): a path-resolution/stat glitch degrades to an
            # unloaded reader (fail-safe for the Stop dispatch), logged at debug.
            logger.debug("TranscriptReader: Error checking path %s: %s", transcript_path, e)
            return

        if size > _FILE_START_OFFSET:
            self._parse_tail(path, size, max_bytes)
        self._loaded = True

        logger.debug(
            "TranscriptReader: Tail-loaded %d messages and %d tool uses from %s (<=%d bytes)",
            len(self._messages),
            len(self._tool_uses),
            transcript_path,
            max_bytes,
        )

    def _parse(self, path: Path) -> None:
        """Parse a whole JSONL file line by line.

        Supports two formats:
        - Real Claude Code format: {"type": "message", "message": {"role": ..., "content": [...]}}
        - Legacy/test format: {"type": "human"/"assistant", "message": {"content": ...}}

        Skips malformed lines and lines without a 'type' field.

        Args:
            path: Path to JSONL file
        """
        try:
            with path.open("r") as f:
                for line in f:
                    self._ingest_record(line)
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("TranscriptReader: Failed to read %s: %s", path, e)
        except Exception as e:
            logger.error("TranscriptReader: Unexpected error reading %s: %s", path, e)

    def _parse_tail(self, path: Path, size: int, max_bytes: int) -> None:
        """Parse only the trailing ``max_bytes`` of the file.

        Seeks to ``max(0, size - max_bytes)`` and reads to EOF. When the window
        begins after the file start it almost always lands mid-record, so the
        partial first line is discarded (a truncated JSON fragment is not a valid
        record) before parsing every following complete record. The same
        record-ingest path as ``_parse`` is used, so accessors behave identically.

        Args:
            path: Path to JSONL file
            size: Current file size in bytes (already stat()-ed by the caller)
            max_bytes: Maximum number of trailing bytes to read
        """
        start = max(_FILE_START_OFFSET, size - max_bytes)
        try:
            with path.open("rb") as f:
                f.seek(start)
                chunk = f.read()
            text = chunk.decode("utf-8", errors="replace")
            lines = text.split(_NEWLINE_STR)
            if start > _FILE_START_OFFSET and lines:
                # The window began mid-record; drop the partial leading fragment.
                lines = lines[1:]
            for line in lines:
                self._ingest_record(line)
        except (OSError, UnicodeDecodeError, ValueError) as e:
            logger.debug("TranscriptReader: Failed tail read %s: %s", path, e)
        except Exception as e:
            # Mirror _parse's broad, LOGGED catch: an unexpected read error must
            # degrade to an empty reader (fail-safe for the Stop dispatch), never
            # crash the handler. Logged at error level — not silently hidden.
            logger.error("TranscriptReader: Unexpected error tail-reading %s: %s", path, e)

    def _ingest_record(self, line: str) -> None:
        """Parse a single JSONL line and append any message/tool-use it yields.

        Shared by ``_parse`` (whole file) and ``_parse_tail`` (bounded tail) so
        both produce identical accessor state. Malformed JSON, non-dict records,
        and records without a 'type' field are skipped.

        Args:
            line: One raw JSONL line (surrounding whitespace is stripped)
        """
        line = line.strip()
        if not line:
            return

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("TranscriptReader: Skipping malformed JSON line")
            return

        if not isinstance(data, dict):
            return

        entry_type = data.get("type")
        if entry_type is None:
            return

        if entry_type == "message":
            # Real Claude Code format
            self._parse_message_entry(data)
        elif entry_type in ("human", "assistant"):
            # Legacy format: type=human/assistant with message.content
            # Real transcripts use this format WITH content blocks (list),
            # so delegate to _parse_message_entry for proper block parsing.
            message_data = data.get("message", {})
            if not isinstance(message_data, dict):
                self._messages.append(
                    TranscriptMessage(role=entry_type, content="", raw=data, uuid=data.get("uuid"))
                )
            else:
                # Inject role into message dict for _parse_message_entry
                if "role" not in message_data:
                    message_data = {**message_data, "role": entry_type}
                self._parse_message_entry({**data, "message": message_data})
        elif entry_type == "tool_use":
            tool_name = data.get("tool_name", "")
            tool_input = data.get("tool_input", {})
            self._tool_uses.append(ToolUse(tool_name=tool_name, tool_input=tool_input, raw=data))

    def _parse_message_entry(self, data: dict[str, Any]) -> None:
        """Parse a real Claude Code message entry (type=message).

        Extracts role from message.role, parses content blocks,
        and concatenates text blocks into a single content string.

        Args:
            data: Parsed JSON dict with type=message
        """
        message = data.get("message", {})
        if not isinstance(message, dict):
            return

        role = message.get("role", "")
        if not role:
            return

        entry_uuid = data.get("uuid")
        raw_content = message.get("content", [])

        # Handle string content (not a list of blocks)
        if isinstance(raw_content, str):
            self._messages.append(
                TranscriptMessage(role=role, content=raw_content, raw=data, uuid=entry_uuid)
            )
            return

        # Parse content block list
        if not isinstance(raw_content, list):
            self._messages.append(
                TranscriptMessage(role=role, content="", raw=data, uuid=entry_uuid)
            )
            return

        blocks: list[ContentBlock] = []
        text_parts: list[str] = []

        for block_data in raw_content:
            if isinstance(block_data, str):
                text_parts.append(block_data)
                blocks.append(ContentBlock(block_type="text", text=block_data, raw={}))
            elif isinstance(block_data, dict):
                block_type = block_data.get("type", "")
                if block_type == "text":
                    text = block_data.get("text", "")
                    text_parts.append(text)
                    blocks.append(ContentBlock(block_type="text", text=text, raw=block_data))
                elif block_type == "tool_use":
                    tool_name = block_data.get("name", "")
                    tool_input = block_data.get("input", {})
                    blocks.append(
                        ContentBlock(
                            block_type="tool_use",
                            tool_name=tool_name,
                            tool_input=tool_input,
                            raw=block_data,
                        )
                    )
                else:
                    blocks.append(ContentBlock(block_type=block_type, raw=block_data))

        content = " ".join(text_parts)
        self._messages.append(
            TranscriptMessage(
                role=role,
                content=content,
                raw=data,
                content_blocks=tuple(blocks),
                uuid=entry_uuid,
            )
        )

    def read_incremental(
        self, transcript_path: str, byte_offset: int
    ) -> tuple[list[TranscriptMessage], int]:
        """Read new messages from transcript starting at byte offset.

        Seeks to byte_offset, reads only new lines, and parses them.
        Falls back to reading from start if offset is beyond file size.

        Args:
            transcript_path: Path to JSONL transcript file
            byte_offset: Byte position to start reading from

        Returns:
            Tuple of (new_messages, new_byte_offset)
        """
        path = Path(transcript_path)
        if not path.exists():
            return [], byte_offset

        file_size = path.stat().st_size
        if file_size == 0:
            return [], 0

        # Fall back to start if offset is invalid
        if byte_offset > file_size:
            byte_offset = 0

        messages: list[TranscriptMessage] = []
        new_offset = byte_offset

        try:
            with path.open("rb") as f:
                # A non-zero offset may land mid-line (the stored value is a
                # byte position, not necessarily a record boundary). Decide
                # whether realignment is needed by inspecting the byte directly
                # before the offset: if it is a newline (or the offset is the
                # file start) the offset already sits on a record boundary and
                # no fragment must be discarded. Otherwise we are mid-line, so
                # advance past the partial fragment to the next newline and
                # parse only complete JSONL records from there.
                if byte_offset != _FILE_START_OFFSET:
                    f.seek(byte_offset - 1)
                    preceding_byte = f.read(1)
                    if preceding_byte != _NEWLINE_BYTE:
                        # Mid-line: discard the partial fragment up to and
                        # including the next newline. readline() leaves the
                        # cursor at the start of the following complete record.
                        f.readline()
                else:
                    f.seek(byte_offset)

                for raw_line in f:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if not isinstance(data, dict):
                        continue

                    entry_type = data.get("type")
                    entry_uuid = data.get("uuid")

                    if entry_type == "message":
                        msg = self._parse_entry_to_message(data, entry_uuid)
                        if msg:
                            messages.append(msg)
                    elif entry_type in ("human", "assistant", "user"):
                        message_data = data.get("message", {})
                        if isinstance(message_data, dict):
                            if "role" not in message_data:
                                message_data = {**message_data, "role": entry_type}
                            msg = self._parse_entry_to_message(
                                {**data, "message": message_data}, entry_uuid
                            )
                            if msg:
                                messages.append(msg)

                new_offset = f.tell()
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("TranscriptReader: Failed incremental read %s: %s", path, e)

        return messages, new_offset

    def _parse_entry_to_message(
        self, data: dict[str, Any], entry_uuid: str | None
    ) -> TranscriptMessage | None:
        """Parse a single entry dict into a TranscriptMessage without storing it.

        Args:
            data: Parsed JSON dict with message field
            entry_uuid: UUID from the entry

        Returns:
            TranscriptMessage or None if entry is not a valid message
        """
        message = data.get("message", {})
        if not isinstance(message, dict):
            return None

        role = message.get("role", "")
        if not role:
            return None

        raw_content = message.get("content", [])

        if isinstance(raw_content, str):
            return TranscriptMessage(role=role, content=raw_content, raw=data, uuid=entry_uuid)

        if not isinstance(raw_content, list):
            return TranscriptMessage(role=role, content="", raw=data, uuid=entry_uuid)

        blocks: list[ContentBlock] = []
        text_parts: list[str] = []

        for block_data in raw_content:
            if isinstance(block_data, str):
                text_parts.append(block_data)
                blocks.append(ContentBlock(block_type="text", text=block_data, raw={}))
            elif isinstance(block_data, dict):
                block_type = block_data.get("type", "")
                if block_type == "text":
                    text = block_data.get("text", "")
                    text_parts.append(text)
                    blocks.append(ContentBlock(block_type="text", text=text, raw=block_data))
                elif block_type == "tool_use":
                    tool_name = block_data.get("name", "")
                    tool_input = block_data.get("input", {})
                    blocks.append(
                        ContentBlock(
                            block_type="tool_use",
                            tool_name=tool_name,
                            tool_input=tool_input,
                            raw=block_data,
                        )
                    )
                else:
                    blocks.append(ContentBlock(block_type=block_type, raw=block_data))

        content = " ".join(text_parts)
        return TranscriptMessage(
            role=role,
            content=content,
            raw=data,
            content_blocks=tuple(blocks),
            uuid=entry_uuid,
        )

    @staticmethod
    def filter_assistant_messages(
        messages: list[TranscriptMessage],
    ) -> list[TranscriptMessage]:
        """Filter a list of messages to only assistant role messages.

        Args:
            messages: List of TranscriptMessage to filter

        Returns:
            List containing only messages with role='assistant'
        """
        return [m for m in messages if m.role == "assistant"]

    def is_loaded(self) -> bool:
        """Check if a transcript has been successfully loaded.

        Returns:
            True if transcript is loaded and parsed
        """
        return self._loaded

    def get_messages(self) -> list[TranscriptMessage]:
        """Get all messages from the transcript.

        Returns:
            List of TranscriptMessage in chronological order
        """
        return list(self._messages)

    def get_tool_uses(self) -> list[ToolUse]:
        """Get all tool use entries from the transcript.

        Returns:
            List of ToolUse in chronological order
        """
        return list(self._tool_uses)

    def get_last_n_messages(self, n: int) -> list[TranscriptMessage]:
        """Get the last N messages from the transcript.

        Args:
            n: Number of messages to return

        Returns:
            List of last N messages in chronological order
        """
        if n <= 0:
            return []
        return list(self._messages[-n:])

    def search_messages(self, pattern: str) -> list[TranscriptMessage]:
        """Search messages for a pattern (case-insensitive).

        Args:
            pattern: Text pattern to search for

        Returns:
            List of messages containing the pattern
        """
        pattern_lower = pattern.lower()
        return [msg for msg in self._messages if pattern_lower in msg.content.lower()]

    def get_last_assistant_message(self) -> TranscriptMessage | None:
        """Get the last assistant message from the transcript.

        Returns:
            Last assistant TranscriptMessage, or None if no assistant messages
        """
        for msg in reversed(self._messages):
            if msg.role == "assistant":
                return msg
        return None

    def get_last_assistant_text(self) -> str:
        """Get the text content of the last assistant message.

        Convenience method that returns the content string directly.

        Returns:
            Text content of last assistant message, or empty string
        """
        msg = self.get_last_assistant_message()
        return msg.content if msg else ""

    def last_assistant_used_tool(self, tool_name: str) -> bool:
        """Check if the last assistant message used a specific tool.

        Scans content_blocks of the last assistant message for a tool_use
        block matching the given tool name.

        Args:
            tool_name: Tool name to check for (e.g. "AskUserQuestion")

        Returns:
            True if the last assistant message contains a tool_use block
            with the given tool name
        """
        msg = self.get_last_assistant_message()
        if not msg:
            return False
        return any(
            block.block_type == "tool_use" and block.tool_name == tool_name
            for block in msg.content_blocks
        )

    def get_last_tool_use_in_message(self) -> ContentBlock | None:
        """Get the last tool_use content block from the last assistant message.

        Returns:
            Last tool_use ContentBlock from last assistant message, or None
        """
        msg = self.get_last_assistant_message()
        if not msg:
            return None
        for block in reversed(msg.content_blocks):
            if block.block_type == "tool_use":
                return block
        return None

    def get_last_tool_result_text(self) -> str:
        """Get text content of the last tool_result block from the transcript.

        Looks for the most recent user/human message containing a tool_result
        content block and returns its text content. Handles both string and
        structured (list of text blocks) content formats.

        Returns:
            Text content of last tool result, or empty string if none found
        """
        for msg in reversed(self._messages):
            if msg.role in ("user", "human"):
                raw_message = msg.raw.get("message", {})
                if not isinstance(raw_message, dict):
                    continue
                raw_content = raw_message.get("content", [])
                if not isinstance(raw_content, list):
                    continue
                for block in reversed(raw_content):
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        content = block.get("content", "")
                        if isinstance(content, str):
                            return content
                        if isinstance(content, list):
                            texts = [
                                item.get("text", "")
                                for item in content
                                if isinstance(item, dict) and item.get("type") == "text"
                            ]
                            return " ".join(text for text in texts if text)
        return ""

    def get_tool_result_text_by_id(self, tool_use_id: str) -> str | None:
        """Return the text of the tool_result whose tool_use_id matches.

        Scans backwards for a user/human message containing a tool_result block
        whose ``tool_use_id`` equals the given id, and returns its text content
        (string or joined text blocks). Returns None when no matching
        tool_result exists. Pairing by id (rather than "the most recent
        tool_result of any tool") ensures a tool_use is matched to ITS OWN
        result even when an unrelated tool ran afterwards.

        Args:
            tool_use_id: The id of the tool_use whose result is wanted

        Returns:
            The matching tool_result's text, or None if not found
        """
        if not tool_use_id:
            return None
        for msg in reversed(self._messages):
            if msg.role not in ("user", "human"):
                continue
            raw_message = msg.raw.get("message", {})
            if not isinstance(raw_message, dict):
                continue
            raw_content = raw_message.get("content", [])
            if not isinstance(raw_content, list):
                continue
            for block in raw_content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_result":
                    continue
                if block.get("tool_use_id") != tool_use_id:
                    continue
                content = block.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    texts = [
                        item.get("text", "")
                        for item in content
                        if isinstance(item, dict) and item.get("type") == "text"
                    ]
                    return " ".join(text for text in texts if text)
                return ""
        return None

    def last_tool_result_was_error(self) -> bool:
        """Return True if ANY tool_result block in the latest user message errored.

        Scans backwards for the most recent user/human message containing one
        or more tool_result blocks. Returns True if ANY of those blocks has a
        truthy ``is_error`` field. A turn may batch multiple tool_results (one
        per tool_use); inspecting only the last block would silently miss a
        failing block that is not last, skipping the Edit-on-unread-file
        recovery path. Used by AutoContinueStopHandler to detect the recovery
        pattern: tool_use Edit → tool_result is_error=true → silent stop →
        specific recovery instruction.
        """
        for msg in reversed(self._messages):
            if msg.role not in ("user", "human"):
                continue
            raw_message = msg.raw.get("message", {})
            if not isinstance(raw_message, dict):
                continue
            raw_content = raw_message.get("content", [])
            if not isinstance(raw_content, list):
                continue
            tool_result_blocks = [
                block
                for block in raw_content
                if isinstance(block, dict) and block.get("type") == "tool_result"
            ]
            if not tool_result_blocks:
                continue
            # Latest user message with tool_results found — decide from ALL of
            # its blocks, then stop scanning older messages.
            return any(bool(block.get("is_error", False)) for block in tool_result_blocks)
        return False

    def get_last_bash_tool_use(self) -> ContentBlock | None:
        """Get the most recent Bash tool_use block across all assistant messages.

        Unlike get_last_tool_use_in_message() which only checks the last assistant
        message, this scans backwards across all messages to find the most recent
        Bash tool use regardless of subsequent assistant text messages.

        Returns:
            Most recent Bash tool_use ContentBlock, or None if not found
        """
        for msg in reversed(self._messages):
            if msg.role == "assistant":
                for block in reversed(msg.content_blocks):
                    if block.block_type == "tool_use" and block.tool_name == ToolName.BASH:
                        return block
        return None
