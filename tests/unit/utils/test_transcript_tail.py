"""Tests for the transcript tail reader and agent-transcript resolver (Plan 00471 Task 2.0)."""

from __future__ import annotations

import io
import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any, BinaryIO, cast

import pytest

from claude_code_hooks_daemon.utils.transcript_tail import (
    TailReading,
    find_agent_transcript,
    input_token_equivalents,
    read_tail,
    resolve_agent_transcript,
    subagents_dir,
)


def assistant(
    ctx_read: int,
    *,
    request_id: str = "req_1",
    model: str = "claude-opus-5-5",
    stop_reason: str | None = "tool_use",
    output: int = 10,
    pad: int = 0,
) -> str:
    """One assistant record line whose context is ``ctx_read + 10`` tokens."""
    record: dict[str, Any] = {
        "type": "assistant",
        "requestId": request_id,
        "message": {
            "model": model,
            "id": f"msg_{request_id}",
            "stop_reason": stop_reason,
            "usage": {
                "input_tokens": 4,
                "cache_creation_input_tokens": 6,
                "cache_read_input_tokens": ctx_read,
                "output_tokens": output,
            },
            "content": [{"type": "text", "text": "x" * pad}],
        },
    }
    return json.dumps(record)


def user(text: str = "go") -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


def synthetic() -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "model": "<synthetic>",
                "stop_reason": "stop_sequence",
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }
    )


