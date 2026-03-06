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
    """

    role: str
    content: str
    raw: dict[str, Any] = field(repr=False)
    content_blocks: tuple[ContentBlock, ...] = ()


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

        path = Path(transcript_path)
        if not path.exists():
            logger.warning("Transcript file not found: %s", transcript_path)
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
        with path.open("r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("TranscriptReader: Skipping malformed JSON at line %d", line_num)
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
                    # Legacy/test format
                    message_data = data.get("message", {})
                    content = (
                        message_data.get("content", "") if isinstance(message_data, dict) else ""
                    )
                    self._messages.append(
                        TranscriptMessage(role=entry_type, content=content, raw=data)
                    )
                elif entry_type == "tool_use":
                    tool_name = data.get("tool_name", "")
                    tool_input = data.get("tool_input", {})
                    self._tool_uses.append(
                        ToolUse(tool_name=tool_name, tool_input=tool_input, raw=data)
                    )

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

        raw_content = message.get("content", [])

        # Handle string content (not a list of blocks)
        if isinstance(raw_content, str):
            self._messages.append(
                TranscriptMessage(role=role, content=raw_content, raw=data)
            )
            return

        # Parse content block list
        if not isinstance(raw_content, list):
            self._messages.append(
                TranscriptMessage(role=role, content="", raw=data)
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
            )
        )

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
