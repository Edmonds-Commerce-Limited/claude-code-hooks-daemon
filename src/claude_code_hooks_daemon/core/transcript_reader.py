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

logger = logging.getLogger(__name__)


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

    def _parse(self, path: Path) -> None:
        """Parse JSONL file line by line.

        Supports two formats:
        - Real Claude Code format: {"type": "message", "message": {"role": ..., "content": [...]}}
        - Legacy/test format: {"type": "human"/"assistant", "message": {"content": ...}}

        Skips malformed lines and lines without a 'type' field.

        Args:
            path: Path to JSONL file
        """
        try:
            with path.open("r") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug(
                            "TranscriptReader: Skipping malformed JSON at line %d", line_num
                        )
                        continue

                    if not isinstance(data, dict):
                        continue

                    entry_type = data.get("type")
                    if entry_type is None:
                        continue

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
                                TranscriptMessage(
                                    role=entry_type, content="", raw=data, uuid=data.get("uuid")
                                )
                            )
                        else:
                            # Inject role into message dict for _parse_message_entry
                            if "role" not in message_data:
                                message_data = {**message_data, "role": entry_type}
                            self._parse_message_entry({**data, "message": message_data})
                    elif entry_type == "tool_use":
                        tool_name = data.get("tool_name", "")
                        tool_input = data.get("tool_input", {})
                        self._tool_uses.append(
                            ToolUse(tool_name=tool_name, tool_input=tool_input, raw=data)
                        )
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("TranscriptReader: Failed to read %s: %s", path, e)
        except Exception as e:
            logger.error("TranscriptReader: Unexpected error reading %s: %s", path, e)

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
                    if block.block_type == "tool_use" and block.tool_name == "Bash":
                        return block
        return None
