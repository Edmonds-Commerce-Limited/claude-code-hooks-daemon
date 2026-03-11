"""Tests for TranscriptReader - JSONL transcript parser.

TDD RED phase: These tests define the expected API for TranscriptReader.
"""

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import ToolName
from claude_code_hooks_daemon.core.transcript_reader import (
    ContentBlock,
    ToolUse,
    TranscriptMessage,
    TranscriptReader,
)


class TestTranscriptReaderInit:
    """Test TranscriptReader initialization."""

    def test_initial_state_not_loaded(self) -> None:
        """TranscriptReader should not be loaded initially."""
        reader = TranscriptReader()
        assert reader.is_loaded() is False

    def test_get_messages_empty_when_not_loaded(self) -> None:
        """get_messages() should return empty list when not loaded."""
        reader = TranscriptReader()
        assert reader.get_messages() == []


class TestTranscriptReaderLoad:
    """Test TranscriptReader.load()."""

    def test_load_marks_as_loaded(self, tmp_path: Path) -> None:
        """load() should mark reader as loaded."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")
        reader = TranscriptReader()
        reader.load(str(transcript))
        assert reader.is_loaded() is True

    def test_load_nonexistent_file_stays_unloaded(self) -> None:
        """load() with nonexistent file should stay unloaded."""
        reader = TranscriptReader()
        reader.load("/nonexistent/file.jsonl")
        assert reader.is_loaded() is False

    def test_load_new_path_resets_cache(self, tmp_path: Path) -> None:
        """load() with new path should reset cached data."""
        # Create first transcript with a message
        transcript1 = tmp_path / "t1.jsonl"
        transcript1.write_text(
            json.dumps({"type": "human", "message": {"content": "Hello"}}) + "\n"
        )
        # Create second transcript with different content
        transcript2 = tmp_path / "t2.jsonl"
        transcript2.write_text(
            json.dumps({"type": "human", "message": {"content": "World"}}) + "\n"
        )

        reader = TranscriptReader()
        reader.load(str(transcript1))
        msgs1 = reader.get_messages()

        reader.load(str(transcript2))
        msgs2 = reader.get_messages()

        # Messages should be different after loading new file
        assert len(msgs1) > 0
        assert len(msgs2) > 0
        assert msgs1[0].content != msgs2[0].content

    def test_load_same_path_uses_cache(self, tmp_path: Path) -> None:
        """load() with same path should not re-parse."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "human", "message": {"content": "Hello"}}) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs1 = reader.get_messages()

        # Load same path again
        reader.load(str(transcript))
        msgs2 = reader.get_messages()

        assert msgs1 == msgs2


