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
_STATUS_LEVEL_INFO = _mod._STATUS_LEVEL_INFO
_STATUS_LEVEL_WARNING = _mod._STATUS_LEVEL_WARNING


def _message_path(untracked: Path) -> Path:
    return untracked / _LOG_SUBDIRECTORY / _STATUS_MESSAGE_FILENAME


class TestWriteStatusMessage:
    """The atomic ``write_status_message`` writer."""

    def test_writes_parseable_payload(self, tmp_path: Path) -> None:
        path = write_status_message(tmp_path, text="hello", expires_at=1234.5)
        assert path == _message_path(tmp_path)
        assert path is not None
        data = json.loads(path.read_text())
        # Level defaults to "info" when the caller does not specify one.
        assert data == {"text": "hello", "expires_at": 1234.5, "level": _STATUS_LEVEL_INFO}

    def test_writes_explicit_warning_level(self, tmp_path: Path) -> None:
        path = write_status_message(
            tmp_path, text="ctrl+z", expires_at=9.0, level=_STATUS_LEVEL_WARNING
        )
        assert path is not None
        data = json.loads(path.read_text())
        assert data == {"text": "ctrl+z", "expires_at": 9.0, "level": _STATUS_LEVEL_WARNING}

    def test_creates_supervise_subdir(self, tmp_path: Path) -> None:
        write_status_message(tmp_path, text="x", expires_at=1.0)
        assert (tmp_path / _LOG_SUBDIRECTORY).is_dir()

    def test_overwrites_previous_message(self, tmp_path: Path) -> None:
        write_status_message(tmp_path, text="first", expires_at=1.0)
        write_status_message(tmp_path, text="second", expires_at=2.0)
        data = json.loads(_message_path(tmp_path).read_text())
        assert data == {"text": "second", "expires_at": 2.0, "level": _STATUS_LEVEL_INFO}

    def test_leaves_no_temp_file_behind(self, tmp_path: Path) -> None:
        write_status_message(tmp_path, text="x", expires_at=1.0)
        leftovers = list((tmp_path / _LOG_SUBDIRECTORY).glob(".*tmp"))
        assert leftovers == []

    def test_countdown_flag_is_omitted_by_default(self, tmp_path: Path) -> None:
        """Absent means 'no countdown' -- keystroke hints keep their bare text."""
        path = write_status_message(tmp_path, text="ctrl+z", expires_at=9.0)
        assert path is not None
        assert "countdown" not in json.loads(path.read_text())

    def test_countdown_flag_rides_in_the_payload_when_requested(self, tmp_path: Path) -> None:
        path = write_status_message(tmp_path, text="audit", expires_at=9.0, countdown=True)
        assert path is not None
        data = json.loads(path.read_text())
        assert data["countdown"] is True
        assert data["text"] == "audit"

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
        assert data == {"text": "notice", "expires_at": 110.0, "level": _STATUS_LEVEL_INFO}

    def test_post_forwards_warning_level(self, tmp_path: Path) -> None:
        poster = StatusMessagePoster(
            tmp_path,
            ttl_seconds=10.0,
            min_interval_seconds=1.0,
            wall_clock=lambda: 100.0,
            monotonic=lambda: 0.0,
        )
        path = poster.post("ctrl+z", level=_STATUS_LEVEL_WARNING)
        assert path is not None
        data = json.loads(path.read_text())
        assert data == {"text": "ctrl+z", "expires_at": 110.0, "level": _STATUS_LEVEL_WARNING}

    def test_post_honours_a_per_post_ttl_and_countdown(self, tmp_path: Path) -> None:
        """An audit banner outlives a keystroke hint and counts itself down."""
        poster = StatusMessagePoster(
            tmp_path,
            ttl_seconds=10.0,
            min_interval_seconds=1.0,
            wall_clock=lambda: 100.0,
            monotonic=lambda: 0.0,
        )
        path = poster.post("audit", ttl_seconds=30.0, countdown=True)
        assert path is not None
        data = json.loads(path.read_text())
        assert data["expires_at"] == 130.0  # the override, not the poster default
        assert data["countdown"] is True

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


class TestAnInfoMessageYieldsToALiveWarning:
    """Plan 00319 F9 — the audit banner could clobber a live Ctrl+C hint.

    The finding proposed routing the banner through ``StatusMessagePoster``,
    but that cannot fix this: the poster's rate limit is a ``threading.Lock``
    and the two writers are in DIFFERENT PROCESSES — the audit banner is
    written by ``decide_once`` in the ``--worker`` subprocess, while every
    keystroke notice is written by the PTY host. A process-local lock
    serialises neither.

    What does work across processes is the message file itself. Every host
    notice is WARNING level and the audit banner is the only INFO writer, so
    the precedence rule is exact: an INFO write never replaces a WARNING that
    has not yet expired.
    """

    def test_info_does_not_replace_an_unexpired_warning(self, tmp_path: Path) -> None:
        write_status_message(
            tmp_path, text="ctrl+c hint", expires_at=100.0, level=_STATUS_LEVEL_WARNING
        )
        result = write_status_message(tmp_path, text="audit banner", expires_at=130.0, now=90.0)
        assert result is None
        assert json.loads(_message_path(tmp_path).read_text())["text"] == "ctrl+c hint"

    def test_info_replaces_a_warning_that_has_expired(self, tmp_path: Path) -> None:
        """Yielding forever would make the banner unreachable after any warning."""
        write_status_message(
            tmp_path, text="ctrl+c hint", expires_at=100.0, level=_STATUS_LEVEL_WARNING
        )
        result = write_status_message(tmp_path, text="audit banner", expires_at=140.0, now=110.0)
        assert result is not None
        assert json.loads(_message_path(tmp_path).read_text())["text"] == "audit banner"

    def test_info_replaces_a_live_info_message(self, tmp_path: Path) -> None:
        """The rule is about SEVERITY, not about recency."""
        write_status_message(tmp_path, text="older banner", expires_at=100.0)
        result = write_status_message(tmp_path, text="newer banner", expires_at=130.0, now=90.0)
        assert result is not None
        assert json.loads(_message_path(tmp_path).read_text())["text"] == "newer banner"

    def test_a_warning_always_wins_even_over_a_live_warning(self, tmp_path: Path) -> None:
        """A keystroke guard must never be silenced by an earlier notice."""
        write_status_message(tmp_path, text="ctrl+z", expires_at=100.0, level=_STATUS_LEVEL_WARNING)
        result = write_status_message(
            tmp_path,
            text="ctrl+c",
            expires_at=130.0,
            level=_STATUS_LEVEL_WARNING,
            now=90.0,
        )
        assert result is not None
        assert json.loads(_message_path(tmp_path).read_text())["text"] == "ctrl+c"

    def test_an_absent_file_is_not_a_live_warning(self, tmp_path: Path) -> None:
        result = write_status_message(tmp_path, text="audit banner", expires_at=130.0, now=90.0)
        assert result is not None

    def test_an_unreadable_file_does_not_block_the_write(self, tmp_path: Path) -> None:
        """Corrupt state must not wedge the channel shut — it fails OPEN here.

        A message nobody can parse is not one a human is reading, so treating
        it as a live warning would silence the banner until the TTL of a value
        we cannot even read elapses.
        """
        path = _message_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        result = write_status_message(tmp_path, text="audit banner", expires_at=130.0, now=90.0)
        assert result is not None
        assert json.loads(path.read_text())["text"] == "audit banner"
