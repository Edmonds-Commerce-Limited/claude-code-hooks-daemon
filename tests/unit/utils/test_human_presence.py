"""Tests for human_presence: is a genuine human prompt recent in this session (N274)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.utils.human_presence import (
    HUMAN_PRESENCE_WINDOW_SECONDS,
    human_prompt_within,
)

SESSION = "session-a"
NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC).timestamp()
WINDOW = 30 * 60.0


def _stamp(seconds_ago: float) -> str:
    return datetime.fromtimestamp(NOW - seconds_ago, tz=UTC).isoformat().replace("+00:00", "Z")


def _user(
    content: Any,
    seconds_ago: float = 60.0,
    *,
    session: str = SESSION,
    origin: str | None = "human",
    **extra: Any,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "type": "user",
        "message": {"role": "user", "content": content},
        "timestamp": _stamp(seconds_ago),
        "sessionId": session,
        **extra,
    }
    if origin is not None:
        record["origin"] = {"kind": origin}
    return record


def _write(tmp_path: Path, records: list[dict[str, Any]], *, raw: str = "") -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records) + raw,
        encoding="utf-8",
    )
    return path


def _present(path: Path, session: str | None = SESSION) -> bool:
    return human_prompt_within(path, session, NOW, WINDOW)


def test_window_constant_is_thirty_minutes() -> None:
    assert HUMAN_PRESENCE_WINDOW_SECONDS == 30 * 60


class TestGenuinePrompts:
    def test_recent_human_prompt_counts(self, tmp_path: Path) -> None:
        assert _present(_write(tmp_path, [_user("human here - take me through it")]))

    def test_old_human_prompt_does_not_count(self, tmp_path: Path) -> None:
        assert not _present(_write(tmp_path, [_user("hello", seconds_ago=WINDOW + 1)]))

    def test_prompt_just_inside_window_counts(self, tmp_path: Path) -> None:
        assert _present(_write(tmp_path, [_user("hello", seconds_ago=WINDOW - 1)]))

    def test_latest_genuine_prompt_decides(self, tmp_path: Path) -> None:
        records = [_user("old", seconds_ago=WINDOW * 4), _user("new", seconds_ago=10)]
        assert _present(_write(tmp_path, records))

    def test_prompt_without_origin_field_counts(self, tmp_path: Path) -> None:
        assert _present(_write(tmp_path, [_user("hello", origin=None)]))

    def test_future_timestamp_does_not_count(self, tmp_path: Path) -> None:
        assert not _present(_write(tmp_path, [_user("hello", seconds_ago=-600)]))


class TestAutomatedPromptsDoNotCount:
    @pytest.mark.parametrize(
        "content",
        [
            "[tick:failsafe]\n**FAILSAFE RECOVERY CHECK** go",
            "[tick:job:issue-sdlc]\nISSUE SDLC TICK",
            "[tick:watchdog]\nwatchdog",
            "\U0001f916 [ccy-supervisor 2026-09-30 11:59:00] continue",
            "\U0001f916 [ccy-supervisor] automated goal",
            '<teammate-message teammate_id="x">hi</teammate-message>',
            "<task-notification>done</task-notification>",
            "<system-reminder>x</system-reminder>",
        ],
    )
    def test_marker_content_does_not_count(self, tmp_path: Path, content: str) -> None:
        assert not _present(_write(tmp_path, [_user(content)]))

    @pytest.mark.parametrize("kind", ["task-notification", "peer", "auto-continuation"])
    def test_non_human_origin_does_not_count(self, tmp_path: Path, kind: str) -> None:
        assert not _present(_write(tmp_path, [_user("plain words", origin=kind)]))

    @pytest.mark.parametrize("flag", ["isMeta", "isSidechain", "isCompactSummary"])
    def test_flagged_record_does_not_count(self, tmp_path: Path, flag: str) -> None:
        record = _user("plain words")
        record[flag] = True
        assert not _present(_write(tmp_path, [record]))

    def test_tool_result_block_does_not_count(self, tmp_path: Path) -> None:
        blocks = [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]
        assert not _present(_write(tmp_path, [_user(blocks)]))

    def test_recent_tick_after_old_human_prompt_does_not_renew_presence(
        self, tmp_path: Path
    ) -> None:
        records = [
            _user("hello", seconds_ago=WINDOW * 3),
            _user("[tick:failsafe]\ngo", seconds_ago=5),
        ]
        assert not _present(_write(tmp_path, records))

    def test_recent_tick_does_not_hide_recent_human_prompt(self, tmp_path: Path) -> None:
        records = [_user("hello", seconds_ago=120), _user("[tick:failsafe]\ngo", seconds_ago=5)]
        assert _present(_write(tmp_path, records))

    def test_assistant_records_are_ignored(self, tmp_path: Path) -> None:
        record = {"type": "assistant", "timestamp": _stamp(1), "sessionId": SESSION}
        assert not _present(_write(tmp_path, [record]))


class TestSessionScoping:
    def test_other_sessions_prompt_does_not_count(self, tmp_path: Path) -> None:
        assert not _present(_write(tmp_path, [_user("hello", session="session-b")]))

    def test_unknown_current_session_accepts_any_record(self, tmp_path: Path) -> None:
        assert _present(_write(tmp_path, [_user("hello", session="session-b")]), session=None)


class TestUnreadableTranscripts:
    def test_missing_file_is_not_presence(self, tmp_path: Path) -> None:
        assert not _present(tmp_path / "absent.jsonl")

    def test_empty_file_is_not_presence(self, tmp_path: Path) -> None:
        assert not _present(_write(tmp_path, []))

    def test_garbage_lines_are_skipped(self, tmp_path: Path) -> None:
        path = _write(tmp_path, [_user("hello")], raw="{not json\n[1, 2]\n")
        assert _present(path)

    @pytest.mark.parametrize("stamp", ["not a date", None, 12345])
    def test_bad_timestamp_is_not_presence(self, tmp_path: Path, stamp: Any) -> None:
        record = _user("hello")
        record["timestamp"] = stamp
        assert not _present(_write(tmp_path, [record]))

    def test_directory_path_is_not_presence(self, tmp_path: Path) -> None:
        assert not _present(tmp_path)


class TestLargeTranscripts:
    def test_prompt_before_a_huge_tail_is_not_found(self, tmp_path: Path) -> None:
        filler = _user([{"type": "tool_result", "content": "x" * 4096}], seconds_ago=1)
        records = [_user("hello", seconds_ago=30)] + [filler] * 600
        # Only the tail is read, so a prompt buried under megabytes of tool
        # output reads as absent: the fail-closed direction.
        assert not _present(_write(tmp_path, records))

    def test_prompt_inside_the_tail_is_found_despite_a_partial_first_line(
        self, tmp_path: Path
    ) -> None:
        filler = _user([{"type": "tool_result", "content": "x" * 4096}], seconds_ago=1)
        records = [filler] * 600 + [_user("hello", seconds_ago=30)]
        assert _present(_write(tmp_path, records))