class TestTranscriptReaderGetMessages:
    """Test TranscriptReader.get_messages()."""

    @pytest.fixture
    def reader_with_messages(self, tmp_path: Path) -> TranscriptReader:
        """Create reader loaded with sample messages."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "human", "message": {"content": "What is Python?"}}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": "Python is a programming language."},
                }
            ),
            json.dumps({"type": "human", "message": {"content": "Tell me more."}}),
        ]
        transcript.write_text("\n".join(lines) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        return reader

    def test_get_messages_returns_all(self, reader_with_messages: TranscriptReader) -> None:
        """get_messages() should return all parsed messages."""
        msgs = reader_with_messages.get_messages()
        assert len(msgs) == 3

    def test_get_messages_preserves_order(self, reader_with_messages: TranscriptReader) -> None:
        """get_messages() should preserve JSONL line order."""
        msgs = reader_with_messages.get_messages()
        assert msgs[0].role == "human"
        assert msgs[1].role == "assistant"
        assert msgs[2].role == "human"

    def test_get_messages_extracts_content(self, reader_with_messages: TranscriptReader) -> None:
        """get_messages() should extract message content."""
        msgs = reader_with_messages.get_messages()
        assert msgs[0].content == "What is Python?"
        assert msgs[1].content == "Python is a programming language."


class TestTranscriptReaderGetToolUses:
    """Test TranscriptReader.get_tool_uses()."""

    @pytest.fixture
    def reader_with_tools(self, tmp_path: Path) -> TranscriptReader:
        """Create reader loaded with tool use messages."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "human", "message": {"content": "Run ls"}}),
            json.dumps(
                {
                    "type": "tool_use",
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls -la"},
                }
            ),
            json.dumps(
                {
                    "type": "tool_result",
                    "tool_name": "Bash",
                    "output": "file1.txt\nfile2.txt",
                }
            ),
            json.dumps(
                {
                    "type": "tool_use",
                    "tool_name": "Read",
                    "tool_input": {"file_path": "/tmp/test.py"},
                }
            ),
        ]
        transcript.write_text("\n".join(lines) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        return reader

    def test_get_tool_uses_returns_tool_entries(self, reader_with_tools: TranscriptReader) -> None:
        """get_tool_uses() should return tool_use entries."""
        tools = reader_with_tools.get_tool_uses()
        assert len(tools) == 2

    def test_get_tool_uses_extracts_tool_name(self, reader_with_tools: TranscriptReader) -> None:
        """get_tool_uses() should extract tool names."""
        tools = reader_with_tools.get_tool_uses()
        assert tools[0].tool_name == ToolName.BASH
        assert tools[1].tool_name == ToolName.READ

    def test_get_tool_uses_extracts_tool_input(self, reader_with_tools: TranscriptReader) -> None:
        """get_tool_uses() should extract tool input."""
        tools = reader_with_tools.get_tool_uses()
        assert tools[0].tool_input == {"command": "ls -la"}


class TestTranscriptReaderGetLastNMessages:
    """Test TranscriptReader.get_last_n_messages()."""

    @pytest.fixture
    def reader_with_5_messages(self, tmp_path: Path) -> TranscriptReader:
        """Create reader with 5 messages."""
        transcript = tmp_path / "transcript.jsonl"
        lines = []
        for i in range(5):
            role = "human" if i % 2 == 0 else "assistant"
            lines.append(json.dumps({"type": role, "message": {"content": f"Message {i}"}}))
        transcript.write_text("\n".join(lines) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        return reader

    def test_get_last_n_returns_n_messages(self, reader_with_5_messages: TranscriptReader) -> None:
        """get_last_n_messages() should return last N messages."""
        msgs = reader_with_5_messages.get_last_n_messages(3)
        assert len(msgs) == 3

    def test_get_last_n_returns_latest(self, reader_with_5_messages: TranscriptReader) -> None:
        """get_last_n_messages() should return the most recent messages."""
        msgs = reader_with_5_messages.get_last_n_messages(2)
        assert msgs[0].content == "Message 3"
        assert msgs[1].content == "Message 4"

    def test_get_last_n_returns_all_if_n_exceeds(
        self, reader_with_5_messages: TranscriptReader
    ) -> None:
        """get_last_n_messages(100) should return all messages."""
        msgs = reader_with_5_messages.get_last_n_messages(100)
        assert len(msgs) == 5


class TestTranscriptReaderSearchMessages:
    """Test TranscriptReader.search_messages()."""

    @pytest.fixture
    def reader_with_searchable(self, tmp_path: Path) -> TranscriptReader:
        """Create reader with searchable messages."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "human", "message": {"content": "Fix the authentication bug"}}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": "I'll look at the auth module."},
                }
            ),
            json.dumps({"type": "human", "message": {"content": "Now add unit tests"}}),
        ]
        transcript.write_text("\n".join(lines) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        return reader

    def test_search_finds_matching_messages(self, reader_with_searchable: TranscriptReader) -> None:
        """search_messages() should find messages containing pattern."""
        results = reader_with_searchable.search_messages("auth")
        assert len(results) == 2  # "authentication" and "auth module"

    def test_search_case_insensitive(self, reader_with_searchable: TranscriptReader) -> None:
        """search_messages() should be case-insensitive."""
        results = reader_with_searchable.search_messages("FIX")
        assert len(results) == 1

    def test_search_no_results(self, reader_with_searchable: TranscriptReader) -> None:
        """search_messages() should return empty for no matches."""
        results = reader_with_searchable.search_messages("database")
        assert results == []


class TestTranscriptReaderEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_malformed_json_lines(self, tmp_path: Path) -> None:
        """Reader should skip malformed JSON lines."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps({"type": "human", "message": {"content": "Valid"}})
            + "\n"
            + "not valid json\n"
            + json.dumps({"type": "assistant", "message": {"content": "Also valid"}})
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 2

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        """Reader should handle empty transcript file."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")
        reader = TranscriptReader()
        reader.load(str(transcript))
        assert reader.get_messages() == []
        assert reader.is_loaded() is True

    def test_handles_lines_without_type(self, tmp_path: Path) -> None:
        """Reader should skip lines without 'type' field."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps({"data": "no type field"})
            + "\n"
            + json.dumps({"type": "human", "message": {"content": "Has type"}})
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1


class TestTranscriptReaderParsingEdgeCases:
    """Test edge cases in _parse method for missing coverage."""

    def test_handles_non_dict_json_lines(self, tmp_path: Path) -> None:
        """Reader should skip JSON lines that parse to non-dict (e.g., list, string)."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps([1, 2, 3])
            + "\n"
            + json.dumps("just a string")
            + "\n"
            + json.dumps({"type": "human", "message": {"content": "Valid"}})
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert msgs[0].content == "Valid"

    def test_get_last_n_messages_with_zero_returns_empty(self, tmp_path: Path) -> None:
        """get_last_n_messages(0) should return empty list."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "human", "message": {"content": "Hello"}}) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_last_n_messages(0)
        assert msgs == []

    def test_get_last_n_messages_with_negative_returns_empty(self, tmp_path: Path) -> None:
        """get_last_n_messages(-1) should return empty list."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "human", "message": {"content": "Hello"}}) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_last_n_messages(-1)
        assert msgs == []


class TestTranscriptMessage:
    """Test TranscriptMessage dataclass."""

    def test_message_fields(self) -> None:
        """TranscriptMessage should store role and content."""
        msg = TranscriptMessage(role="human", content="Hello", raw={})
        assert msg.role == "human"
        assert msg.content == "Hello"


class TestTranscriptMessageContentBlocks:
    """Test TranscriptMessage.content_blocks field."""

    def test_default_content_blocks_is_empty_tuple(self) -> None:
        """Default content_blocks should be empty tuple for backward compat."""
        msg = TranscriptMessage(role="human", content="Hello", raw={})
        assert msg.content_blocks == ()

    def test_content_blocks_preserved(self) -> None:
        """content_blocks should store provided blocks."""
        block = ContentBlock(block_type="text", text="Hello")
        msg = TranscriptMessage(
            role="assistant",
            content="Hello",
            raw={},
            content_blocks=(block,),
        )
        assert len(msg.content_blocks) == 1
        assert msg.content_blocks[0].text == "Hello"


class TestContentBlock:
    """Test ContentBlock dataclass."""

    def test_text_block(self) -> None:
        """ContentBlock should store text block fields."""
        block = ContentBlock(block_type="text", text="Hello world")
        assert block.block_type == "text"
        assert block.text == "Hello world"
        assert not block.tool_name
        assert block.tool_input == {}

    def test_tool_use_block(self) -> None:
        """ContentBlock should store tool_use block fields."""
        block = ContentBlock(
            block_type="tool_use",
            tool_name=ToolName.ASK_USER_QUESTION,
            tool_input={"question": "Which option?"},
        )
        assert block.block_type == "tool_use"
        assert block.tool_name == ToolName.ASK_USER_QUESTION
        assert block.tool_input == {"question": "Which option?"}
        assert block.text == ""

    def test_raw_field(self) -> None:
        """ContentBlock raw field stores original dict."""
        raw = {"type": "text", "text": "hi"}
        block = ContentBlock(block_type="text", text="hi", raw=raw)
        assert block.raw == raw

    def test_default_raw_is_empty_dict(self) -> None:
        """ContentBlock raw defaults to empty dict."""
        block = ContentBlock(block_type="text")
        assert block.raw == {}


class TestToolUse:
    """Test ToolUse dataclass."""

    def test_tool_use_fields(self) -> None:
        """ToolUse should store tool_name and tool_input."""
        tool = ToolUse(tool_name=ToolName.BASH, tool_input={"command": "ls"}, raw={})
        assert tool.tool_name == ToolName.BASH
        assert tool.tool_input == {"command": "ls"}


class TestTranscriptReaderRealJSONLFormat:
    """Test parsing real Claude Code JSONL format (type=message with nested role)."""

    def test_parses_real_assistant_message(self, tmp_path: Path) -> None:
        """Should parse real format: type=message, message.role=assistant."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "I'll help you."},
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "ls"},
                            },
                        ],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert msgs[0].role == "assistant"
        assert msgs[0].content == "I'll help you."

    def test_parses_content_blocks_from_real_format(self, tmp_path: Path) -> None:
        """Should parse content blocks from real JSONL format."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "Let me check."},
                            {
                                "type": "tool_use",
                                "name": "AskUserQuestion",
                                "input": {"question": "Which?"},
                            },
                        ],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs[0].content_blocks) == 2
        assert msgs[0].content_blocks[0].block_type == "text"
        assert msgs[0].content_blocks[0].text == "Let me check."
        assert msgs[0].content_blocks[1].block_type == "tool_use"
        assert msgs[0].content_blocks[1].tool_name == ToolName.ASK_USER_QUESTION
        assert msgs[0].content_blocks[1].tool_input == {"question": "Which?"}

    def test_parses_real_human_message(self, tmp_path: Path) -> None:
        """Should parse real format: type=message, message.role=human."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "human",
                        "content": [{"type": "text", "text": "Hello Claude"}],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert msgs[0].role == "human"
        assert msgs[0].content == "Hello Claude"

    def test_concatenates_multiple_text_blocks(self, tmp_path: Path) -> None:
        """Should concatenate multiple text blocks into content string."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "First part."},
                            {"type": "text", "text": "Second part."},
                        ],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert msgs[0].content == "First part. Second part."

    def test_legacy_format_still_works(self, tmp_path: Path) -> None:
        """Legacy format (type=human/assistant) should still be parsed."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "human", "message": {"content": "Hello"}}) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert msgs[0].role == "human"
        assert msgs[0].content == "Hello"

    def test_string_content_in_real_format(self, tmp_path: Path) -> None:
        """Should handle string content (not list) in real format."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": "Just a plain string",
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert msgs[0].content == "Just a plain string"


class TestTranscriptReaderQueryMethods:
    """Test new query methods on TranscriptReader."""

    @pytest.fixture
    def reader_with_conversation(self, tmp_path: Path) -> TranscriptReader:
        """Create reader with a realistic conversation including tool_use blocks."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "human",
                        "content": [{"type": "text", "text": "Fix the bug"}],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "I'll read the file."},
                            {
                                "type": "tool_use",
                                "name": "Read",
                                "input": {"file_path": "/tmp/test.py"},
                            },
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "Would you like me to proceed?"},
                            {
                                "type": "tool_use",
                                "name": "AskUserQuestion",
                                "input": {"question": "Which approach?"},
                            },
                        ],
                    },
                }
            ),
        ]
        transcript.write_text("\n".join(lines) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        return reader

    def test_get_last_assistant_message(self, reader_with_conversation: TranscriptReader) -> None:
        """get_last_assistant_message() returns last assistant TranscriptMessage."""
        msg = reader_with_conversation.get_last_assistant_message()
        assert msg is not None
        assert msg.role == "assistant"
        assert "Would you like" in msg.content

    def test_get_last_assistant_message_none_when_empty(self, tmp_path: Path) -> None:
        """get_last_assistant_message() returns None when no assistant messages."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "human",
                        "content": [{"type": "text", "text": "Hello"}],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        assert reader.get_last_assistant_message() is None

    def test_get_last_assistant_text(self, reader_with_conversation: TranscriptReader) -> None:
        """get_last_assistant_text() returns text content of last assistant message."""
        text = reader_with_conversation.get_last_assistant_text()
        assert "Would you like" in text

    def test_get_last_assistant_text_empty_when_no_messages(self, tmp_path: Path) -> None:
        """get_last_assistant_text() returns empty string when no assistant messages."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")
        reader = TranscriptReader()
        reader.load(str(transcript))
        assert reader.get_last_assistant_text() == ""

    def test_last_assistant_used_tool_true(
        self, reader_with_conversation: TranscriptReader
    ) -> None:
        """last_assistant_used_tool() returns True when tool was used."""
        assert reader_with_conversation.last_assistant_used_tool(ToolName.ASK_USER_QUESTION) is True

    def test_last_assistant_used_tool_false(
        self, reader_with_conversation: TranscriptReader
    ) -> None:
        """last_assistant_used_tool() returns False when tool was NOT used."""
        assert reader_with_conversation.last_assistant_used_tool(ToolName.BASH) is False

    def test_last_assistant_used_tool_false_when_no_messages(self, tmp_path: Path) -> None:
        """last_assistant_used_tool() returns False when no messages."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")
        reader = TranscriptReader()
        reader.load(str(transcript))
        assert reader.last_assistant_used_tool(ToolName.ASK_USER_QUESTION) is False

    def test_get_last_tool_use_in_message(self, reader_with_conversation: TranscriptReader) -> None:
        """get_last_tool_use_in_message() returns last tool_use ContentBlock."""
        block = reader_with_conversation.get_last_tool_use_in_message()
        assert block is not None
        assert block.block_type == "tool_use"
        assert block.tool_name == ToolName.ASK_USER_QUESTION

    def test_get_last_tool_use_in_message_none_when_no_tools(self, tmp_path: Path) -> None:
        """get_last_tool_use_in_message() returns None when no tool_use blocks."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Just text."}],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        assert reader.get_last_tool_use_in_message() is None


