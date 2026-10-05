"""N86: an over-length AF_UNIX path is definitively not live, not indeterminate."""

from pathlib import Path

from claude_code_hooks_daemon.daemon.paths import socket_path_overflow
from claude_code_hooks_daemon.daemon.server import _socket_liveness_sync, _SocketLiveness


class TestOverLengthSocketPath:
    """No socket can be bound at a path past the AF_UNIX limit, so nothing listens there."""

    def test_an_over_length_path_is_not_live(self, tmp_path: Path) -> None:
        path = tmp_path / ("d" * 120) / "daemon.sock"
        assert socket_path_overflow(path) > 0
        assert _socket_liveness_sync(path) is _SocketLiveness.NOT_LIVE

    def test_an_absent_short_path_is_still_not_live(self, tmp_path: Path) -> None:
        assert _socket_liveness_sync(tmp_path / "s.sock") is _SocketLiveness.NOT_LIVE
