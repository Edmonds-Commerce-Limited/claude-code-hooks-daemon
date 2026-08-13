"""Tests for shared stop hook helper utilities.

TDD RED phase: These tests define the expected API for stop_hook_helpers.
"""

import json
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.utils.stop_hook_helpers import (
    get_transcript_reader,
    has_recent_stop_hook_block,
    is_stop_hook_active,
)


class TestIsStopHookActive:
    """Test is_stop_hook_active() shared utility."""

    def test_false_when_not_set(self) -> None:
        """Returns False when neither field is present."""
        assert is_stop_hook_active({}) is False

    def test_true_with_snake_case(self) -> None:
        """Returns True when stop_hook_active is True."""
        assert is_stop_hook_active({"stop_hook_active": True}) is True

    def test_true_with_camel_case(self) -> None:
        """Returns True when stopHookActive is True."""
        assert is_stop_hook_active({"stopHookActive": True}) is True

    def test_false_with_snake_case_false(self) -> None:
        """Returns False when stop_hook_active is explicitly False."""
        assert is_stop_hook_active({"stop_hook_active": False}) is False

    def test_false_with_camel_case_false(self) -> None:
        """Returns False when stopHookActive is explicitly False."""
        assert is_stop_hook_active({"stopHookActive": False}) is False

    def test_true_when_either_is_true(self) -> None:
        """Returns True if either variant is True."""
        assert is_stop_hook_active({"stop_hook_active": False, "stopHookActive": True}) is True


class TestGetTranscriptReader:
    """Test get_transcript_reader() shared utility."""

    def test_returns_reader_for_valid_transcript(self, tmp_path: Path) -> None:
        """Returns a loaded TranscriptReader for valid transcript path."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Hello"}],
                    },
                }
            )
            + "\n"
        )
        hook_input: dict[str, Any] = {"transcript_path": str(transcript)}
        reader = get_transcript_reader(hook_input)
        assert reader is not None
        assert reader.is_loaded() is True

    def test_returns_none_when_no_transcript_path(self) -> None:
        """Returns None when transcript_path is missing from hook_input."""
        assert get_transcript_reader({}) is None

    def test_returns_none_when_transcript_path_empty(self) -> None:
        """Returns None when transcript_path is empty string."""
        assert get_transcript_reader({"transcript_path": ""}) is None

    def test_returns_none_when_file_not_found(self) -> None:
        """Returns None when transcript file does not exist."""
        assert get_transcript_reader({"transcript_path": "/nonexistent/file.jsonl"}) is None

    def test_reader_has_messages(self, tmp_path: Path) -> None:
        """Returned reader should have parsed messages."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Test message"}],
                    },
                }
            )
            + "\n"
        )
        hook_input: dict[str, Any] = {"transcript_path": str(transcript)}
        reader = get_transcript_reader(hook_input)
        assert reader is not None
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert msgs[0].content == "Test message"