class TestLegacyFormatWithContentBlocks:
    """Test type=assistant/human entries with content as list of blocks.

    Regression tests for bug: Real Claude Code transcripts use type=assistant
    (not type=message) with content as a list of content blocks. The legacy
    format path stored the list directly instead of parsing blocks, causing
    TypeError in handlers that call get_last_assistant_text().
    """

    def test_legacy_assistant_with_content_blocks_returns_string(self, tmp_path: Path) -> None:
        """type=assistant with content blocks should join text into string."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "I'll help you with that."},
                        ],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        text = reader.get_last_assistant_text()
        assert isinstance(text, str)
        assert text == "I'll help you with that."

    def test_legacy_assistant_with_multiple_text_blocks(self, tmp_path: Path) -> None:
        """type=assistant with multiple text blocks should concatenate them."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "First part."},
                            {"type": "text", "text": "Second part."},
                        ],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        text = reader.get_last_assistant_text()
        assert text == "First part. Second part."

    def test_legacy_assistant_with_tool_use_blocks(self, tmp_path: Path) -> None:
        """type=assistant with tool_use blocks should parse content blocks."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Let me check."},
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "ls"},
                            },
                        ],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msg = reader.get_last_assistant_message()
        assert msg is not None
        assert msg.content == "Let me check."
        assert len(msg.content_blocks) == 2
        assert msg.content_blocks[0].block_type == "text"
        assert msg.content_blocks[1].block_type == "tool_use"
        assert msg.content_blocks[1].tool_name == ToolName.BASH

    def test_legacy_human_with_content_blocks(self, tmp_path: Path) -> None:
        """type=human with content blocks should also parse correctly."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "human",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Fix the bug please"},
                        ],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert isinstance(msgs[0].content, str)
        assert msgs[0].content == "Fix the bug please"

    def test_legacy_assistant_string_content_still_works(self, tmp_path: Path) -> None:
        """type=assistant with plain string content should still work."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": "Plain string response"},
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        text = reader.get_last_assistant_text()
        assert text == "Plain string response"


class TestTranscriptMessageUuid:
    """Tests for UUID field on TranscriptMessage (Plan 00081 Task 2.1)."""

    def test_uuid_parsed_from_entry_level_field(self, tmp_path: Path) -> None:
        """UUID should be parsed from the entry-level uuid field."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "uuid": "abc-123-def",
                    "message": {"role": "assistant", "content": "Hello"},
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msg = reader.get_last_assistant_message()
        assert msg is not None
        assert msg.uuid == "abc-123-def"

    def test_uuid_none_when_missing(self, tmp_path: Path) -> None:
        """UUID should be None when entry has no uuid field."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"role": "assistant", "content": "No UUID"},
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msg = reader.get_last_assistant_message()
        assert msg is not None
        assert msg.uuid is None

    def test_uuid_on_real_format_message(self, tmp_path: Path) -> None:
        """UUID should be parsed from type=message entries too."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "uuid": "real-uuid-456",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Response"}],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msg = reader.get_last_assistant_message()
        assert msg is not None
        assert msg.uuid == "real-uuid-456"

    def test_uuid_preserved_across_multiple_messages(self, tmp_path: Path) -> None:
        """Each message should have its own UUID."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "uuid": "uuid-1",
                    "message": {"role": "assistant", "content": "First"},
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "uuid": "uuid-2",
                    "message": {"role": "assistant", "content": "Second"},
                }
            ),
        ]
        transcript.write_text("\n".join(lines) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 2
        assert msgs[0].uuid == "uuid-1"
        assert msgs[1].uuid == "uuid-2"


class TestIncrementalRead:
    """Tests for incremental transcript reading (Plan 00081 Task 2.2)."""

    def test_read_incremental_returns_new_messages(self, tmp_path: Path) -> None:
        """read_incremental should return only messages after byte offset."""
        transcript = tmp_path / "transcript.jsonl"
        line1 = json.dumps(
            {
                "type": "assistant",
                "uuid": "uuid-1",
                "message": {"role": "assistant", "content": "First"},
            }
        )
        transcript.write_text(line1 + "\n")

        reader = TranscriptReader()
        # First read — get all
        messages, offset = reader.read_incremental(str(transcript), 0)
        assert len(messages) == 1
        assert messages[0].content == "First"
        assert offset > 0

        # Append more content
        with transcript.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "uuid-2",
                        "message": {"role": "assistant", "content": "Second"},
                    }
                )
                + "\n"
            )

        # Incremental read — only new messages
        new_messages, new_offset = reader.read_incremental(str(transcript), offset)
        assert len(new_messages) == 1
        assert new_messages[0].content == "Second"
        assert new_offset > offset

    def test_read_incremental_returns_empty_when_no_new(self, tmp_path: Path) -> None:
        """read_incremental should return empty list when no new content."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "uuid": "uuid-1",
                    "message": {"role": "assistant", "content": "Only one"},
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        _, offset = reader.read_incremental(str(transcript), 0)

        # Read again from same offset — nothing new
        messages, same_offset = reader.read_incremental(str(transcript), offset)
        assert len(messages) == 0
        assert same_offset == offset

    def test_read_incremental_fallback_on_invalid_offset(self, tmp_path: Path) -> None:
        """read_incremental should fall back to full read if offset is beyond file size."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "uuid": "uuid-1",
                    "message": {"role": "assistant", "content": "Data"},
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        # Use offset way beyond file size
        messages, offset = reader.read_incremental(str(transcript), 999999)
        assert len(messages) == 1
        assert messages[0].content == "Data"
        assert offset > 0

    def test_read_incremental_skips_non_message_types(self, tmp_path: Path) -> None:
        """read_incremental should skip progress/system entries, only return messages."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "progress", "uuid": "p1", "data": "compiling"}),
            json.dumps(
                {
                    "type": "assistant",
                    "uuid": "uuid-1",
                    "message": {"role": "assistant", "content": "Done"},
                }
            ),
            json.dumps({"type": "system", "uuid": "s1", "data": "info"}),
        ]
        transcript.write_text("\n".join(lines) + "\n")
        reader = TranscriptReader()
        messages, _ = reader.read_incremental(str(transcript), 0)
        assert len(messages) == 1
        assert messages[0].content == "Done"


