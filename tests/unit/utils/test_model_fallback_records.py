"""Tests for the shared automatic-model-downgrade record parser.

Claude Code writes the safety classifier's model substitution into the session
transcript in TWO shapes (both observed in the Plan 00328 field scan of 25 real
records): a ``fallback`` content block inside the assistant message, and a
standalone ``model_refusal_fallback`` record a few seconds later. This module
is the single place that recognises either.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.model_fallback_records import (
    UNKNOWN_MODEL,
    FallbackFacts,
    parse_fallback_line,
    scan_transcript_tail,
)


def _subtype_line(
    *,
    original: str = "claude-fable-5",
    fallback: str = "claude-opus-4-8",
    category: str = "cyber",
    scope: str = "session",
    timestamp: str = "2026-08-27T09:34:10.341Z",
) -> str:
    return json.dumps(
        {
            "subtype": "model_refusal_fallback",
            "originalModel": original,
            "fallbackModel": fallback,
            "apiRefusalCategory": category,
            "scope": scope,
            "timestamp": timestamp,
        }
    )


def _block_line(
    *,
    original: str = "claude-fable-5",
    fallback: str = "claude-opus-4-8",
    timestamp: str = "2026-08-27T09:33:41.549Z",
) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": timestamp,
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "hello"},
                    {
                        "type": "fallback",
                        "from": {"model": original},
                        "to": {"model": fallback},
                    },
                ],
            },
        }
    )


class TestParseFallbackLine:
    """Both real record shapes parse; nothing else does."""

    def test_standalone_subtype_record_carries_every_field(self) -> None:
        facts = parse_fallback_line(_subtype_line())

        assert facts == FallbackFacts(
            original_model="claude-fable-5",
            fallback_model="claude-opus-4-8",
            category="cyber",
            scope="session",
            timestamp="2026-08-27T09:34:10.341Z",
        )

    def test_assistant_message_fallback_block_carries_the_models(self) -> None:
        facts = parse_fallback_line(_block_line())

        assert facts is not None
        assert facts.original_model == "claude-fable-5"
        assert facts.fallback_model == "claude-opus-4-8"
        assert facts.timestamp == "2026-08-27T09:33:41.549Z"

    def test_the_block_shape_reports_unknown_for_fields_it_does_not_carry(self) -> None:
        """The block names no refusal category or scope; it must not invent them."""
        facts = parse_fallback_line(_block_line())

        assert facts is not None
        assert facts.category == UNKNOWN_MODEL
        assert facts.scope == UNKNOWN_MODEL

    @pytest.mark.parametrize(
        "line",
        [
            "",
            "   ",
            "not json at all",
            "[1, 2, 3]",
            json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}),
            json.dumps({"subtype": "something_else", "originalModel": "claude-fable-5"}),
        ],
        ids=["empty", "blank", "garbage", "json-array", "ordinary-message", "other-subtype"],
    )
    def test_a_line_that_is_not_a_fallback_record_yields_none(self, line: str) -> None:
        assert parse_fallback_line(line) is None

    def test_an_assistant_message_with_no_fallback_block_yields_none(self) -> None:
        line = json.dumps(
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
            }
        )

        assert parse_fallback_line(line) is None

    def test_a_missing_model_degrades_to_unknown_rather_than_crashing(self) -> None:
        line = json.dumps({"subtype": "model_refusal_fallback", "scope": "session"})

        facts = parse_fallback_line(line)

        assert facts is not None
        assert facts.original_model == UNKNOWN_MODEL
        assert facts.fallback_model == UNKNOWN_MODEL


class TestAMalformedMessageIsNotARecord:
    """A transcript is written live, so half-shaped payloads reach the parser."""

    @pytest.mark.parametrize(
        "payload",
        [
            {"message": "prose"},
            {"message": {"content": "text"}},
            {"message": {"content": [{"type": "text", "text": "hi"}]}},
            {"message": {"content": ["not-a-dict"]}},
            {"message": None},
        ],
        ids=["message-is-prose", "content-is-text", "no-block", "block-not-dict", "message-none"],
    )
    def test_a_shape_that_is_not_a_fallback_block_yields_none(self, payload: dict) -> None:
        assert parse_fallback_line(json.dumps(payload)) is None

    def test_a_block_whose_endpoints_are_not_objects_reports_unknown(self) -> None:
        """`from`/`to` are objects in every real record; a string is not fatal."""
        line = json.dumps(
            {
                "message": {
                    "content": [{"type": "fallback", "from": "fable", "to": "opus"}],
                }
            }
        )

        facts = parse_fallback_line(line)

        assert facts is not None
        assert facts.original_model == UNKNOWN_MODEL
        assert facts.fallback_model == UNKNOWN_MODEL


class TestScanTranscriptTail:
    """The scan is bounded, returns the LATEST record, and never raises."""

    def test_returns_the_only_record_in_a_small_transcript(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(f"{_block_line()}\n{_subtype_line()}\n", encoding="utf-8")

        facts = scan_transcript_tail(transcript)

        assert facts is not None
        assert facts.category == "cyber"

    def test_the_latest_record_wins_when_several_are_present(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(
            "\n".join(
                [
                    _subtype_line(timestamp="2026-08-27T09:00:00.000Z"),
                    _subtype_line(timestamp="2026-08-27T10:00:00.000Z"),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        facts = scan_transcript_tail(transcript)

        assert facts is not None
        assert facts.timestamp == "2026-08-27T10:00:00.000Z"

    def test_a_transcript_with_no_fallback_record_yields_none(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n",
            encoding="utf-8",
        )

        assert scan_transcript_tail(transcript) is None

    def test_a_record_outside_the_tail_window_is_not_read(self, tmp_path: Path) -> None:
        """The bound is the point: a 100 MB transcript is never parsed whole."""
        transcript = tmp_path / "session.jsonl"
        filler = json.dumps({"type": "user", "message": {"role": "user", "content": "x" * 200}})
        transcript.write_text(
            f"{_subtype_line()}\n" + "\n".join([filler] * 50) + "\n",
            encoding="utf-8",
        )

        assert scan_transcript_tail(transcript, max_bytes=500) is None

    def test_a_record_inside_the_tail_window_is_read(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.jsonl"
        filler = json.dumps({"type": "user", "message": {"role": "user", "content": "x" * 200}})
        transcript.write_text(
            "\n".join([filler] * 50) + f"\n{_subtype_line()}\n",
            encoding="utf-8",
        )

        facts = scan_transcript_tail(transcript, max_bytes=2000)

        assert facts is not None
        assert facts.original_model == "claude-fable-5"

    def test_a_partial_first_line_from_a_mid_line_seek_is_discarded(self, tmp_path: Path) -> None:
        """Seeking into the middle of a line must not yield a half-record.

        The truncated head is dropped, so the intact record after it is what
        comes back rather than a JSON parse error.
        """
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(
            f"{_subtype_line(timestamp='2026-01-01T00:00:00.000Z')}\n{_subtype_line()}\n",
            encoding="utf-8",
        )
        size = transcript.stat().st_size

        facts = scan_transcript_tail(transcript, max_bytes=size - 20)

        assert facts is not None
        assert facts.timestamp == "2026-08-27T09:34:10.341Z"

    def test_a_missing_transcript_yields_none_rather_than_raising(self, tmp_path: Path) -> None:
        assert scan_transcript_tail(tmp_path / "nope.jsonl") is None

    def test_an_empty_transcript_yields_none(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.jsonl"
        transcript.write_text("", encoding="utf-8")

        assert scan_transcript_tail(transcript) is None

    def test_a_directory_where_a_transcript_should_be_yields_none(self, tmp_path: Path) -> None:
        """An OSError on open degrades to "no record", never an exception."""
        directory = tmp_path / "session.jsonl"
        directory.mkdir()

        assert scan_transcript_tail(directory) is None
