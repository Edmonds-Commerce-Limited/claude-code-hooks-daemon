"""The daemon publishes where its per-event sockets are when that is not the natural place.

Generated forwarders carry no machine-specific path (Plan 00609), so the short
fallback events directory used on an AF_UNIX overflow reaches them through a
two-line location file: the untracked dir it was written for, then the events
dir.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon import paths
from claude_code_hooks_daemon.daemon.paths import (
    event_socket_dir_is_fallback,
    events_dir_location_file,
    publish_events_dir_location,
)


@pytest.fixture(autouse=True)
def _pinned_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "_get_hostname_suffix", lambda: "-testhost")


def _deep(tmp_path: Path) -> Path:
    untracked = tmp_path / ("d" * 80) / "untracked"
    untracked.mkdir(parents=True)
    assert event_socket_dir_is_fallback(untracked)
    return untracked


def test_the_location_file_sits_beside_the_natural_events_dir(tmp_path: Path) -> None:
    assert events_dir_location_file(tmp_path) == tmp_path / "events-testhost.location"


def test_an_overflowing_layout_publishes_untracked_dir_then_events_dir(tmp_path: Path) -> None:
    untracked = _deep(tmp_path)
    events = Path("/run/user/1000/hooks-daemon-x-events")

    publish_events_dir_location(untracked, events)

    assert events_dir_location_file(untracked).read_text() == f"{untracked}\n{events}\n"
    assert list(untracked.glob("*.tmp")) == []


def test_a_natural_layout_publishes_nothing_and_clears_a_stale_file() -> None:
    # A short directory: pytest's tmp_path is long enough to overflow by itself.
    with tempfile.TemporaryDirectory(prefix="el-") as short:
        untracked = Path(short)
        assert not event_socket_dir_is_fallback(untracked)
        stale = events_dir_location_file(untracked)
        stale.write_text("stale\n")

        publish_events_dir_location(untracked, untracked / "events-testhost")

        assert not stale.exists()


def test_a_failed_write_leaves_no_temp_file_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-10: a write that fails part-way must not strand its scratch file."""
    untracked = _deep(tmp_path)
    real_write_text = Path.write_text

    def partial_then_fail(self: Path, data: str, *args: object, **kwargs: object) -> int:
        real_write_text(self, data[:3])
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", partial_then_fail)

    with pytest.raises(OSError, match="disk full"):
        publish_events_dir_location(untracked, Path("/run/user/1/a"))

    assert list(untracked.iterdir()) == []


def test_publishing_again_replaces_the_file(tmp_path: Path) -> None:
    untracked = _deep(tmp_path)
    publish_events_dir_location(untracked, Path("/run/user/1/a"))
    publish_events_dir_location(untracked, Path("/run/user/1/b"))

    assert events_dir_location_file(untracked).read_text() == f"{untracked}\n/run/user/1/b\n"