class TestFilterAssistantMessages:
    """Tests for assistant message filtering (Plan 00081 Task 2.3)."""

    def test_filter_assistant_messages_only(self) -> None:
        """filter_assistant_messages should return only assistant role messages."""
        messages = [
            TranscriptMessage(role="user", content="Question", raw={}, uuid=None),
            TranscriptMessage(role="assistant", content="Answer", raw={}, uuid="a1"),
            TranscriptMessage(role="user", content="Follow up", raw={}, uuid=None),
            TranscriptMessage(role="assistant", content="More info", raw={}, uuid="a2"),
        ]
        result = TranscriptReader.filter_assistant_messages(messages)
        assert len(result) == 2
        assert result[0].content == "Answer"
        assert result[1].content == "More info"

    def test_filter_assistant_messages_empty_list(self) -> None:
        """filter_assistant_messages should return empty list for empty input."""
        assert TranscriptReader.filter_assistant_messages([]) == []

    def test_filter_assistant_messages_no_assistant(self) -> None:
        """filter_assistant_messages should return empty when no assistant messages."""
        messages = [
            TranscriptMessage(role="user", content="Hello", raw={}, uuid=None),
        ]
        result = TranscriptReader.filter_assistant_messages(messages)
        assert len(result) == 0


class TestLoadPathCheckExceptions:
    """Cover exception branches in load() path validation (lines 122-124)."""

    def test_load_with_invalid_path_characters_stays_unloaded(self) -> None:
        """load() should handle path.exists() raising an exception gracefully."""
        # A null byte in the path triggers an OSError in Path.exists() on Linux,
        # exercising the except-Exception branch (lines 122-124).
        reader = TranscriptReader()
        reader.load("/some/path\x00with_null")
        assert reader.is_loaded() is False


