"""Tests for the supervisor -> status-line transient message channel.

A GENERAL, reusable channel (the Ctrl+Z "ignored" notice is merely its first
consumer): the supervisor writes a small TTL-bounded JSON message file that the
daemon's status-line handler reads and renders, auto-omitting it once expired.

THREAD/PROCESS SAFETY is a first-class requirement here (see the module-level
note in ``claude-supervise.py``): the file is read by the daemon (a separate
process) on every status render and may be written by more than one supervisor
thread/process. Writes are atomic-replace via a private ``.{name}.{pid}.{tid}``
temp file so a reader never sees a partial file and concurrent writers never
clobber each other's temp path. These tests pin that contract.
"""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
write_status_message = _mod.write_status_message
StatusMessagePoster = _mod.StatusMessagePoster
_LOG_SUBDIRECTORY = _mod._LOG_SUBDIRECTORY
_STATUS_MESSAGE_FILENAME = _mod._STATUS_MESSAGE_FILENAME


def _message_path(untracked: Path) -> Path:
    return untracked / _LOG_SUBDIRECTORY / _STATUS_MESSAGE_FILENAME


class TestWriteStatusMessage:
    """The atomic ``write_status_message`` writer."""

    def test_writes_parseable_payload(self, tmp_path: Path) -> None:
        path = write_status_message(tmp_path, text="hello", expires_at=1234.5)
        assert path == _message_path(tmp_path)
        assert path is not None
        data = json.loads(path.read_text())
        assert data == {"text": "hello", "expires_at": 1234.5}

    def test_creates_supervise_subdir(self, tmp_path: Path) -> None:
        write_status_message(tmp_path, text="x", expires_at=1.0)
        assert (tmp_path / _LOG_SUBDIRECTORY).is_dir()

    def test_overwrites_previous_message(self, tmp_path: Path) -> None:
        write_status_message(tmp_path, text="first", expires_at=1.0)
        write_status_message(tmp_path, text="second", expires_at=2.0)
        data = json.loads(_message_path(tmp_path).read_text())
        assert data == {"text": "second", "expires_at": 2.0}

    def test_leaves_no_temp_file_behind(self, tmp_path: Path) -> None:
        write_status_message(tmp_path, text="x", expires_at=1.0)
        leftovers = list((tmp_path / _LOG_SUBDIRECTORY).glob(".*tmp"))
        assert leftovers == []

    def test_unwritable_dir_returns_none_not_raises(self, tmp_path: Path) -> None:
        # Make the 'supervise' subdir path a FILE so mkdir(parents=True) fails
        # with OSError -> the writer must fail-safe to None, never raise.
        clash = tmp_path / _LOG_SUBDIRECTORY
        clash.write_text("i am a file, not a dir")
        assert write_status_message(tmp_path, text="x", expires_at=1.0) is None


class TestStatusMessagePoster:
    """Thread-safe, rate-limited poster over the writer."""

    def test_first_post_writes(self, tmp_path: Path) -> None:
        poster = StatusMessagePoster(
            tmp_path,
            ttl_seconds=10.0,
            min_interval_seconds=1.0,
            wall_clock=lambda: 100.0,
            monotonic=lambda: 0.0,
        )
        path = poster.post("notice")
        assert path is not None
        data = json.loads(path.read_text())
        assert data == {"text": "notice", "expires_at": 110.0}

    def test_second_post_within_interval_is_suppressed(self, tmp_path: Path) -> None:
        clock = {"mono": 0.0}
        poster = StatusMessagePoster(
            tmp_path,
            min_interval_seconds=1.0,
            wall_clock=lambda: 0.0,
            monotonic=lambda: clock["mono"],
        )
        assert poster.post("a") is not None
        clock["mono"] = 0.5  # < 1.0s later
        assert poster.post("b") is None
        # File still holds the FIRST message (the suppressed post did not write).
        data = json.loads(_message_path(tmp_path).read_text())
        assert data["text"] == "a"

    def test_post_after_interval_writes_again(self, tmp_path: Path) -> None:
        clock = {"mono": 0.0}
        poster = StatusMessagePoster(
            tmp_path,
            min_interval_seconds=1.0,
            wall_clock=lambda: 0.0,
            monotonic=lambda: clock["mono"],
        )
        assert poster.post("a") is not None
        clock["mono"] = 1.5  # >= 1.0s later
        assert poster.post("b") is not None
        data = json.loads(_message_path(tmp_path).read_text())
        assert data["text"] == "b"

    def test_concurrent_posts_only_one_wins_the_interval(self, tmp_path: Path) -> None:
        # Many threads post at the same monotonic instant; the lock-guarded
        # rate limiter must let exactly ONE through (the rest suppressed), so
        # the file is written once and is never a corrupt partial.
        poster = StatusMessagePoster(
            tmp_path,
            min_interval_seconds=1.0,
            wall_clock=lambda: 0.0,
            monotonic=lambda: 0.0,
        )
        results: list[object] = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(8)

        def worker(n: int) -> None:
            barrier.wait()
            written = poster.post(f"msg-{n}")
            with results_lock:
                results.append(written)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        wrote = [r for r in results if r is not None]
        assert len(wrote) == 1
        # The written file is complete and parseable (no partial write).
        data = json.loads(_message_path(tmp_path).read_text())
        assert data["text"].startswith("msg-")