def write_lines(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class CountingFile(io.RawIOBase):
    """A binary file wrapper counting read calls."""

    def __init__(self, inner: BinaryIO, counter: list[int]) -> None:
        self._inner = inner
        self._counter = counter

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._inner.seek(offset, whence)

    def read(self, size: int = -1) -> bytes:
        self._counter.append(size)
        return self._inner.read(size)

    def close(self) -> None:
        self._inner.close()
        super().close()


def counting_opener(reads: list[int]) -> Callable[[Path], IO[bytes]]:
    """An opener for :func:`read_tail` that records every read call in ``reads``."""

    def opener(path: Path) -> IO[bytes]:
        return cast("IO[bytes]", CountingFile(path.open("rb"), reads))

    return opener


class TestReadTail:
    def test_context_is_input_plus_cache_of_last_real_request(self, tmp_path: Path) -> None:
        path = write_lines(tmp_path / "t.jsonl", [assistant(100), assistant(500, request_id="r2")])
        reading = read_tail(path)
        assert reading == TailReading(context_tokens=510, model="claude-opus-5-5", stopped=False)

    def test_synthetic_tail_is_skipped(self, tmp_path: Path) -> None:
        path = write_lines(tmp_path / "t.jsonl", [assistant(300), synthetic(), synthetic()])
        reading = read_tail(path)
        assert reading is not None
        assert reading.context_tokens == 310

    def test_end_turn_as_last_conversational_record_is_stopped(self, tmp_path: Path) -> None:
        lines = [assistant(300, stop_reason="end_turn"), json.dumps({"type": "system"})]
        reading = read_tail(write_lines(tmp_path / "t.jsonl", lines))
        assert reading is not None and reading.stopped is True

    def test_user_record_after_end_turn_means_running(self, tmp_path: Path) -> None:
        lines = [assistant(300, stop_reason="end_turn"), user("NEW TASK")]
        reading = read_tail(write_lines(tmp_path / "t.jsonl", lines))
        assert reading is not None and reading.stopped is False

    def test_no_usage_anywhere_is_none(self, tmp_path: Path) -> None:
        assert read_tail(write_lines(tmp_path / "t.jsonl", [user(), synthetic()])) is None

    def test_empty_file_is_none(self, tmp_path: Path) -> None:
        path = tmp_path / "t.jsonl"
        path.write_bytes(b"")
        assert read_tail(path) is None

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            read_tail(tmp_path / "absent.jsonl")

    def test_garbage_lines_are_ignored(self, tmp_path: Path) -> None:
        path = write_lines(tmp_path / "t.jsonl", [assistant(50), "not json", "[1, 2]"])
        reading = read_tail(path)
        assert reading is not None and reading.context_tokens == 60

    def test_a_non_json_line_is_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = write_lines(tmp_path / "t.jsonl", [assistant(50), "not json"])
        with caplog.at_level(logging.DEBUG):
            read_tail(path)
        assert "not a transcript record" in caplog.text

    def test_trailing_line_larger_than_the_window_doubles(self, tmp_path: Path) -> None:
        """A 300 KB trailing record is found by doubling the 64 KiB window."""
        lines = [user()] * 3 + [assistant(777, pad=300_000)]
        path = write_lines(tmp_path / "t.jsonl", lines)
        reads: list[int] = []
        reading = read_tail(path, opener=counting_opener(reads))
        assert reading is not None and reading.context_tokens == 787
        assert 1 < len(reads) <= 4

    def test_read_count_does_not_scale_with_file_size(self, tmp_path: Path) -> None:
        """The same number of reads for a 1 MB and an 8 MB transcript."""
        counts = []
        for megabytes in (1, 8):
            filler = [assistant(i, request_id=f"r{i}", pad=1000) for i in range(megabytes * 1000)]
            path = write_lines(
                tmp_path / f"t{megabytes}.jsonl", [*filler, assistant(9, request_id="z")]
            )
            assert path.stat().st_size >= megabytes * 1_000_000
            reads: list[int] = []
            reading = read_tail(path, opener=counting_opener(reads))
            assert reading is not None and reading.context_tokens == 19
            counts.append(len(reads))
        assert counts[0] == counts[1] == 1


class TestInputTokenEquivalents:
    def test_weights(self) -> None:
        usage = {
            "input_tokens": 100,
            "cache_creation_input_tokens": 300,
            "cache_read_input_tokens": 1000,
            "output_tokens": 10,
            "cache_creation": {"ephemeral_1h_input_tokens": 100},
        }
        # 100 + 200*1.25 + 100*2 + 1000*0.1 + 10*5
        assert input_token_equivalents(usage) == pytest.approx(700.0)

    def test_junk_counts_as_zero(self) -> None:
        assert input_token_equivalents({"input_tokens": "x", "output_tokens": True}) == 0.0


class TestResolver:
    def test_agent_own_transcript_is_used_directly(self, tmp_path: Path) -> None:
        own = tmp_path / "s1" / "subagents" / "agent-abc.jsonl"
        own.parent.mkdir(parents=True)
        own.write_text("")
        assert resolve_agent_transcript(str(own), "s1", "abc") == own

    def test_main_transcript_derives_agent_path(self, tmp_path: Path) -> None:
        main = tmp_path / "s1.jsonl"
        main.write_text("")
        agent = tmp_path / "s1" / "subagents" / "agent-abc.jsonl"
        agent.parent.mkdir(parents=True)
        agent.write_text("")
        assert resolve_agent_transcript(str(main), "s1", "abc") == agent

    def test_neither_exists_is_none(self, tmp_path: Path) -> None:
        assert resolve_agent_transcript(str(tmp_path / "s1.jsonl"), "s1", "abc") is None

    def test_missing_inputs_are_none(self) -> None:
        assert resolve_agent_transcript("", "s1", "abc") is None
        assert resolve_agent_transcript("/x/s1.jsonl", "s1", "") is None

    def test_agent_id_cannot_escape_the_directory(self, tmp_path: Path) -> None:
        assert resolve_agent_transcript(str(tmp_path / "s1.jsonl"), "s1", "../../etc") is None

    def test_find_agent_transcript_picks_the_newest_confirmed_generation(
        self, tmp_path: Path
    ) -> None:
        old = tmp_path / "agent-aw-1111.jsonl"
        new = tmp_path / "agent-aw-2222.jsonl"
        other = tmp_path / "agent-aw-3333.jsonl"
        for index, path in enumerate((old, new, other)):
            path.write_text("", encoding="utf-8")
            meta = path.with_name(path.name.removesuffix(".jsonl") + ".meta.json")
            meta.write_text(json.dumps({"name": "w" if path != other else "x"}))
            os.utime(path, (1000 + index, 1000 + index))
        assert find_agent_transcript(tmp_path, "w") == new
        assert find_agent_transcript(tmp_path, "nobody") is None

    def test_find_agent_transcript_raises_when_the_directory_cannot_be_listed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(path: Path) -> Any:
            raise PermissionError(13, "Permission denied", str(path))

        monkeypatch.setattr("os.scandir", refuse)
        with pytest.raises(PermissionError):
            find_agent_transcript(tmp_path, "plan464-impl")

    def test_subagents_dir_for_both_shapes(self, tmp_path: Path) -> None:
        own = tmp_path / "s1" / "subagents" / "agent-abc.jsonl"
        assert subagents_dir(str(own), "s1") == own.parent
        assert subagents_dir(str(tmp_path / "s1.jsonl"), "s1") == tmp_path / "s1" / "subagents"
        assert subagents_dir("", "s1") is None