class TestHasRecentStopHookBlock:
    """Test has_recent_stop_hook_block() — the discriminator that distinguishes
    a genuine Stop-hook re-entry (Claude Code re-fires Stop after a prior block
    was emitted) from a silent abnormal stop where stop_hook_active=true is set
    despite no prior block.

    A genuine block leaves two markers in the transcript JSONL:
      1. A user-role entry whose message.content begins with
         "Stop hook feedback:" (Claude Code injects this so the model sees the
         block reason).
      2. An attachment entry of type "hook_blocking_error" with hookEvent=Stop.

    Either marker, present in the recent tail of the transcript, signals a
    genuine re-entry. Absence signals the silent-stop bug.
    """

    def _write_lines(self, path: Path, lines: list[dict[str, Any]]) -> None:
        with path.open("w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")

    def test_returns_false_for_missing_path(self) -> None:
        """Missing transcript_path → False (cannot prove a recent block)."""
        assert has_recent_stop_hook_block(None) is False
        assert has_recent_stop_hook_block("") is False

    def test_returns_false_for_nonexistent_file(self, tmp_path: Path) -> None:
        """Nonexistent transcript file → False."""
        assert has_recent_stop_hook_block(str(tmp_path / "no_such.jsonl")) is False

    def test_returns_false_for_empty_transcript(self, tmp_path: Path) -> None:
        """Empty transcript → no block markers found → False."""
        path = tmp_path / "empty.jsonl"
        path.touch()
        assert has_recent_stop_hook_block(str(path)) is False

    def test_returns_true_when_stop_hook_feedback_user_message(self, tmp_path: Path) -> None:
        """A 'Stop hook feedback:' user message in the recent tail → True."""
        path = tmp_path / "transcript.jsonl"
        self._write_lines(
            path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "ok"}],
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": (
                            "Stop hook feedback:\n"
                            "You stopped without explaining why. Either:\n"
                            "1. Prefix your stop message with STOPPING BECAUSE:..."
                        ),
                    },
                },
            ],
        )
        assert has_recent_stop_hook_block(str(path)) is True

    def test_returns_true_when_hook_blocking_error_attachment(self, tmp_path: Path) -> None:
        """A hook_blocking_error attachment in the recent tail → True."""
        path = tmp_path / "transcript.jsonl"
        self._write_lines(
            path,
            [
                {
                    "type": "attachment",
                    "attachment": {
                        "type": "hook_blocking_error",
                        "hookName": "Stop",
                        "hookEvent": "Stop",
                        "blockingError": {"blockingError": "You stopped..."},
                    },
                },
            ],
        )
        assert has_recent_stop_hook_block(str(path)) is True

    def test_returns_false_when_only_tool_error_no_block_marker(self, tmp_path: Path) -> None:
        """Tool errors are NOT block markers — bug shape returns False.

        This is the discriminator's main job: a tool_use_error in a tool_result
        is NOT evidence of a Stop hook block, so the re-entry guard must NOT
        trigger when only a tool error precedes the stop.
        """
        path = tmp_path / "transcript.jsonl"
        self._write_lines(
            path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Edit",
                                "input": {"file_path": "/x", "old_string": "a"},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "is_error": True,
                                "content": (
                                    "<tool_use_error>"
                                    "File has not been read yet"
                                    "</tool_use_error>"
                                ),
                                "tool_use_id": "tu_1",
                            }
                        ],
                    },
                },
            ],
        )
        assert has_recent_stop_hook_block(str(path)) is False

    def test_returns_false_when_only_normal_assistant_text(self, tmp_path: Path) -> None:
        """Plain assistant text messages do not constitute a block marker."""
        path = tmp_path / "transcript.jsonl"
        self._write_lines(
            path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "All done"}],
                    },
                },
            ],
        )
        assert has_recent_stop_hook_block(str(path)) is False

    def test_returns_false_when_block_marker_is_too_far_back(self, tmp_path: Path) -> None:
        """A 'Stop hook feedback:' entry far before the tail → False.

        The default lookback window is 20 lines; a block marker outside that
        window does not count as a recent re-entry signal.
        """
        path = tmp_path / "transcript.jsonl"
        # Old block marker, then 25 unrelated entries
        entries: list[dict[str, Any]] = [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "Stop hook feedback:\nYou stopped without explaining why.",
                },
            },
        ]
        for i in range(25):
            entries.append(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": f"msg {i}"}],
                    },
                }
            )
        self._write_lines(path, entries)
        assert has_recent_stop_hook_block(str(path)) is False

    def test_returns_true_when_block_marker_within_lookback(self, tmp_path: Path) -> None:
        """A 'Stop hook feedback:' within the lookback window → True."""
        path = tmp_path / "transcript.jsonl"
        entries: list[dict[str, Any]] = []
        # 5 padding entries
        for i in range(5):
            entries.append(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": f"msg {i}"}],
                    },
                }
            )
        # Block marker close to tail
        entries.append(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "Stop hook feedback:\nYou stopped without explaining why.",
                },
            }
        )
        # 3 padding after
        for i in range(3):
            entries.append(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": f"after {i}"}],
                    },
                }
            )
        self._write_lines(path, entries)
        assert has_recent_stop_hook_block(str(path)) is True

    def test_handles_malformed_jsonl_lines(self, tmp_path: Path) -> None:
        """Malformed JSON lines must not raise — they're just skipped."""
        path = tmp_path / "transcript.jsonl"
        with path.open("w") as f:
            f.write("not valid json\n")
            f.write("{incomplete\n")
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": "Stop hook feedback:\nYou stopped...",
                        },
                    }
                )
                + "\n"
            )
        assert has_recent_stop_hook_block(str(path)) is True

    def test_handles_unicode_decode_error(self, tmp_path: Path) -> None:
        """Invalid UTF-8 bytes must not raise — function returns False."""
        path = tmp_path / "transcript.jsonl"
        with path.open("wb") as f:
            f.write(b"\xff\xfe invalid utf-8 \x80\x81")
        assert has_recent_stop_hook_block(str(path)) is False

    def test_handles_oserror_on_open(self, tmp_path: Path, monkeypatch: Any) -> None:
        """An unexpected OSError on open() is logged and returns False."""
        path = tmp_path / "transcript.jsonl"
        path.write_text("{}\n")

        original_open = open

        def raising_open(*args: Any, **kwargs: Any) -> Any:
            if args and str(args[0]) == str(path):
                raise OSError("simulated I/O error")
            return original_open(*args, **kwargs)

        monkeypatch.setattr("builtins.open", raising_open)
        assert has_recent_stop_hook_block(str(path)) is False

    def test_skips_empty_lines(self, tmp_path: Path) -> None:
        """Blank lines in the transcript are skipped without error."""
        path = tmp_path / "transcript.jsonl"
        with path.open("w") as f:
            f.write("\n")
            f.write("   \n")
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": "Stop hook feedback:\nYou stopped...",
                        },
                    }
                )
                + "\n"
            )
        assert has_recent_stop_hook_block(str(path)) is True

    def test_skips_non_dict_entries(self, tmp_path: Path) -> None:
        """JSON entries that parse as non-dict (lists, strings) are skipped."""
        path = tmp_path / "transcript.jsonl"
        with path.open("w") as f:
            f.write(json.dumps(["array", "entry"]) + "\n")
            f.write(json.dumps("plain string") + "\n")
            f.write(json.dumps(42) + "\n")
        assert has_recent_stop_hook_block(str(path)) is False