class TestParseExceptionBranches:
    """Cover exception handling branches inside _parse() (lines 153, 195-198)."""

    def test_skips_malformed_json_inside_parse(self, tmp_path: Path) -> None:
        """_parse() should skip lines with malformed JSON (line 153)."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            "this is {not valid json\n"
            + json.dumps({"type": "human", "message": {"content": "Good"}})
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert msgs[0].content == "Good"

    def test_handles_oserror_during_parse(self, tmp_path: Path) -> None:
        """_parse() should handle OSError when reading (line 148 try/except).

        We create a directory where a file is expected so that open() raises
        IsADirectoryError (subclass of OSError). _parse() catches this
        internally and returns empty, but load() still marks _loaded = True
        since _parse() didn't propagate the exception.
        """
        # Create a directory with the same name as the transcript so open() raises
        transcript_dir = tmp_path / "transcript.jsonl"
        transcript_dir.mkdir()
        reader = TranscriptReader()
        # load() will see path.exists() == True then _parse() catches OSError
        reader.load(str(transcript_dir))
        # _parse() caught the error and returned normally, so _loaded is True
        # but no messages were parsed
        assert reader.is_loaded() is True
        assert reader.get_messages() == []


class TestParseMessageEntryEdgeCases:
    """Cover _parse_message_entry branches not exercised by existing tests."""

    def test_message_field_not_dict_is_skipped(self, tmp_path: Path) -> None:
        """_parse_message_entry returns early when message value is not a dict (line 211)."""
        transcript = tmp_path / "transcript.jsonl"
        # type=message but message field is a string, not a dict
        transcript.write_text(json.dumps({"type": "message", "message": "not a dict"}) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        assert reader.get_messages() == []

    def test_message_entry_with_empty_role_is_skipped(self, tmp_path: Path) -> None:
        """_parse_message_entry returns early when role is absent/empty (line 215)."""
        transcript = tmp_path / "transcript.jsonl"
        # message dict present but no role key
        transcript.write_text(
            json.dumps({"type": "message", "message": {"content": "no role"}}) + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        assert reader.get_messages() == []

    def test_non_list_non_string_content_produces_empty_message(self, tmp_path: Path) -> None:
        """_parse_message_entry handles content that is neither str nor list (lines 229-232)."""
        transcript = tmp_path / "transcript.jsonl"
        # content is a dict — neither str nor list
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {"role": "assistant", "content": {"key": "value"}},
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert msgs[0].role == "assistant"
        assert msgs[0].content == ""

    def test_string_items_in_content_list_become_text_blocks(self, tmp_path: Path) -> None:
        """_parse_message_entry handles bare string items in content list (lines 239-240)."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": ["plain string item"],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert msgs[0].content == "plain string item"
        assert len(msgs[0].content_blocks) == 1
        assert msgs[0].content_blocks[0].block_type == "text"
        assert msgs[0].content_blocks[0].text == "plain string item"

    def test_unknown_block_type_stored_as_generic_content_block(self, tmp_path: Path) -> None:
        """_parse_message_entry stores unknown block types with their type name (line 259)."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "Let me reason..."},
                        ],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert len(msgs[0].content_blocks) == 1
        assert msgs[0].content_blocks[0].block_type == "thinking"
        assert msgs[0].content_blocks[0].text == ""

    def test_uuid_on_legacy_format_with_non_dict_message(self, tmp_path: Path) -> None:
        """Legacy path appends message with empty content when message is not a dict (line 179)."""
        transcript = tmp_path / "transcript.jsonl"
        # type=human but message value is not a dict — triggers line 179 branch
        transcript.write_text(
            json.dumps({"type": "human", "uuid": "x-uuid", "message": ["not", "a", "dict"]}) + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert msgs[0].role == "human"
        assert msgs[0].content == ""
        assert msgs[0].uuid == "x-uuid"


class TestIncrementalReadEdgeCases:
    """Cover branches in read_incremental() not hit by existing tests."""

    def test_read_incremental_returns_empty_and_zero_for_empty_file(self, tmp_path: Path) -> None:
        """read_incremental on a zero-byte file returns ([], 0) (lines 289, 293)."""
        transcript = tmp_path / "empty.jsonl"
        transcript.write_text("")
        reader = TranscriptReader()
        messages, offset = reader.read_incremental(str(transcript), 0)
        assert messages == []
        assert offset == 0

    def test_read_incremental_skips_empty_lines(self, tmp_path: Path) -> None:
        """read_incremental skips blank lines within the file (line 309)."""
        transcript = tmp_path / "transcript.jsonl"
        line = json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "Hi"}})
        # Surround a real line with blank lines
        transcript.write_bytes(("\n" + line + "\n\n").encode("utf-8"))
        reader = TranscriptReader()
        messages, offset = reader.read_incremental(str(transcript), 0)
        assert len(messages) == 1
        assert messages[0].content == "Hi"

    def test_read_incremental_skips_malformed_json_lines(self, tmp_path: Path) -> None:
        """read_incremental silently skips lines with invalid JSON (lines 313-314)."""
        transcript = tmp_path / "transcript.jsonl"
        good_line = json.dumps(
            {"type": "assistant", "message": {"role": "assistant", "content": "Good"}}
        )
        transcript.write_bytes(("bad json here\n" + good_line + "\n").encode("utf-8"))
        reader = TranscriptReader()
        messages, _ = reader.read_incremental(str(transcript), 0)
        assert len(messages) == 1
        assert messages[0].content == "Good"

    def test_read_incremental_skips_non_dict_json_lines(self, tmp_path: Path) -> None:
        """read_incremental skips JSON lines that are not dicts (line 317)."""
        transcript = tmp_path / "transcript.jsonl"
        good_line = json.dumps(
            {"type": "assistant", "message": {"role": "assistant", "content": "Good"}}
        )
        transcript.write_bytes((json.dumps([1, 2, 3]) + "\n" + good_line + "\n").encode("utf-8"))
        reader = TranscriptReader()
        messages, _ = reader.read_incremental(str(transcript), 0)
        assert len(messages) == 1
        assert messages[0].content == "Good"

    def test_read_incremental_parses_type_message_entries(self, tmp_path: Path) -> None:
        """read_incremental handles type=message entries (lines 323-325)."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_bytes(
            (
                json.dumps(
                    {
                        "type": "message",
                        "uuid": "m-uuid",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Via message type"}],
                        },
                    }
                )
                + "\n"
            ).encode("utf-8")
        )
        reader = TranscriptReader()
        messages, _ = reader.read_incremental(str(transcript), 0)
        assert len(messages) == 1
        assert messages[0].content == "Via message type"
        assert messages[0].uuid == "m-uuid"

    def test_read_incremental_injects_role_for_legacy_entries_without_role(
        self, tmp_path: Path
    ) -> None:
        """read_incremental injects role into legacy entries that omit it (line 330)."""
        transcript = tmp_path / "transcript.jsonl"
        # type=assistant but message dict has no 'role' key
        transcript.write_bytes(
            (
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": "Injected role"},
                    }
                )
                + "\n"
            ).encode("utf-8")
        )
        reader = TranscriptReader()
        messages, _ = reader.read_incremental(str(transcript), 0)
        assert len(messages) == 1
        assert messages[0].role == "assistant"
        assert messages[0].content == "Injected role"

    def test_read_incremental_handles_oserror(self, tmp_path: Path) -> None:
        """read_incremental returns ([], offset) when an OSError occurs (lines 338-339)."""
        import os

        # Create a directory at the path so open() raises IsADirectoryError
        transcript_dir = tmp_path / "transcript.jsonl"
        transcript_dir.mkdir()

        reader = TranscriptReader()
        # path.exists() is True (dir exists) and stat().st_size would fail or
        # open() would raise IsADirectoryError.  Either way the OSError branch fires.
        messages, offset = reader.read_incremental(str(transcript_dir), 0)
        assert messages == []
        os.rmdir(str(transcript_dir))

    def test_read_incremental_user_type_entry_is_parsed(self, tmp_path: Path) -> None:
        """read_incremental handles type=user entries (branch alongside human/assistant)."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_bytes(
            (
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": "User message"},
                    }
                )
                + "\n"
            ).encode("utf-8")
        )
        reader = TranscriptReader()
        messages, _ = reader.read_incremental(str(transcript), 0)
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "User message"


class TestParseEntryToMessage:
    """Cover _parse_entry_to_message() branches (lines 357-399)."""

    def test_returns_none_when_message_not_dict(self) -> None:
        """_parse_entry_to_message returns None when message field is not a dict (line 357)."""
        reader = TranscriptReader()
        result = reader._parse_entry_to_message({"message": "not a dict"}, entry_uuid=None)
        assert result is None

    def test_returns_none_when_role_missing(self) -> None:
        """_parse_entry_to_message returns None when role is absent (line 361)."""
        reader = TranscriptReader()
        result = reader._parse_entry_to_message(
            {"message": {"content": "no role"}}, entry_uuid=None
        )
        assert result is None

    def test_returns_message_with_string_content(self) -> None:
        """_parse_entry_to_message handles string content (line 366)."""
        reader = TranscriptReader()
        result = reader._parse_entry_to_message(
            {"message": {"role": "assistant", "content": "plain string"}},
            entry_uuid="u1",
        )
        assert result is not None
        assert result.role == "assistant"
        assert result.content == "plain string"
        assert result.uuid == "u1"

    def test_returns_message_with_non_list_non_string_content(self) -> None:
        """_parse_entry_to_message handles content that is neither str nor list (line 369)."""
        reader = TranscriptReader()
        result = reader._parse_entry_to_message(
            {"message": {"role": "human", "content": {"nested": "dict"}}},
            entry_uuid=None,
        )
        assert result is not None
        assert result.role == "human"
        assert result.content == ""

    def test_returns_message_with_string_items_in_content_list(self) -> None:
        """_parse_entry_to_message handles bare string items in content list (lines 376-377)."""
        reader = TranscriptReader()
        result = reader._parse_entry_to_message(
            {"message": {"role": "human", "content": ["bare string"]}},
            entry_uuid=None,
        )
        assert result is not None
        assert result.content == "bare string"
        assert len(result.content_blocks) == 1
        assert result.content_blocks[0].block_type == "text"
        assert result.content_blocks[0].text == "bare string"

    def test_returns_message_with_tool_use_block(self) -> None:
        """_parse_entry_to_message parses tool_use content blocks (lines 384-394)."""
        reader = TranscriptReader()
        result = reader._parse_entry_to_message(
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Running it."},
                        {
                            "type": "tool_use",
                            "name": ToolName.BASH,
                            "input": {"command": "ls"},
                        },
                    ],
                }
            },
            entry_uuid="u2",
        )
        assert result is not None
        assert result.content == "Running it."
        assert len(result.content_blocks) == 2
        assert result.content_blocks[1].block_type == "tool_use"
        assert result.content_blocks[1].tool_name == ToolName.BASH
        assert result.content_blocks[1].tool_input == {"command": "ls"}

    def test_returns_message_with_unknown_block_type(self) -> None:
        """_parse_entry_to_message stores unknown block types generically (line 396)."""
        reader = TranscriptReader()
        result = reader._parse_entry_to_message(
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "data": "..."}},
                    ],
                }
            },
            entry_uuid=None,
        )
        assert result is not None
        assert len(result.content_blocks) == 1
        assert result.content_blocks[0].block_type == "image"
        assert result.content_blocks[0].text == ""

    def test_returns_message_with_uuid(self) -> None:
        """_parse_entry_to_message stores the uuid on the returned message."""
        reader = TranscriptReader()
        result = reader._parse_entry_to_message(
            {
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello"}],
                }
            },
            entry_uuid="entry-uuid-99",
        )
        assert result is not None
        assert result.uuid == "entry-uuid-99"


class TestGetLastToolUseInMessageEdgeCases:
    """Cover get_last_tool_use_in_message() when there is no assistant message (line 521)."""

    def test_get_last_tool_use_returns_none_when_no_messages_loaded(self) -> None:
        """get_last_tool_use_in_message() returns None when reader has no messages (line 521)."""
        reader = TranscriptReader()
        # Never loaded — no messages at all
        result = reader.get_last_tool_use_in_message()
        assert result is None

    def test_get_last_tool_use_returns_none_when_only_human_messages(self, tmp_path: Path) -> None:
        """get_last_tool_use_in_message() returns None when no assistant messages exist."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "human",
                        "content": [{"type": "text", "text": "Hello"}],
                    },
                }
            )
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        result = reader.get_last_tool_use_in_message()
        assert result is None