class _CountingHandle:
    """A file handle that tallies how many bytes are actually read."""

    def __init__(self, handle: Any, tally: list[int]) -> None:
        self._handle = handle
        self._tally = tally

    def read(self, *args: Any) -> Any:
        data = self._handle.read(*args)
        self._tally.append(len(data))
        return data

    def __iter__(self) -> Any:
        # Iteration must be counted too, or this guard is vacuous: the defect
        # being pinned (``deque(f, maxlen=N)``) consumed the file by ITERATING
        # it, never calling read(), so a read()-only tally would score the
        # original bug at zero bytes and pass.
        for line in self._handle:
            self._tally.append(len(line))
            yield line

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)

    def __enter__(self) -> "_CountingHandle":
        self._handle.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self._handle.__exit__(*exc)


class TestTheTailReadIsBounded:
    """The read cost must not scale with transcript size (Plan 00231).

    This function is called only when ``stop_hook_active`` is set — that is,
    only during a deny/re-fire loop — so the path that runs repeatedly was the
    one paying the whole-file cost. Byte accounting pins the fix behaviourally;
    ``scripts/qa/check_bounded_reads.py`` pins the code shape that caused it.
    """

    @staticmethod
    def _write_large_transcript(path: Path, *, with_marker: bool) -> None:
        padding = json.dumps(
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "x" * 500}]},
            }
        )
        with path.open("w") as f:
            for _ in range(4000):
                f.write(padding + "\n")
            if with_marker:
                f.write(
                    json.dumps(
                        {
                            "type": "user",
                            "message": {"role": "user", "content": "Stop hook feedback:\nstopped"},
                        }
                    )
                    + "\n"
                )

    def test_reads_far_less_than_the_whole_file(self, tmp_path: Path, monkeypatch: Any) -> None:
        """A marker at the tail is found without reading the file that precedes it."""
        import builtins

        from claude_code_hooks_daemon.utils import stop_hook_helpers

        path = tmp_path / "transcript.jsonl"
        self._write_large_transcript(path, with_marker=True)
        file_size = path.stat().st_size
        assert file_size > 2_000_000, "fixture must be large enough to expose a full read"

        tally: list[int] = []

        def counting_open(*args: Any, **kwargs: Any) -> Any:
            return _CountingHandle(builtins.open(*args, **kwargs), tally)

        monkeypatch.setattr(stop_hook_helpers, "open", counting_open, raising=False)

        assert has_recent_stop_hook_block(str(path)) is True
        assert sum(tally) < file_size // 4, (
            f"read {sum(tally)} bytes of a {file_size}-byte transcript — "
            "the tail read is no longer bounded"
        )

    def test_lookback_window_still_bounds_the_search(self, tmp_path: Path) -> None:
        """Reading less must not mean matching more: an old marker stays invisible."""
        path = tmp_path / "transcript.jsonl"
        self._write_large_transcript(path, with_marker=False)
        assert has_recent_stop_hook_block(str(path)) is False
